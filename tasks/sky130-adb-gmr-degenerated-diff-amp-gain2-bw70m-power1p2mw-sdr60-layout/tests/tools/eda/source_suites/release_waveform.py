"""Reject incomplete native waveforms before frozen source measurements.

The expected coverage comes from the actual private SPICE deck, not inferred
performance requirements. This only reads ngspice ASCII raw output.
"""
import math
from pathlib import Path
import re


def spice_number(token):
    match = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z]*)', token.lower())
    if not match:
        raise ValueError(f'Analysis range is not a numeric SPICE value: {token!r}')
    number, suffix = match.groups()
    factors = {'': 1, 't': 1e12, 'g': 1e9, 'meg': 1e6, 'k': 1e3,
               'm': 1e-3, 'u': 1e-6, 'n': 1e-9, 'p': 1e-12, 'f': 1e-15}
    key = 'meg' if suffix.startswith('meg') else suffix[:1]
    if key not in factors:
        raise ValueError(f'Unsupported SPICE suffix: {suffix!r}')
    return float(number) * factors[key]


def raw_axes(path):
    """Read each declared axis completely; malformed/truncated raw is an error."""
    lines = Path(path).read_text(errors='strict').splitlines()
    axes = []
    index = 0
    while index < len(lines):
        if not lines[index].startswith('Title:'):
            index += 1
            continue
        headers = {}
        while index < len(lines) and not lines[index].startswith('Variables:'):
            if ':' in lines[index]:
                key, value = lines[index].split(':', 1)
                headers[key.lower().strip()] = value.strip()
            index += 1
        variables, points = int(headers['no. variables']), int(headers['no. points'])
        if variables < 1 or points < 1:
            raise ValueError('Native raw plot is empty')
        index += 1
        name = lines[index].split()[1].lower()
        index += variables
        if index >= len(lines) or lines[index].strip() != 'Values:':
            raise ValueError('Expected ASCII raw Values section')
        index += 1
        values = []
        for point in range(points):
            while index < len(lines) and not lines[index].strip():
                index += 1
            fields = lines[index].split()
            if len(fields) != 2 or int(fields[0]) != point:
                raise ValueError('Missing or reordered native raw point')
            values.append(float(fields[1].split(',')[0]))
            index += variables
            if index > len(lines):
                raise ValueError('Truncated native raw point')
        axes.append({'name': name, 'plot': headers.get('plotname', ''), 'values': values})
    if not axes:
        raise ValueError('Native raw contains no plots')
    return axes


def require_axis(values, start, stop, *, first_tolerance=0.0, label='analysis'):
    if len(values) < 2 or not all(math.isfinite(value) for value in values):
        raise ValueError(f'{label}: missing or nonfinite native analysis axis')
    increasing = stop >= start
    if not all((right > left if increasing else right < left)
               for left, right in zip(values, values[1:])):
        raise ValueError(f'{label}: native analysis axis is not strictly monotonic')
    tolerance = max(abs(start), abs(stop), abs(stop - start)) * 1e-6
    if abs(values[0] - start) > max(first_tolerance, tolerance):
        raise ValueError(f'{label}: axis starts at {values[0]:g}, expected {start:g}')
    if abs(values[-1] - stop) > tolerance:
        raise ValueError(f'{label}: axis ends at {values[-1]:g}, expected {stop:g}')


def require_table_axis(path, start, stop, *, first_tolerance=0.0):
    """Validate first-column axes of native wrdata exports before FFT/integration."""
    values = []
    for line in Path(path).read_text().splitlines():
        fields = line.split()
        if not fields:
            continue
        try:
            values.append(float(fields[0]))
        except ValueError:
            if values:
                raise ValueError('Unexpected nonnumeric row inside native waveform table')
    require_axis(values, start, stop, first_tolerance=first_tolerance, label=Path(path).name)


def require_native_coverage(work, raw_path=None):
    """Validate every explicit transient/AC/noise/DC request in this raw deck."""
    work = Path(work)
    axes = raw_axes(work / 'analysis.raw' if raw_path is None else Path(raw_path))
    used = set()
    for line in (work / 'testbench.spi').read_text().splitlines():
        tokens = line.strip().lower().split()
        if not tokens:
            continue
        kind = tokens[0].lstrip('.')
        first_tolerance = 0.0
        expected_points = None
        if kind == 'tran':
            step, stop = map(spice_number, tokens[1:3])
            start = spice_number(tokens[3]) if len(tokens) > 3 and tokens[3] != 'uic' else 0.0
            first_tolerance = step * 1.01
            axis_name = 'time'
        elif kind in ('ac', 'noise'):
            offset = 1 if kind == 'ac' else 3
            mode, count_text, start_text, stop_text = tokens[offset:offset + 4]
            count = int(count_text)
            start, stop = map(spice_number, (start_text, stop_text))
            if mode in ('dec', 'oct'):
                base = 10 if mode == 'dec' else 2
                intervals = math.floor(math.log(stop / start, base) * count + 1e-7)
                stop = start * base ** (intervals / count)
                expected_points = intervals + 1
            elif mode != 'lin':
                raise ValueError(f'Unsupported frequency sweep: {mode}')
            else:
                expected_points = count
            axis_name = 'frequency'
        elif kind == 'dc':
            start, stop, step = map(spice_number, tokens[2:5])
            intervals = math.floor((stop - start) / step + 1e-7)
            stop = start + intervals * step
            expected_points = intervals + 1
            axis_name = 'v(v-sweep)' if tokens[1].startswith('v') else 'i(i-sweep)'
        else:
            continue
        candidates = [(index, axis) for index, axis in enumerate(axes)
                      if index not in used and axis['name'] == axis_name]
        if not candidates:
            raise ValueError(f'Missing native {kind} plot for {line.strip()}')
        index, axis = candidates[0]
        used.add(index)
        if expected_points is not None and len(axis['values']) != expected_points:
            raise ValueError(f'{kind}: native sweep has {len(axis["values"])} points, expected {expected_points}')
        require_axis(axis['values'], start, stop, first_tolerance=first_tolerance,
                     label=f'{kind} {axis["plot"]}')
