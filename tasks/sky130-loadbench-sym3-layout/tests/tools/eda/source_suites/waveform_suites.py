"""Waveform measurements for the low-power line driver."""
import math

from .additional_suites import ScalarFixture
from .ota_suites import check_rows
from .common import point_id
from .release_reference_suites import apply_reduction


class LowPowerLineDriver(ScalarFixture):
    slug = 'low-power-line-driver-pvt'

    def plan(self):
        return self.cases([(bench, p) for p in self.source.PVT for bench in ('loopgain', 'swing', 'thd')])

    def analyze(self, case, work, run):
        row = super().analyze(case, work, run)
        s = self.source
        row['name'] = s.point_name(case['point'])
        if case['bench'] == 'loopgain' and tuple(case['point']) == s.NOMINAL and self.reference:
            listing = work / 'netlist_expanded.txt'
            row['source_reference_device_policy_failures'] = (s.device_policy_failures(listing.read_text())
                                                              if listing.exists() else ['expanded reference listing missing'])
        if case['bench'] == 'thd':
            times, samples = [], []
            for line in (work / 'thd_wave.dat').read_text().splitlines():
                fields = line.split()
                if len(fields) >= 2:
                    times.append(float(fields[0]))
                    samples.append(float(fields[1]))
            if len(times) <= 16 or times[-1] < (s.THD_STARTUP_CYCLES + s.THD_MEASURE_CYCLES) / s.F0_HZ:
                raise ValueError('Original distortion sampling window is incomplete')
            # Original interpolation to 2048 uniform samples, four cycles,
            # harmonics 2..9, after four startup cycles. No adaptive-time FFT.
            metrics = s.harmonic_fit(times, samples)
            if not all(math.isfinite(value) for value in metrics.values()):
                raise ValueError('Nonfinite original harmonic-fit result')
            row.update(metrics)
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        s = self.source
        if case['bench'] == 'loopgain':
            result = check_rows(s.loop_checks([row], 1).values())
            if self.reference and tuple(case['point']) == s.NOMINAL:
                problems = row.get('source_reference_device_policy_failures', ['source policy evidence missing'])
                result += check_rows([('reference_device_policy', not problems, '; '.join(problems) or 'Original reference-only device policy passed')])
            return result
        if case['bench'] == 'swing':
            return check_rows(s.swing_check([row], 1).values())
        return check_rows([*s.distortion_check([row], 1).values(),
                           ('drive_peak_evidence', 'peak_supply_current_a' in row, 'Peak-current measurement required for paired drive check')])

    def reduce_suite(self, records, report):
        source_rows = {}
        for r in records:
            if r.get('error') or not r.get('row') or r['run']['returncode'] != 0:
                continue
            row = {**r['row'], 'point': tuple(r['row']['point'])}
            source_rows[(row['bench'], row['point'])] = row
        reductions = []
        for point in self.source.PVT:
            loop = source_rows.get(('loopgain', tuple(point)))
            thd = source_rows.get(('thd', tuple(point)))
            if loop is None or thd is None or 'power_w' not in loop:
                checks = check_rows([('line_drive', False, 'Both loop quiescent power and THD peak-current evidence required')])
            else:
                checks = check_rows(self.source.drive_check([thd], [loop], 1).values())
            group = point_id(point)
            for check in checks:
                check.update(failure_attribution=group, depends_on=['loopgain__' + group, 'thd__' + group])
            reductions.extend(checks)
            if not all(c['passed'] for c in checks):
                report['group_results'][group]['passed'] = False
                report['group_results'][group]['suite_failure'] = checks[0]['message']
        report['suite_reductions'] = reductions
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        points = sorted({tuple(c['point']) for c in plan})
        rows = {(r['case']['bench'], tuple(r['case']['point'])):
                {**r['row'], 'point': tuple(r['case']['point'])}
                for r in records if not r.get('error') and r.get('row')
                and r['run']['returncode'] == 0}
        for point in points:
            selected = {c['bench'] for c in plan if tuple(c['point']) == point}
            if not {'loopgain', 'thd'} <= selected:
                raise ValueError('Selected line-driver point requires both loopgain and THD fixtures')
            loop, thd = rows.get(('loopgain', point)), rows.get(('thd', point))
            if (loop is None or thd is None or
                    not math.isfinite(float(loop.get('power_w', math.nan)))):
                checks = check_rows([('line_drive', False, 'Both finite quiescent power and THD peak-current evidence are required at the selected point')])
            else:
                checks = check_rows(self.source.drive_check([thd], [loop], 1).values())
            group = point_id(point)
            for check in checks:
                check['depends_on'] = ['loopgain__' + group, 'thd__' + group]
            apply_reduction(report, group, checks)
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def original_suite_checks(self, rows, run_summary):
        rows = [{**r, 'point': tuple(r['point'])} for r in rows]
        by = {b: [r for r in rows if r['bench'] == b] for b in ('loopgain', 'swing', 'thd')}
        s = self.source
        named = {**s.loop_checks(by['loopgain'], len(s.PVT)),
                 **s.swing_check(by['swing'], len(s.PVT)),
                 **s.distortion_check(by['thd'], len(s.PVT))}
        if s.complete(by['loopgain'], ('power_w',), len(s.PVT)):
            named.update(s.drive_check(by['thd'], by['loopgain'], len(s.PVT)))
        else:
            named.update(s.blocked(('line_drive',), 'complete quiescent power matrix required'))
        checks = check_rows([named[name] for name in s.ORDER])
        if self.reference:
            nominal = next((r for r in by['loopgain'] if r['point'] == s.NOMINAL), {})
            failures = nominal.get('source_reference_device_policy_failures', ['reference policy evidence missing'])
            checks += check_rows([('reference_device_policy', not failures, '; '.join(failures) or 'Original reference policy passed')])
        return checks
