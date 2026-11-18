"""Private adapter for the frozen complementary class-AB op-amp signoff.

Native source benches, track interpretation, Fourier parser, constants, and
whole-suite predicates are retained. Point-local checks factor the source
conjunctions; the cross-PVT UGB ratio remains an explicit global gate.
"""
import math

from .additional_suites import ScalarFixture
from .ota_suites import check_rows
from .common import point_id
from .release_reference_suites import unassessed


class Complementary(ScalarFixture):
    slug = 'complementary-folded-cascode-ab-opamp-pvt'

    def plan(self):
        s = self.source
        jobs = [('ac', p, cm, None) for p in s.PVT for cm in s.CM_INDICES]
        jobs += [(bench, p, s.AC_CM_INDEX if bench == 'noise' else None, None)
                 for bench in ('track', 'step', 'noise') for p in s.PVT]
        jobs += [(bench, p, None, None) for bench in ('cmrr', 'psrr', 'thd')
                 for p in s.REPRESENTATIVE_POINTS]
        jobs += [('offset', s.NOMINAL, s.AC_CM_INDEX, seed) for seed in s.OFFSET_SEEDS]
        cases = []
        for bench, point, cm, seed in jobs:
            ident = bench + '__' + point_id(point)
            if cm is not None:
                ident += '__cm' + str(cm)
            if seed is not None:
                ident += '__seed' + str(seed)
            cases.append({'id': ident, 'score_group': point_id(point),
                          'bench': bench, 'point': point, 'cm_index': cm, 'seed': seed})
        if len(cases) != s.EXPECTED_PROCESSES:
            raise ValueError('Declared source process count differs from fixed plan')
        return cases

    def deck(self, case, design, model):
        s = self.source
        point = tuple(case['point'])
        cm = s.common_modes(point)[case['cm_index']] if case['cm_index'] is not None else None
        text = (s.HERE / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        replacements = s.substitutions(point, cm)
        replacements[f'.lib "{s.DEFAULT_MODEL}" tt'] = f'.lib "{model}" {point[0]}'
        replacements[f'.include "{s.DEFAULT_DESIGN}"'] = f'.include "{design}"'
        if case['bench'] == 'offset':
            # The TT mismatch section is part of the unchanged native model.
            text = text.replace(f'.lib "{s.DEFAULT_MODEL}" tt_mm', f'.lib "{model}" tt_mm')
            replacements['.option seed=31000'] = f'.option seed={case["seed"]}'
        for old, new in replacements.items():
            text = text.replace(old, str(new))
        if str(design) not in text or str(model) not in text:
            raise ValueError('Source DUT/model paths were not resolved')
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Frozen complementary op-amp fixture; explicit ngspice title\n' + text
        return text, False

    def analyze(self, case, work, run):
        row = super().analyze(case, work, run)
        s = self.source
        row['name'] = s.point_name(case['point'])
        if case['cm_index'] is not None:
            row.update(cm_index=case['cm_index'], cm_v=s.common_modes(case['point'])[case['cm_index']])
        if case['seed'] is not None:
            row['seed'] = case['seed']
        if case['bench'] == 'track':
            row = s.analyze_track(row)
        if case['bench'] == 'thd':
            for line in (work / 'ngspice.log').read_text(errors='replace').splitlines():
                match = s.FOURIER_THD.search(line)
                if match and math.isfinite(float(match.group(1))):
                    row['fourier_thd_percent'] = float(match.group(1))
            if all(field in row for field in ('thd_residual_v', 'thd_command_v')) and float(row['thd_command_v']) > 0:
                row['thd_residual_fraction'] = float(row['thd_residual_v']) / float(row['thd_command_v'])
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        s = self.source
        if case['cm_index'] is not None and (row.get('cm_index') != case['cm_index'] or
                row.get('cm_v') != s.common_modes(case['point'])[case['cm_index']]):
            raise ValueError('Wrong input common-mode measurement identity')
        if case['seed'] is not None and row.get('seed') != case['seed']:
            raise ValueError('Wrong source mismatch seed identity')
        bench = case['bench']
        fields = {'ac': s.AC_FIELDS, 'track': s.TRACK_FIELDS, 'step': s.STEP_FIELDS,
                  'noise': ('input_noise_vrms',), 'cmrr': ('cmrr_1khz_db', 'cmrr_1mhz_db'),
                  'psrr': ('psrr_10hz_db', 'psrr_1mhz_db'),
                  'thd': ('thd_residual_fraction', 'fourier_thd_percent'), 'offset': ('offset_v',)}[bench]
        if not s.finite_fields(row, fields):
            return check_rows([('required_source_measurements', False, 'Required finite source measurements missing')])
        if bench == 'ac':
            near = case['cm_index'] in (0, 4)
            predicates = [
                ('gain_10hz', row['gain_10hz_db'] >= (s.GAIN_10HZ_NEAR_RAIL_MIN_DB if near else s.GAIN_10HZ_MIN_DB)),
                ('ugb', row['ugbw_hz'] >= s.UGB_MIN_HZ),
                ('phase_margin', row['phase_margin_deg'] >= (s.PHASE_MARGIN_NEAR_RAIL_MIN_DEG if near else s.PHASE_MARGIN_MIN_DEG)),
                ('static_power', 0 <= row['static_power_w'] <= s.STATIC_POWER_MAX_W)]
        elif bench == 'track':
            ok, message = s.nominal_track_gate(row)
            return check_rows([('source_track_gate', ok, message)])
        elif bench == 'step':
            ok, message = s.nominal_step_gate(row)
            return check_rows([('source_step_gate', ok, message)])
        elif bench == 'noise':
            predicates = [('input_noise', row['input_noise_vrms'] <= s.INPUT_NOISE_MAX_VRMS)]
        elif bench == 'cmrr':
            predicates = [('cmrr_1khz', row['cmrr_1khz_db'] >= s.CMRR_1KHZ_MIN_DB),
                          ('cmrr_1mhz', row['cmrr_1mhz_db'] >= s.CMRR_1MHZ_MIN_DB)]
        elif bench == 'psrr':
            predicates = [('psrr_10hz', row['psrr_10hz_db'] >= s.PSRR_10HZ_MIN_DB),
                          ('psrr_1mhz', row['psrr_1mhz_db'] >= s.PSRR_1MHZ_MIN_DB)]
        elif bench == 'thd':
            predicates = [('thd_residual', row['thd_residual_fraction'] <= s.THD_RESIDUAL_MAX),
                          ('fourier_thd', row['fourier_thd_percent'] <= s.THD_MAX_PERCENT)]
        else:
            predicates = [('offset', abs(row['offset_v']) <= s.OFFSET_MAX_V)]
        return check_rows([(name, bool(ok), 'Exact source predicate at ' + row['name']) for name, ok in predicates])

    def reduce_suite(self, records, report):
        # max/min bandwidth spans ALL 125 AC/VCM points. It cannot be counted
        # as a separate corner or silently omitted from per-PVT completion.
        rows = [dict(r['row'], point=tuple(r['row']['point'])) for r in records
                if r.get('row') and not r.get('error') and r['run']['returncode'] == 0 and r['row']['bench'] == 'ac']
        if self.source.complete_ac(rows):
            original = self.source.ac_checks(rows)['pvt_ugbw_pvt_flatness']
            check = check_rows([original])[0]
        else:
            check = {'name': 'pvt_ugbw_pvt_flatness', 'passed': False,
                     'message': 'Complete original 125-row AC/VCM matrix required for max/min UGB'}
        check['failure_attribution'] = 'all PVT groups; cross-condition requirement'
        report['suite_reductions'] = [check]
        if not check['passed']:
            for group in report['group_results'].values():
                group['passed'] = False
                group['suite_failure'] = check['message']
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        expected_ac = {c['id'] for c in self.plan() if c['bench'] == 'ac'}
        selected_ac = {c['id'] for c in plan if c['bench'] == 'ac'}
        if selected_ac == expected_ac:
            report = self.reduce_suite(records, report)
        else:
            unassessed(report, 'pvt_ugbw_pvt_flatness',
                       'Original full 125-point AC/common-mode spread is not assessed by the selected fixtures. Individual measured gain, bandwidth and phase-margin limits remain checked.')
        selected_seeds = {c['seed'] for c in plan if c['bench'] == 'offset'}
        if selected_seeds != set(self.source.OFFSET_SEEDS):
            unassessed(report, 'complete_offset_seed_regression',
                       'Only selected fixed-seed offsets are checked. The original complete seed regression and statistical yield are not established.')
        return report

    def original_suite_checks(self, rows, run_summary):
        s = self.source
        rows = [{**r, 'point': tuple(r['point'])} for r in rows]
        by = {b: [r for r in rows if r['bench'] == b]
              for b in ('ac', 'track', 'step', 'noise', 'cmrr', 'psrr', 'thd', 'offset')}
        named = {**s.ac_checks(by['ac']), **s.track_checks(by['track'], by['ac']),
                 **s.step_checks(by['step']),
                 **s.auxiliary_checks(by['noise'], by['cmrr'] + by['psrr'] + by['thd'], by['offset'])}
        identities = {(r['bench'], r['point'], r.get('cm_index'), r.get('seed')) for r in rows}
        expected = {(c['bench'], tuple(c['point']), c['cm_index'], c['seed']) for c in self.plan()}
        complete = (len(rows) == s.EXPECTED_PROCESSES and identities == expected and
                    s.complete_ac(by['ac']) and s.complete_point_rows(by['track'], s.TRACK_FIELDS) and
                    s.complete_point_rows(by['step'], s.STEP_FIELDS) and
                    s.complete_point_rows(by['noise'], ('input_noise_vrms',)))
        named['complete_signoff'] = ('complete_signoff', complete and all(c[1] for c in named.values()),
                                     f'{len(rows)}/{s.EXPECTED_PROCESSES} source analyses; exact measurement identities required')
        return check_rows([named[name] for name in s.CHECK_NAMES])
