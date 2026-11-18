"""Private fixed-matrix reference adapters using unchanged source scorers."""
import contextlib
import io
import json
import math
from pathlib import Path
import re
import tempfile

from .common import load_source, point_id
from .release_waveform import require_native_coverage


def predicates(items):
    return [{'name': name, 'passed': bool(ok), 'message': message}
            for name, ok, message in items]


def finite_fields(row, fields):
    return all(isinstance(row.get(key), (int, float)) and not isinstance(row[key], bool)
               and math.isfinite(row[key]) for key in fields)


def available_rows(records):
    return [record['row'] for record in records if record.get('row') is not None
            and not record.get('error') and record.get('run', {}).get('returncode') == 0]


def apply_reduction(report, group, checks):
    result = report['group_results'][group]
    result.setdefault('suite_checks', []).extend(checks)
    result['passed'] = bool(result['passed'] and checks and all(check['passed'] for check in checks))


def unassessed(report, name, reason):
    """Record a requirement outside the selected coverage, without a pass flag."""
    report.setdefault('unassessed_requirements', []).append(
        {'name': name, 'reason': reason})


class BetaMultiplier:
    slug = 'beta-multiplier-reference-pvt-mc'
    initialization = 'set num_threads=1\n'
    FIELDS = {
        'compliance': ('output_current_a', 'vref_v', 'power_w', 'compliance_current_mean_a',
                       'compliance_current_min_a', 'compliance_current_max_a', 'compliance_flatness'),
        'startup': ('startup_final_current_a', 'startup_final_vref_v', 'startup_settling_time_s',
                    'startup_current_overshoot_ratio', 'startup_peak_supply_current_a', 'startup_energy_j'),
        'mc': ('output_current_a', 'vref_v'),
    }
    LOCAL_CHECKS = {
        'compliance': ('pvt_output_current', 'pvt_vref', 'pvt_power', 'pvt_output_compliance'),
        'startup': ('pvt_multi_ramp_startup_final', 'pvt_multi_ramp_startup_settling',
                    'startup_overshoot', 'startup_inrush_and_energy'),
    }

    def __init__(self, source_path: Path | None = None, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        self.nominal = ('tt', 1.8, 27)

    def plan(self):
        cases = []
        for original in self.source.build_cases(self.source.SPEC):
            case = dict(original)
            point = (case['corner'], case['vdd'], case['temp_c'])
            ident = case['group'] + '__' + point_id(point)
            if case['group'] == 'mc':
                ident += '__seed' + str(case['seed'])
                group = point_id(self.nominal)
            else:
                group = point_id(point)
                if 'ramp_s' in case:
                    ident += '__ramp' + str(case['ramp_s'])
            cases.append({**case, 'id': ident, 'score_group': group,
                          'profile': 'tt' if point == self.nominal else 'pvt'})
        return cases

    def deck(self, case, design, model):
        source = self.source
        home = Path(source.__file__).parent
        text = (home / 'benches' / case['bench']).read_text()
        if case['group'] == 'mc':
            # Inline the unchanged wrapper body so a per-run writable model
            # copy is unnecessary. Only the model pathname is substituted.
            wrapper = (home / 'models/sky130_mc_mm.lib.spice').read_text()
            match = re.search(r'(?ims)^\.lib mc_mm\s*\n(.*?)^\.endl mc_mm\s*$', wrapper)
            if match is None:
                raise ValueError('Frozen process-and-mismatch wrapper changed')
            body = match[1].replace(source.CANONICAL_MODEL, str(model)).rstrip()
            old = f'.lib "{source.CANONICAL_MC_MODEL}" mc_mm'
            if old not in text:
                raise ValueError('Frozen MC fixture lacks its wrapper reference')
            text = text.replace(old, body, 1).replace(source.CANONICAL_DESIGN, str(design), 1)
            text, count = re.subn(r'(?m)^\.option seed=\d+', f'.option seed={case["seed"]}', text, count=1)
            if count != 1:
                raise ValueError('Frozen MC fixture lacks deterministic seed')
        else:
            ramp = case.get('ramp_s')
            stop = ramp + source.SPEC['operating']['startup_observation_after_ramp_s'] if ramp is not None else None
            text = source.instantiate(text, model, design, case['corner'], case['vdd'], case['temp_c'], ramp, stop)
        return text, True

    @staticmethod
    def identity(case):
        return {key: value for key, value in case.items() if key not in ('id', 'score_group', 'profile')}

    def analyze(self, case, work, run):
        require_native_coverage(work)
        source = self.source
        plot = source.parse_raw(work / 'analysis.raw')[0]
        if case['group'] == 'compliance':
            voltage = source.SPEC['operating']['output_voltage_v']
            sweep = [value.real for value in plot.vector('v(v-sweep)')]
            index = min(range(len(sweep)), key=lambda item: abs(sweep[item] - voltage))
            metrics = {**source.operating_metrics(plot, case['vdd'], voltage, index),
                       **source.compliance_metrics(plot, source.SPEC['limits']['compliance_low_v'],
                                                   source.SPEC['limits']['compliance_high_v'])}
        elif case['group'] == 'startup':
            ramp = case['ramp_s']
            metrics = source.startup_metrics(plot, ramp, ramp + source.SPEC['operating']['startup_observation_after_ramp_s'])
        elif case['group'] == 'mc':
            metrics = {'output_current_a': -plot.vector('i(vout)')[0].real,
                       'vref_v': plot.vector('v(vref)')[0].real}
        else:
            raise ValueError('Unknown frozen analysis group')
        return {**self.identity(case), **metrics, 'run_time_s': run['wall_seconds']}

    def source_checks(self, rows, run_summary=None):
        """Use the frozen CLI scorer directly, including statistics.stdev."""
        run = {'ngspice_runs': len(rows), 'failed_runs': [], **(run_summary or {})}
        with tempfile.TemporaryDirectory(prefix='beta-source-score-') as temporary:
            directory = Path(temporary)
            paths = {name: directory / (name + '.json')
                     for name in ('input', 'run-summary', 'summary', 'report', 'reward')}
            paths['input'].write_text(json.dumps(rows, allow_nan=False))
            paths['run-summary'].write_text(json.dumps(run, allow_nan=False))
            argv = [part for name, path in paths.items() for part in ('--' + name, str(path))]
            with contextlib.redirect_stdout(io.StringIO()):
                self.source.score_results(argv)
            report = json.loads(paths['report'].read_text())
        return [{'name': check['name'], 'passed': check['status'] == 'passed', 'message': check['message']}
                for check in report['results']['tests']]

    def checks(self, case, row):
        if any(row.get(key) != value for key, value in self.identity(case).items()):
            raise ValueError('Beta measurement identity differs from requested source case')
        if not finite_fields(row, (*self.FIELDS[case['group']], 'run_time_s')):
            return predicates([('required_source_measurements', False, 'Missing or nonfinite source metrics')])
        if case['group'] == 'mc':
            # Individual outliers are legal under the source 90% yield rule.
            return predicates([('complete_mc_sample', True, 'Finite sample; yield and sample sigma require all 50 fixed seeds')])
        names = set(self.LOCAL_CHECKS[case['group']])
        if case['group'] == 'compliance' and (case['corner'], case['vdd'], case['temp_c']) == self.nominal:
            names.add('nominal_current_accuracy')
        return [check for check in self.source_checks([row]) if check['name'] in names]

    def mc_checks(self, rows):
        expected = {case['seed'] for case in self.plan() if case['group'] == 'mc'}
        complete = (len(rows) == len(expected) and {row.get('seed') for row in rows} == expected
                    and all(finite_fields(row, self.FIELDS['mc']) for row in rows))
        if not complete:
            return predicates([(name, False, 'All 50 original seeds 31000..31049 must be present exactly once')
                               for name in ('mc_current_yield', 'mc_current_sigma')])
        return [check for check in self.source_checks(rows) if check['name'] in ('mc_current_yield', 'mc_current_sigma')]

    def reduce_suite(self, records, report):
        rows = [row for row in available_rows(records) if row['group'] == 'mc']
        checks = self.mc_checks(rows)
        report['suite_reductions'] = checks
        apply_reduction(report, point_id(self.nominal), checks)
        report['passed_group_count'] = sum(group['passed'] for group in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        expected = {case['id'] for case in self.plan() if case['group'] == 'mc'}
        selected = {case['id'] for case in plan if case['group'] == 'mc'}
        if selected == expected:
            return self.reduce_suite(records, report)
        unassessed(report, 'mc_current_yield_and_sigma',
                   f'Only {len(selected)}/{len(expected)} fixed Monte Carlo samples are selected; '
                   'a finite sample is not a yield or sigma measurement.')
        return report

    def original_suite_checks(self, rows, run_summary):
        expected = {json.dumps(self.identity(case), sort_keys=True) for case in self.plan()}
        keys = set()
        for row in rows:
            identity = {key: row[key] for key in ('group', 'bench', 'corner', 'vdd', 'temp_c')}
            for key in ('groups', 'ramp_s', 'seed'):
                if key in row:
                    identity[key] = row[key]
            keys.add(json.dumps(identity, sort_keys=True))
        coverage = len(rows) == len(expected) and keys == expected
        return self.source_checks(rows, run_summary) + predicates([
            ('fixed_source_case_coverage', coverage, f'{len(rows)}/{len(expected)} exact source case identities')])


class PllChargePump:
    slug = 'pll-charge-pump-pvt'
    initialization = 'set num_threads=1\n'

    def __init__(self, source_path: Path | None = None, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference

    def plan(self):
        source = self.source
        cases = [{'id': analysis + '__' + point_id(point), 'score_group': point_id(point),
                  'analysis': analysis, 'point': point, 'seed': None,
                  'profile': 'tt' if point == source.NOMINAL else 'pvt'}
                 for analysis, points in (('dc', source.PVT), ('pulse', source.PULSE_POINTS)) for point in points]
        cases += [{'id': 'mm__seed' + str(seed), 'score_group': point_id(source.NOMINAL),
                   'analysis': 'mm', 'point': source.NOMINAL, 'seed': seed, 'profile': 'pvt'}
                  for seed in source.MM_SEEDS]
        return cases

    def deck(self, case, design, model):
        source = self.source
        bench = 'pulse' if case['analysis'] == 'pulse' else 'dc'
        text = (source.HERE / 'benches' / f'tb_{bench}.spi').read_text()
        replacements = source.substitutions(tuple(case['point']))
        replacements[f'.lib "{source.DEFAULT_MODEL}" tt'] = (
            f'.option seed={case["seed"]}\n.lib "{model}" tt_mm' if case['analysis'] == 'mm'
            else f'.lib "{model}" {case["point"][0]}')
        replacements[f'.include "{source.DEFAULT_DESIGN}"'] = f'.include "{design}"'
        for old, new in replacements.items():
            if old not in text:
                raise ValueError(f'Frozen PLL fixture lacks {old!r}')
            text = text.replace(old, str(new))
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Frozen PLL charge-pump fixture\n' + text
        return text, False

    def analyze(self, case, work, run):
        parse = self.source.run_spice.__globals__['parse_measures']
        values = parse((work / 'ngspice.log').read_text(errors='replace'))
        return {'analysis': case['analysis'], 'point': tuple(case['point']), 'seed': case['seed'],
                'name': (f'tt_mm/1.80V/+27C/seed={case["seed"]}' if case['analysis'] == 'mm'
                         else self.source.point_name(case['point'])), **values}

    def checks(self, case, row):
        row = {**row, 'point': tuple(row['point'])}
        if (row['point'] != tuple(case['point']) or row.get('seed') != case['seed']
                or row.get('analysis') != case['analysis']):
            raise ValueError('PLL measurement identity differs from requested source case')
        if case['analysis'] == 'dc':
            return predicates(self.source.dc_checks([row], {tuple(case['point'])}))
        required = (self.source.PULSE_METRICS if case['analysis'] == 'pulse' else
                    tuple(f'{branch}_current_{voltage}_a' for branch in ('up', 'dn') for voltage in ('low', 'mid', 'high')))
        return predicates([('required_source_measurements', finite_fields(row, required),
                            'Source pulse/DC pairing or all 20 mismatch seeds are checked by suite reduction')])

    def reduce_suite(self, records, report):
        rows = [{**row, 'point': tuple(row['point'])} for row in available_rows(records)]
        checks = predicates(self.source.mm_checks([row for row in rows if row['analysis'] == 'mm']))
        apply_reduction(report, point_id(self.source.NOMINAL), checks)
        reductions = [{'score_group': point_id(self.source.NOMINAL), 'checks': checks}]
        for point in self.source.PULSE_POINTS:
            pulses = [row for row in rows if row['analysis'] == 'pulse' and row['point'] == point]
            dc = [row for row in rows if row['analysis'] == 'dc' and row['point'] == point]
            checks = predicates(self.source.pulse_checks(pulses, dc, {point}))
            apply_reduction(report, point_id(point), checks)
            reductions.append({'score_group': point_id(point), 'checks': checks})
        report['suite_reductions'] = reductions
        report['passed_group_count'] = sum(group['passed'] for group in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        rows = [{**row, 'point': tuple(row['point'])} for row in available_rows(records)]
        reductions = []
        for point in sorted({tuple(case['point']) for case in plan if case['analysis'] == 'pulse'}):
            pulses = [row for row in rows if row['analysis'] == 'pulse' and row['point'] == point]
            dc = [row for row in rows if row['analysis'] == 'dc' and row['point'] == point]
            checks = predicates(self.source.pulse_checks(pulses, dc, {point}))
            apply_reduction(report, point_id(point), checks)
            reductions.append({'score_group': point_id(point), 'checks': checks})
        selected_seeds = {case['seed'] for case in plan if case['analysis'] == 'mm'}
        if selected_seeds:
            samples = [row for row in rows if row['analysis'] == 'mm']
            fields = tuple(f'{branch}_current_{voltage}_a'
                           for branch in ('up', 'dn') for voltage in ('low', 'mid', 'high'))
            complete = (len(samples) == len(selected_seeds)
                        and {row.get('seed') for row in samples} == selected_seeds
                        and all(finite_fields(row, fields) for row in samples))
            nominal = self.source.NOMINAL_CURRENT_A
            checks = predicates([
                ('selected_mismatch_current_accuracy',
                 complete and all(.95 * nominal <= row[key] <= 1.05 * nominal
                                  for row in samples for key in fields),
                 'Original +/-5% branch-current bound for each selected mismatch sample'),
                ('selected_mismatch_branch_match',
                 complete and all(abs(row[f'up_current_{v}_a'] - row[f'dn_current_{v}_a']) / nominal <= .02
                                  for row in samples for v in ('low', 'mid', 'high')),
                 'Original 2% branch mismatch bound for each selected sample'),
            ])
            group = point_id(self.source.NOMINAL)
            apply_reduction(report, group, checks)
            reductions.append({'score_group': group, 'checks': checks})
        if selected_seeds != set(self.source.MM_SEEDS):
            unassessed(report, 'complete_mismatch_seed_coverage',
                       f'{len(selected_seeds)}/{len(self.source.MM_SEEDS)} original fixed seeds selected.')
        report['suite_reductions'] = reductions
        return report

    def original_suite_checks(self, rows, run_summary):
        rows = [{**row, 'point': tuple(row['point'])} for row in rows]
        dc = [row for row in rows if row['analysis'] == 'dc']
        mm = [row for row in rows if row['analysis'] == 'mm']
        pulses = [row for row in rows if row['analysis'] == 'pulse']
        expected = {(case['analysis'], tuple(case['point']), case['seed']) for case in self.plan()}
        actual = {(row['analysis'], row['point'], row['seed']) for row in rows}
        checks = (self.source.dc_checks(dc, set(self.source.PVT)) + self.source.mm_checks(mm)
                  + self.source.pulse_checks(pulses, [row for row in dc if row['point'] in self.source.PULSE_POINTS], set(self.source.PULSE_POINTS)))
        return predicates(checks + [('fixed_source_case_coverage', len(rows) == len(expected) and actual == expected,
                                     f'{len(rows)}/{len(expected)} exact source case identities')])
