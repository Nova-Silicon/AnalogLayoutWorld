"""Finite evidence for two frozen source checkers' +inf timing sentinels.

This is a private measurement adapter, not a new settling algorithm. A bound
only replaces the checker's explicit ``+inf`` result after a successful run and
the complete, finite original observation window. Other nonfinite values keep
the generic runner's existing missing/invalid classification.
"""
import math
from pathlib import Path
import re


BOUND_STATUS = 'not_settled_in_window'
BOUND_FIELDS = {'status', 'lower_bound_s', 'reference_time_s',
                'window_end_s', 'last_error_v'}


def timing_fields(source, group):
    if group == 'cm_recovery' and hasattr(source, 'CM_RECOVERY_TIME_S_MAX'):
        return {'cm_recovery_time_s': source.CM_RECOVERY_TIME_S_MAX}
    if group == 'settling':
        fields = source.GROUP_FIELDS[group]
        return {name: source.SETTLING_TIME_S_MAX for name in fields
                if name in {'settling_time_s', 'settling_rise_time_s',
                            'settling_fall_time_s'}}
    return {}


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _complete_transient(source, case, tran, run):
    if run.get('returncode') != 0:
        return False
    # These frozen source fixtures use a literal numeric .tran stop time.
    # Refuse an unrecognized/changed fixture rather than guess its window.
    text = (Path(source.__file__).parent / 'benches' / case['bench']).read_text()
    stops = re.findall(r'^\s*\.tran\s+\S+\s+(\S+)', text, re.I | re.M)
    if len(stops) != 1:
        return False
    token = re.fullmatch(r'([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([munpf]?)',
                         stops[0], re.I)
    if not token:
        return False
    stop = float(token[1]) * {'': 1, 'm': 1e-3, 'u': 1e-6, 'n': 1e-9,
                             'p': 1e-12, 'f': 1e-15}[token[2].lower()]
    times = [value.real for value in tran.vector('time')]
    return (stop > 0 and len(times) >= 2
            and all(math.isfinite(value.real) and math.isfinite(value.imag)
                    for point in tran.points for value in point)
            and all(right > left for left, right in zip(times, times[1:]))
            and math.isclose(times[-1], stop, rel_tol=1e-9, abs_tol=1e-15))


def adapt_timing_sentinels(source, case, tran, run, metrics):
    """Preserve exact finite rows; recognize only proven window failures."""
    limits = timing_fields(source, case['group'])
    infinite = [name for name in limits if type(metrics.get(name)) is float
                and metrics[name] == math.inf]
    if not infinite or not _complete_transient(source, case, tran, run):
        return metrics
    times = [value.real for value in tran.vector('time')]
    result = dict(metrics)
    for name in infinite:
        if name in {'settling_rise_time_s', 'settling_fall_time_s'}:
            rise = name == 'settling_rise_time_s'
            reference = (source.SETTLING_RISE_REFERENCE_S if rise
                         else source.SETTLING_FALL_REFERENCE_S)
            end = (source.SETTLING_RISE_WINDOW_END_S if rise
                   else source.SETTLING_FALL_WINDOW_END_S)
            target = (source.SETTLING_COMMAND_FINAL_V if rise
                      else source.SETTLING_COMMAND_INITIAL_V)
            tolerance = source.SETTLING_TOLERANCE_V
            values = [value.real for value in tran.vector('v(vout)')]
        else:
            recovery = name == 'cm_recovery_time_s'
            command = 'v(vocm)' if recovery else 'v(err0)'
            target = (source.CM_RECOVERY_COMMAND_FINAL_V if recovery
                      else source.SETTLING_COMMAND_FINAL_V)
            tolerance = (source.CM_RECOVERY_BAND_V if recovery else
                         source.SETTLING_ERROR_FRACTION_MAX *
                         (source.SETTLING_COMMAND_FINAL_V - source.SETTLING_COMMAND_INITIAL_V))
            reference = source.edge_crossing_time(
                times, [value.real for value in tran.vector(command)], target)
            end = times[-1]
            pairs = zip(tran.vector('v(voutp)'), tran.vector('v(voutn)'))
            values = [0.5 * (p + n).real if recovery else (p - n).real
                      for p, n in pairs]
        indices = [i for i, time in enumerate(times) if reference <= time <= end]
        if not indices:
            continue
        last = indices[-1]
        bound = times[last] - reference
        residual = abs(values[last] - target)
        # Even an explicitly unsuccessful settling measurement is not a
        # certified SPEC failure when its observed lower bound is too short.
        if not math.isfinite(bound) or bound <= limits[name] or residual <= tolerance:
            continue
        result[name] = {'status': BOUND_STATUS, 'lower_bound_s': bound,
                        'reference_time_s': reference, 'window_end_s': times[last],
                        'last_error_v': residual}
    return result


def bounded_failure_checks(source, case, row):
    """Return a known failure only for the narrowly typed bound representation.

    ``None`` delegates every ordinary row to the unchanged source checker. The
    finite schema probe below validates *only* the remaining source fields; it
    is neither retained as a measurement nor used to evaluate source pass/fail.
    """
    if not isinstance(row, dict):
        return None
    limits = timing_fields(source, case['group'])
    bounds = {name: row[name] for name in limits if isinstance(row.get(name), dict)}
    if not bounds:
        return None
    probe = dict(row)
    for name, bound in bounds.items():
        if (set(bound) != BOUND_FIELDS or bound.get('status') != BOUND_STATUS
                or any(not _finite(bound.get(field)) for field in BOUND_FIELDS - {'status'})
                or bound['last_error_v'] < 0
                or bound['lower_bound_s'] <= limits[name]
                or not math.isclose(bound['window_end_s'] - bound['reference_time_s'],
                                    bound['lower_bound_s'], rel_tol=1e-12, abs_tol=1e-18)):
            raise ValueError(f'Invalid bounded timing evidence: {name}')
        probe[name] = limits[name]
    error = source.row_schema_error(probe)
    if error:
        raise ValueError(error)
    if any(row[key] != case[key] for key in ('group', 'bench', 'corner', 'vdd', 'temp_c')):
        raise ValueError('Bounded timing row differs from requested case')
    detail = '; '.join(f'{name} > {bound["lower_bound_s"]:.12g} s '
                       f'(required {limits[name]:.12g} s); '
                       f'last error {bound["last_error_v"]:.12g} V'
                       for name, bound in bounds.items())
    return [{'name': case['group'] + '_source_predicate', 'passed': False,
             'message': 'Original observation window completed without settling: ' + detail}]
