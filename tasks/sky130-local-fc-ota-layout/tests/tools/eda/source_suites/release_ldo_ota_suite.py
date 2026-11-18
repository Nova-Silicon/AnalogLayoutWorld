"""Original LDO OTA5 full DC/network/stability/transient/mismatch matrix."""
import contextlib
import csv
import io
import json
from pathlib import Path
import tempfile
from .common import point_id
from .release_waveform import require_native_coverage
from .release_reference_suites import BetaMultiplier, predicates, finite_fields, available_rows, apply_reduction, unassessed


class LdoOta(BetaMultiplier):
    slug = 'ldo-ota5-robust-pvt-mc'

    def analysis_dependencies(self, case):
        # Row measurement reads only this case's raw waveform and fixed SPEC.
        # Cross-case checks stay in the existing reducer, in source plan order.
        return []

    def plan(self):
        rows = []
        for index, job in enumerate(self.source.jobs(self.source.SPEC, False)):
            p = (job['corner'], job['vin'], job['temp'])
            rows.append({**job, 'id': f'{index:03d}__{job["group"]}__{point_id(p)}',
                         'score_group': point_id(self.nominal if job['group'] == 'mc' else p),
                         'profile': 'tt' if p == self.nominal else 'pvt'})
        return rows

    def deck(self, case, design, model):
        s = self.source
        text = (Path(s.__file__).parent / 'benches' / ('tb_' + case['bench'] + '.spi')).read_text()
        text = s.instantiate(text, model=model, design=design,
                             **{k: case[k] for k in ('corner', 'temp', 'vin', 'load', 'cap', 'esr')})
        if 'seed' in case:
            text = s.enable_mc_mismatch(text, case['seed'])
        return text, True

    def analyze(self, case, work, run):
        # The frozen DC .control block explicitly appends three sweeps to
        # result.raw; ngspice's -r filename does not override `write` commands.
        raw_path = work / ('result.raw' if case['group'] == 'pvt_dc' else 'analysis.raw')
        require_native_coverage(work, raw_path=raw_path)
        s = self.source; plots = s.parse_ascii_raw(raw_path)
        target = s.SPEC['device']['target_output_v']
        values = s.analyze_pvt_dc(plots, target) if case['group'] == 'pvt_dc' else s.analyze(case['group'], plots, target, s.SPEC['limits']['transient_settling_error_v_max'])
        return {**self.identity(case), **values, 'returncode': 0, 'elapsed_s': run['wall_seconds']}

    def checks(self, case, row):
        g = case['group']; limits = self.source.SPEC['limits']
        if g == 'mc':
            return predicates([('finite_mc_output', finite_fields(row, ['vout_v']), 'Yield checked over the original complete seed set')])
        if g == 'pvt_dc':
            bounds = {'output_error_max_v': (None, 'dc_output_error_v_max'),
                      'quiescent_current_min_a': ('quiescent_current_a_min', None),
                      'quiescent_current_max_a': (None, 'quiescent_current_a_max')}
        elif g.startswith('dropout'):
            bounds = {'dropout_v': (None, 'dropout_v_max_at_30ma')}
        elif g.startswith('loop'):
            bounds = {'dc_loop_gain_db': ('loop_dc_gain_db_min', None), 'phase_margin_deg': ('phase_margin_deg_min', None),
                      'loop_ugb_hz': ('loop_ugb_hz_min', None)}
        elif g.startswith('psrr'):
            bounds = {f'psrr_{f}_db': (f'psrr_{f}_db_min', None) for f in ('100hz', '1khz', '100khz', '1mhz')}
        elif g == 'noise':
            bounds = {'output_noise_rms_v': (None, 'output_noise_rms_v_max')}
        elif g.startswith('startup'):
            bounds = {k: (None, k + '_max') for k in ('startup_t90_s', 'startup_settling_after_ramp_s', 'startup_overshoot_v')}
        else:
            prefix = 'load' if g.startswith('load') else 'line'
            bounds = {'excursion_v': (None, prefix + '_transient_excursion_v_max'), 'settling_time_s': (None, 'transient_settling_time_s_max')}
        if not finite_fields(row, bounds):
            return predicates([('required_measurements', False, 'Missing/nonfinite source measurement')])
        checks = [(k, (lo is None or row[k] >= limits[lo]) and (hi is None or row[k] <= limits[hi]), str(row[k])) for k, (lo, hi) in bounds.items()]
        if g == 'pvt_dc':
            checks.append(('all_nine_dc_points', row.get('pvt_points') == 9, str(row.get('pvt_points'))))
        return predicates(checks)

    def mc_checks(self, rows):
        mc = self.source.SPEC['monte_carlo']; seeds = {c['seed'] for c in self.plan() if c['group'] == 'mc'}
        complete = len(rows) == len(seeds) and {r['seed'] for r in rows} == seeds and all(finite_fields(r, ['vout_v']) for r in rows)
        fraction = sum(mc['output_voltage_v_min'] <= r['vout_v'] <= mc['output_voltage_v_max'] for r in rows) / len(rows) if complete else 0
        return predicates([('monte_carlo_output', complete and fraction >= mc['yield_min'], f'{len(rows)}/{len(seeds)} samples, yield={fraction}')])

    def reduce_suite(self, records, report):
        apply_reduction(report, point_id(self.nominal), self.mc_checks([r for r in available_rows(records) if r['group'] == 'mc']))
        return report

    def reduce_selected(self, records, report, plan):
        selected = {case['seed'] for case in plan if case['group'] == 'mc'}
        expected = {case['seed'] for case in self.plan() if case['group'] == 'mc'}
        if selected == expected:
            return self.reduce_suite(records, report)
        unassessed(report, 'monte_carlo_output_yield',
                   f'{len(selected)}/{len(expected)} fixed samples selected; '
                   'finite individual samples do not establish the specified yield.')
        return report

    def original_suite_checks(self, rows, run_summary):
        with tempfile.TemporaryDirectory(prefix='ldo-source-score-') as temporary:
            d = Path(temporary)
            paths = {n: d / (n + '.json') for n in ('input', 'run-summary', 'summary', 'report', 'reward')}
            fields = sorted({k for row in rows for k in row})
            with paths['input'].open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows(rows)
            paths['run-summary'].write_text(json.dumps({**run_summary, 'failed_runs': len(run_summary['failed_runs'])}))
            argv = [x for n, p in paths.items() for x in ('--' + n, str(p))]
            with contextlib.redirect_stdout(io.StringIO()):
                self.source.score_results(argv)
            report = json.loads(paths['report'].read_text())
        return [{'name': c['name'], 'passed': c['status'] == 'passed', 'message': c['message']} for c in report['results']['tests']]
