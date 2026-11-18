"""Source-specific OTA acceptance adapters; no PDK or source module changes.

Threshold tuples below are literal transcriptions of the cited source checker
functions. They are evaluated by each source's original threshold(), not by a
metric-name heuristic. Full-matrix source functions remain the consistency oracle.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import load_source, point_id


def check_rows(checks):
    return [{'name': name, 'passed': bool(passed), 'message': message}
            for name, passed, message in checks]


class OtaBase:
    def __init__(self, source_path: Path | None = None, reference: bool = False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        # Original utils.parse_measures bound to the original run_spice.
        self.parse_measures = self.source.run_spice.__globals__['parse_measures']

    def deck(self, case, design, model):
        text = (self.source.HERE / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        point = tuple(case['point'])
        # Keep the author's condition substitutions, but resolve actual inputs.
        substitutions = self.source.substitutions(point)
        substitutions[f'.lib "{self.source.DEFAULT_MODEL}" tt'] = f'.lib "{model}" {point[0]}'
        substitutions[f'.include "{self.source.DEFAULT_DESIGN}"'] = f'.include "{design}"'
        if case['bench'] == 'op_ac_noise':
            substitutions['set points = ( 0 1 2 3 4 5 6 7 8 )'] = f'set points = ( {self.source.point_index(point)} )'
        for old, new in substitutions.items():
            text = text.replace(old, str(new))
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Original OTA fixture with explicit ngspice title\n' + text
        return text, False

    def analyze(self, case, work, run):
        values = self.parse_measures((work / 'ngspice.log').read_text(errors='replace'))
        point = tuple(case['point'])
        if case['bench'] == 'op_ac_noise':
            prefix = f'm{self.source.point_index(point)}_'
            values = {name: values[prefix + name] for name in self.source.PVT_METRICS if prefix + name in values}
        row = {'bench': case['bench'], 'point': point, 'name': self.source.point_name(point), **values}
        if self.reference and self.slug == Miller60.slug and case['bench'] == 'op_ac' and point == self.source.NOMINAL:
            listing = work / 'netlist_expanded.txt'
            row['source_reference_device_policy_failures'] = (
                self.source.device_policy_failures(listing.read_text()) if listing.exists()
                else ['expanded netlist listing missing'])
        return row

    def normalized(self, case, row):
        row = {**row, 'point': tuple(row['point'])}
        if row['point'] != tuple(case['point']) or row['bench'] != case['bench']:
            raise ValueError('measurement row belongs to another requested condition/bench')
        if any(isinstance(value, float) and not math.isfinite(value) for value in row.values()):
            raise ValueError('nonfinite scalar cannot originate from the source finite-measurement parser')
        return row


class Ota5(OtaBase):
    slug = 'ota-5t-gain40-pm60-noise50uv-pvt'

    def plan(self):
        jobs = [('op_ac_noise', p) for p in self.source.PVT]
        jobs += [(bench, p) for bench in self.source.THREE_POINT_BENCHES for p in self.source.REPRESENTATIVE_POINTS]
        return [{'id': bench + '__' + point_id(p), 'score_group': point_id(p), 'bench': bench, 'point': p}
                for bench, p in jobs]

    def checks(self, case, row):
        row = self.normalized(case, row)
        if case['bench'] == 'op_ac_noise':
            return check_rows([*self.source.op_ac_checks([row], 1),
                               self.source.threshold([row], 1, self.source.NOISE_LIMIT)])
        # Literal source three_point_checks tuples, evaluated per represented PVT.
        spec = ('cmrr_50db', 'cmrr_db_1khz', 50, True, 1, 'dB') if case['bench'] == 'cmrr' else (
            'psrr_30db', 'psrr_db_1khz', 30, True, 1, 'dB')
        return check_rows([self.source.threshold([row], 1, spec)])

    def original_suite_checks(self, rows, run_summary):
        rows = [{**r, 'point': tuple(r['point'])} for r in rows]
        primary = [r for r in rows if r['bench'] == 'op_ac_noise']
        other = [r for r in rows if r['bench'] != 'op_ac_noise']
        return check_rows([*self.source.op_ac_checks(primary, len(self.source.PVT)),
                           self.source.threshold(primary, len(self.source.PVT), self.source.NOISE_LIMIT),
                           *self.source.three_point_checks(other)])


class MillerBase(OtaBase):
    def plan(self):
        jobs = [(bench, p) for bench in ('op_ac', 'noise') for p in self.source.PVT]
        jobs += [(bench, p) for bench in ('psrr', 'cmrr', 'swing', 'settling', 'slew')
                 for p in self.source.REPRESENTATIVE_POINTS]
        return [{'id': bench + '__' + point_id(p), 'score_group': point_id(p), 'bench': bench, 'point': p}
                for bench, p in jobs]

    def checks(self, case, row):
        row = self.normalized(case, row)
        bench = case['bench']
        result = []
        for spec in self.thresholds.get(bench, ()):
            result.append(self.source.threshold([row], 1, spec))
        if bench == 'op_ac':
            result.append(('no_0db_recrossing', 'ugb_recross_hz' not in row,
                           'Original primary_checks rejects every observed second 0 dB crossing.'))
            if tuple(case['point']) == self.source.NOMINAL:
                if self.slug == Miller60.slug:
                    failures = row.get('source_reference_device_policy_failures', ['source policy evidence missing']) if self.reference else []
                    result.append(self.source.nominal_functional(row, failures))
                else:
                    result.append(self.source.nominal_functional(row))
        elif bench == 'noise':
            complete = self.source.complete([row], 1, ('closed_loop_3db_hz', 'input_noise_vrms'))
            result.append(('noise_measurements_complete', complete, 'Both source noise measurements are mandatory.'))
            # Original noise_check checks bandwidth>10 only at the globally
            # maximum-noise row. reduce_suite below preserves that exact rule.
        return check_rows(result)

    def reduce_suite(self, records, report):
        noise = []
        for record in records:
            if record['case']['bench'] != 'noise' or record.get('error') or record['run']['returncode'] != 0 or not record.get('row'):
                continue
            row = {**record['row'], 'point': tuple(record['row']['point'])}
            noise.append(row)
        source = self.source.noise_check(noise)
        report['suite_reductions'] = check_rows([source])
        complete = self.source.complete(noise, len(self.source.PVT), ('closed_loop_3db_hz', 'input_noise_vrms'))
        if complete:
            worst = max(noise, key=lambda r: float(r['input_noise_vrms']))
            group = point_id(worst['point'])
            report['suite_reductions'][0]['depends_on'] = ['noise__' + point_id(p) for p in self.source.PVT]
            report['suite_reductions'][0]['failure_attribution'] = group
            if not source[1]:
                report['group_results'][group]['passed'] = False
                report['group_results'][group]['suite_failure'] = source[2]
        report['passed_group_count'] = sum(group['passed'] for group in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        from .release_reference_suites import apply_reduction, unassessed

        expected = [c for c in plan if c['bench'] == 'noise']
        if not expected:
            unassessed(report, 'selected_input_noise', 'No noise fixture selected.')
            return report
        by_id = {r['case']['id']: r['row'] for r in records
                 if not r.get('error') and r.get('row') and r['run']['returncode'] == 0}
        noise = [{**by_id[c['id']], 'point': tuple(by_id[c['id']]['point'])}
                 for c in expected if c['id'] in by_id]
        complete = self.source.complete(noise, len(expected),
                                        ('closed_loop_3db_hz', 'input_noise_vrms'))
        if complete:
            worst = max(noise, key=lambda r: float(r['input_noise_vrms']))
            # Exact source noise predicate, over the explicitly selected rows.
            value = float(worst['input_noise_vrms'])
            bandwidth = float(worst['closed_loop_3db_hz'])
            groups = [point_id(worst['point'])]
            passed = value <= 50e-6 and bandwidth > 10
            message = f'Selected worst noise {value:g} V RMS <=50 uV and its bandwidth {bandwidth:g} Hz >10 Hz'
        else:
            groups = sorted({c['score_group'] for c in expected})
            passed, message = False, 'Every selected noise measurement and bandwidth is required'
        for group in groups:
            apply_reduction(report, group, [{
                'name': 'selected_input_noise', 'passed': passed, 'message': message,
                'depends_on': [c['id'] for c in expected],
            }])
        if {c['id'] for c in expected} != {c['id'] for c in self.plan() if c['bench'] == 'noise'}:
            unassessed(report, 'full_pvt_worst_noise', 'The original full-PVT noise maximum is not covered; selected-noise limits are checked.')
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def original_suite_checks(self, rows, run_summary):
        rows = [{**r, 'point': tuple(r['point'])} for r in rows]
        by_bench = {bench: [r for r in rows if r['bench'] == bench]
                    for bench in ('op_ac', 'noise', 'psrr', 'cmrr', 'swing', 'settling', 'slew')}
        nominal = next((r for r in by_bench['op_ac'] if r['point'] == self.source.NOMINAL), {})
        policy = nominal.get('source_reference_device_policy_failures', ['source policy evidence missing']) if self.reference else []
        functional = (self.source.nominal_functional(nominal, policy)
                      if self.slug == Miller60.slug else self.source.nominal_functional(nominal))
        return check_rows([functional, *self.source.primary_checks(by_bench['op_ac']),
                           self.source.noise_check(by_bench['noise']),
                           *self.source.rejection_checks(by_bench['psrr'], by_bench['cmrr']),
                           *self.source.dynamic_checks(by_bench['swing'] + by_bench['settling'] + by_bench['slew'])])

    def informational(self, records):
        if not hasattr(self.source, 'efficiency_foms'):
            return None
        rows = [{**r['row'], 'point': tuple(r['row']['point'])} for r in records if not r.get('error') and r.get('row')]
        try:
            return self.source.efficiency_foms([r for r in rows if r['bench'] == 'op_ac'],
                                               [r for r in rows if r['bench'] == 'noise'])
        except Exception as exc:
            return {'error': str(exc), 'informational_only': True}


def miller_thresholds(gain, bandwidth, power, psrr1k, psrr1m, cmrr, settling, slew):
    # Exact literal tuples from primary_checks/rejection_checks/noise_check/
    # settling_check/dynamic_checks. Compound recrossing and global noise rules
    # remain explicit above rather than being reduced to guessed bounds.
    return {
        'op_ac': [('pvt_gain_bandwidth_gain', 'dc_gain_db', gain, True, 1, 'dB'),
                  ('pvt_gain_bandwidth_ugb', 'ugb_hz', bandwidth, True, 1e-6, 'MHz'),
                  ('pvt_phase_margin', 'phase_margin_deg', 60, True, 1, 'deg'),
                  ('pvt_output_bias', 'output_common_mode_error_v', 25e-3, False, 1e3, 'mV'),
                  ('pvt_power', 'power_w', power, False, 1e6, 'uW')],
        'noise': [('pvt_input_noise', 'input_noise_vrms', 50e-6, False, 1e6, 'uVrms')],
        'psrr': [('supply_rejection_1k', 'psrr_1khz_db', psrr1k, True, 1, 'dB'),
                 ('supply_rejection_1m', 'psrr_1mhz_db', psrr1m, True, 1, 'dB')],
        'cmrr': [('pvt_common_mode_rejection', 'cmrr_1khz_db', cmrr, True, 1, 'dB')],
        'swing': [('closed_loop_range', 'closed_loop_range_vpp', 0.8, True, 1, 'Vpp')],
        'settling': [('settling_time', 'settling_time_s', settling, False, 1e9, 'ns'),
                     ('settling_fraction', 'settling_error_fraction', 0.02, False, 100, '%'),
                     ('settling_static', 'settling_static_error_v', 2e-3, False, 1e3, 'mV')],
        'slew': [('slew_rise', 'slew_rise_v_per_us', slew, True, 1, 'V/us'),
                 ('slew_fall', 'slew_fall_v_per_us', slew, True, 1, 'V/us')],
    }


class Miller60(MillerBase):
    slug = 'two-stage-miller-opamp-gain60-ugb200-pm60-noise50uv-pvt'
    thresholds = miller_thresholds(60, 200e6, 2e-3, 35, 35, 55, 20e-9, 50)


class Miller70(MillerBase):
    slug = 'two-stage-miller-opamp-gain70-ugb20-pm60-noise50uv-pvt'
    thresholds = miller_thresholds(70, 20e6, 600e-6, 65, 20, 60, 30e-9, 10)
