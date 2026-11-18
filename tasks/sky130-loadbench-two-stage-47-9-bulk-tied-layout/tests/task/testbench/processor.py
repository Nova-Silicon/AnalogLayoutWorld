"""Read source-compatible waveform metrics, independent of DUT device names."""
import importlib.util
import json
from pathlib import Path
import numpy as np

_spec = importlib.util.spec_from_file_location('loadbench_source_metrics', Path(__file__).with_name('loadbench_source_metrics.py'))
_source = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_source)


def _process_case(case, work, values):
    work = Path(work)
    if case['measurement_kind'] == 'closed_loop_step':
        data = np.loadtxt(work / 'transient.tsv', skiprows=1)
        if data.ndim != 2 or data.shape[1] != 3 or not np.isfinite(data).all():
            raise ValueError('Step waveform is missing or invalid')
        t, vin, vout = data.T
        if len(t) < 2 or not np.all(np.diff(t) > 0) or t[-1] < 20e-6 * (1 - 1e-9):
            raise ValueError("The complete monotone 20 us step waveform is required")
        errors = []
        for left, right in ((4e-6, 4.9e-6), (9e-6, 9.9e-6), (14e-6, 14.9e-6), (19e-6, 19.9e-6)):
            mask = (t >= left) & (t <= right)
            if not mask.any():
                raise ValueError('Step waveform misses a required settled window')
            errors.append(float(np.max(np.abs(vin[mask] - vout[mask]))))
        return {'spec_step_settled_error': max(errors)}
    raw = lambda name: _source.parse_raw(work / (name + '.raw'))
    power, offset, icmr_min, icmr_max, vout_min, vout_max = _source.calc_dc(
        raw('result_op'), raw('result_dc'), raw('result_dc_vout'))
    gain, ft, pm, cmrr, psrr = _source.calc_ac(
        raw('result_ac_vdc'), raw('result_ac_vdd'), raw('result_ac_vtran'))
    measured = dict(P=power, Voffset=offset, icmr_min=icmr_min, icmr_max=icmr_max,
                    vout_min=vout_min, vout_max=vout_max, dc_gain=gain, ft=ft,
                    phaseMargin=pm, CMRR=cmrr, PSRR=psrr)
    # Prefix avoids replacing stdout's rounded .meas values with waveform values.
    return {'spec_' + name: float(value) for name, value in measured.items()}


def process_case(case, work, values):
    work = Path(work)
    try:
        measured = _process_case(case, work, values)
    except (OSError, ValueError, KeyError, IndexError, ZeroDivisionError, FloatingPointError) as error:
        (work / 'measurement_unavailable.json').write_text(json.dumps({'reason': str(error)}) + '\n')
        return {}
    finite = {name: value for name, value in measured.items() if np.isfinite(value)}
    if len(finite) != len(measured):
        (work / 'measurement_unavailable.json').write_text(json.dumps({'nonfinite_metrics': sorted(set(measured) - set(finite))}) + '\n')
    return finite
