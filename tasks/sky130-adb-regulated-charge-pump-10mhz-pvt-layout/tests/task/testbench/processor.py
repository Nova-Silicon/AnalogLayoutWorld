"""Derived quantities from upstream scalar measurements; no new SPECs."""
import math


def process_case(case, work, values):
    if case.get('kind') == 'public_pump':
        return {}  # The public fixture directly measures its required scalars.
    required = case['source_measurements']
    if any(key not in values or not math.isfinite(values[key]) for key in required):
        return {}  # Missing source measurements remain failures, never zeros.
    if case['kind'] == 'oscillator':
        if values['period_10'] <= 0:
            return {}
        return {
            'adb_frequency_hz': 10 / values['period_10'],
            'adb_swing_v': values['clko_max'] - values['clko_min'],
            'adb_power_w': case['supply_v'] * abs(values['i_avdd_avg']),
        }
    if case['kind'] == 'pump_disabled':
        return {'adb_disabled_current_a': abs(values[required[0]])}
    average, maximum, minimum, current = required
    return {
        'adb_output_v': values[average],
        'adb_ripple_v': values[maximum] - values[minimum],
        'adb_enabled_current_a': abs(values[current]),
    }
