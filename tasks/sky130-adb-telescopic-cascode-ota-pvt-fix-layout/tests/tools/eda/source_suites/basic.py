"""Telescopic amplifier measurement suite."""
from pathlib import Path
from .common import load_source, point_id
from .bounded_times import adapt_timing_sentinels, bounded_failure_checks


class Telescopic:
    slug = 'telescopic-cascode-ota-pvt-fix'

    def __init__(self, source_path: Path | None = None, reference: bool = False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference

    def plan(self):
        return [{**case, 'id': case['group'] + '__' + point_id(self.source.point_key(case)),
                 'score_group': point_id(self.source.point_key(case))}
                for case in self.source.build_cases()]

    def deck(self, case, design, model):
        text = (Path(self.source.__file__).parent / 'benches' / case['bench']).read_text()
        return self.source.instantiate(text, model, design, self.source.point_key(case)), True

    def analyze(self, case, work, run):
        # Preserve upstream raw parser and all interpolation/settling logic.
        plots = self.source.parse_raw(work / 'analysis.raw')
        group = case['group']
        if group == 'pvt':
            metrics = {**self.source.ac_metrics(self.source.plot(plots, 'AC Analysis')),
                       **self.source.op_metrics(self.source.plot(plots, 'Operating Point'), case['vdd'], 0.9)}
        elif group == 'swing':
            metrics = self.source.swing_metrics(self.source.plot(plots, 'DC transfer characteristic'), 0.9)
        elif group == 'settling':
            tran = self.source.plot(plots, 'Transient Analysis')
            metrics = self.source.settling_metrics(tran)
            metrics = adapt_timing_sentinels(self.source, case, tran, run, metrics)
        elif group == 'cm_recovery':
            tran = self.source.plot(plots, 'Transient Analysis')
            metrics = self.source.common_mode_recovery_metrics(tran)
            metrics = adapt_timing_sentinels(self.source, case, tran, run, metrics)
        else:
            raise ValueError('Unknown original analysis group')
        return {**{k: case[k] for k in ('group', 'bench', 'corner', 'vdd', 'temp_c')},
                **metrics, 'run_time_s': run['wall_seconds']}

    def checks(self, case, row):
        bounded = bounded_failure_checks(self.source, case, row)
        if bounded is not None:
            return bounded
        error = self.source.row_schema_error(row)
        if error is None:
            for key in ('group', 'bench', 'corner', 'vdd', 'temp_c'):
                if row[key] != case[key]:
                    error = f'Row {key} differs from requested case'
                    break
        if error:
            return [{'name': 'source_row_integrity', 'passed': False, 'message': error}]
        return [{'name': case['group'] + '_source_predicate',
                 'passed': bool(self.source.case_passes(row)),
                 'message': 'Original row_schema_error + case_passes; no rewritten numeric thresholds.'}]

    def original_suite_checks(self, rows, run_summary):
        checks, error = self.source.score(rows, run_summary)
        return [{'name': c.name, 'passed': bool(c.passed), 'message': c.message} for c in checks]
