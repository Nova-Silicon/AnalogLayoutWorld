"""Accepted POR-subblock measurements; raw waveforms and failure reasons retained."""
import json
from pathlib import Path
import numpy as np


def crossing(t, x, threshold, direction):
    mask = ((x[:-1] < threshold) & (x[1:] >= threshold)) if direction == "rise" else ((x[:-1] > threshold) & (x[1:] <= threshold))
    ids = np.flatnonzero(mask)
    return t[ids] + (threshold - x[ids]) / (x[ids + 1] - x[ids]) * (t[ids + 1] - t[ids])


def unavailable(work, reason):
    (work / 'measurement_unavailable.json').write_text(json.dumps({'reason': reason}) + '\n')
    return {}  # Required values stay missing: design does not earn this case.


def process_case(case, work, values):
    work = Path(work)
    try:
        data = np.loadtxt(work / 'wave.tsv', skiprows=1)
    except (OSError, ValueError) as error:
        return unavailable(work, 'Waveform unavailable: ' + str(error))
    if data.ndim != 2 or data.shape[1] != 4 or len(data) < 2 or not np.isfinite(data).all():
        return unavailable(work, 'Waveform is empty, nonfinite or has unexpected columns')
    t, vin, vout, current = data.T
    if not np.all(np.diff(t) > 0) or t[-1] <= 0:
        return unavailable(work, 'Waveform time coordinate is not strictly increasing')
    voltage = case['supply_V']
    if case['measurement_kind'] == 'schmitt_trigger':
        if t[-1] < 45e-6 * (1 - 1e-9):
            return unavailable(work, 'The complete 45 us waveform is required for average power')
        rising = crossing(t, vout, voltage / 2, 'rise')
        falling = crossing(t, vout, voltage / 2, 'fall')
        if len(rising) != 2 or len(falling) != 2:
            return unavailable(work, f'Expected two rise/fall transitions, observed {len(rising)}/{len(falling)}')
        hi = np.interp(rising, t, vin)
        lo = np.interp(falling, t, vin)
        result = {}
        for name, vector in (('vth_rise_v', hi), ('vth_fall_v', lo), ('hysteresis_v', hi - lo)):
            for index, value in enumerate(vector):
                result[f'{name}__{index}'] = float(value)
        high, low = vin > .99 * voltage, vin < .01 * voltage
        if not high.any() or not low.any():
            return unavailable(work, 'Input waveform did not reach both endpoints')
        result.update(high_level_min_v=float(vout[high].min()), low_level_max_v=float(vout[low].max()),
                      average_power_uw=float(-voltage * np.trapezoid(current, t) / t[-1] * 1e6))
        return result
    rise = crossing(t, vout, voltage / 2, 'rise')
    fall = crossing(t, vout, voltage / 2, 'fall')
    steady = rise[(rise > .001) & (rise < .0025)]
    if len(steady) < 4:
        return unavailable(work, f'Insufficient steady oscillation edges: {len(steady)}')
    periods = np.diff(steady)
    duties = []
    for a, b in zip(steady[:-1], steady[1:]):
        falling = fall[(fall > a) & (fall < b)]
        if len(falling) == 1:
            duties.append((falling[0] - a) / (b - a))
    enabled = (t > .001) & (t < .0025)
    disabled = (t > .0033) & (t < .0038)
    restart = rise[rise > .00400001]
    first = rise[(rise > .00010001) & (rise < .003)]
    if (len(duties) != len(periods) or len(first) == 0 or len(restart) == 0 or enabled.sum() < 2
            or not disabled.any() or t[-1] < .006):
        return unavailable(work, 'Required duty/start/restart/disable window was not observed')
    return dict(frequency_hz=float(1 / np.median(periods)),
                period_variation_fraction=float(np.ptp(periods) / np.mean(periods)),
                duty_cycle_min=float(min(duties)), duty_cycle_max=float(max(duties)),
                startup_first_edge_s=float(first[0] - .00010001),
                restart_first_edge_s=float(restart[0] - .00400001),
                enabled_power_uw=float(-voltage * np.trapezoid(current[enabled], t[enabled]) / np.ptp(t[enabled]) * 1e6),
                disabled_current_na=float(-np.mean(current[disabled]) * 1e9),
                disabled_output_max_v=float(vout[disabled].max()))
