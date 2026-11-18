"""Private source-specific suites. Only paths/declared conditions are substituted.

Scalar parsing, dynamic waveform fitting and all reusable predicates are the
frozen authors' functions. Ring-VCO per-point predicates are explicit literal
transcriptions because primary_checks hard-codes its complete matrix or TT.
"""
from __future__ import annotations

import math
from pathlib import Path

from .common import load_source, point_id
from .ota_suites import check_rows


class ScalarFixture:
    def __init__(self, source_path: Path | None = None, reference: bool = False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        self.parse_measures = self.source.run_spice.__globals__['parse_measures']

    def deck(self, case, design, model):
        text = (self.source.HERE / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        point = tuple(case['point'])
        replacements = self.source.substitutions(point) if hasattr(self.source, 'substitutions') else {}
        replacements[f'.lib "{self.source.DEFAULT_MODEL}" tt'] = f'.lib "{model}" {point[0]}'
        replacements[f'.include "{self.source.DEFAULT_DESIGN}"'] = f'.include "{design}"'
        for old, new in replacements.items():
            text = text.replace(old, str(new))
        if str(design) not in text or str(model) not in text:
            raise ValueError('Frozen fixture input path substitution did not resolve DUT/model')
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Frozen source fixture; explicit ngspice title\n' + text
        return text, False

    def analyze(self, case, work, run):
        values = self.parse_measures((work / 'ngspice.log').read_text(errors='replace'))
        return {'bench': case['bench'], 'point': tuple(case['point']), **values}

    def normalized(self, case, row):
        row = {**row, 'point': tuple(row['point'])}
        if row['point'] != tuple(case['point']) or row['bench'] != case['bench']:
            raise ValueError('Source measurements belong to a different condition/bench')
        if any(isinstance(v, float) and not math.isfinite(v) for v in row.values()):
            raise ValueError('Nonfinite scalar measurement')
        return row

    @staticmethod
    def cases(jobs):
        return [{'id': bench + '__' + point_id(point), 'score_group': point_id(point),
                 'bench': bench, 'point': point} for bench, point in jobs]


class Divider2(ScalarFixture):
    slug = 'transistor-divide-by-2'
    # The original two benches specify TT and no .temp; ngspice defaults to 27 C.
    nominal = ('tt', 1.8, 27)

    def plan(self):
        return self.cases([(bench, self.nominal) for bench in ('reset', 'divide')])

    def checks(self, case, row):
        row = self.normalized(case, row)
        checks = ([self.source.reset_check(row)] if case['bench'] == 'reset' else
                  [self.source.frequency_check(row), self.source.duty_and_level_check(row), self.source.delay_check(row)])
        return check_rows(checks)

    def original_suite_checks(self, rows, run_summary):
        by_bench = {r['bench']: r for r in rows}
        return check_rows([self.source.reset_check(by_bench.get('reset', {})),
                           self.source.frequency_check(by_bench.get('divide', {})),
                           self.source.duty_and_level_check(by_bench.get('divide', {})),
                           self.source.delay_check(by_bench.get('divide', {}))])


class GmrBase(ScalarFixture):
    def plan(self):
        return self.cases([(bench, p) for p in self.source.PVT_POINTS for bench in ('ac_power', 'sdr')])

    def analyze(self, case, work, run):
        row = super().analyze(case, work, run)
        row['name'] = self.source.point_name(case['point'])
        if case['bench'] == 'ac_power':
            return self.source.normalized_ac(row)
        if row.get('simulation_complete') != 1:
            raise ValueError('Source SDR simulation_complete marker missing or not one')
        # Original least-squares fundamental/noise fit on adaptive-time samples;
        # neither a substituted FFT nor just the printed scalar completion flag.
        gain, sdr = self.source.dynamic_metrics(work / 'dynamic.dat')
        if not math.isfinite(gain) or not math.isfinite(sdr):
            raise ValueError('Source dynamic waveform fit returned nonfinite metrics')
        row.update(fundamental_gain_vv=gain, dynamic_range_db=sdr)
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        return check_rows(self.source.ac_checks([row], 1) if case['bench'] == 'ac_power'
                          else [self.source.dynamic_check([row], 1)])

    def original_suite_checks(self, rows, run_summary):
        ac = [r for r in rows if r['bench'] == 'ac_power']
        dynamic = [r for r in rows if r['bench'] == 'sdr']
        return check_rows([*self.source.ac_checks(ac, len(self.source.PVT_POINTS)),
                           self.source.dynamic_check(dynamic, len(self.source.PVT_POINTS))])


class Gmr5(GmrBase):
    slug = 'gmr-degenerated-diff-amp-gain2-bw70m-power1p2mw-sdr60'


class Gmr15(GmrBase):
    slug = 'gmr-degen-amp-constant-gm-pvt'


class RingVco(ScalarFixture):
    slug = 'current-starved-ring-vco-pvt'

    def plan(self):
        return self.cases([('tune', p) for p in self.source.PVT]
                          + [('push', (c, 1.8, 27)) for c in self.source.CORNERS])

    def analyze(self, case, work, run):
        row = super().analyze(case, work, run)
        required = self.source.REQUIRED_TUNE_METRICS if case['bench'] == 'tune' else ('supply_pushing_pct_per_v',)
        missing = [metric for metric in required if metric not in row]
        row.update(name=self.source.point_name(case['point']), corner=case['point'][0],
                   outcome='non_converged' if missing else 'completed',
                   detail='missing/non-finite: ' + ', '.join(missing) if missing else 'ok')
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        if case['bench'] == 'push':
            ok = row.get('outcome') == 'completed' and 'supply_pushing_pct_per_v' in row
            return check_rows([('supply_pushing', ok and row['supply_pushing_pct_per_v'] <= 100,
                                'Source push_check: finite paired-supply pushing <=100 %/V at this corner.')])
        error = self.source.tuning_matrix_error([row], {tuple(case['point'])})
        if error:
            return check_rows(self.source.blocked(self.source.PRIMARY_NAMES, error))
        # Exact conjunctions in primary_checks, applied to this requested PVT.
        # The whole-matrix source function is called below as an independent
        # oracle; no source NOMINAL/PVT globals are replaced to trick it.
        predicates = [
            self.source.MIN_F_0P9_HZ <= row['f_0p9_hz'] <= 25e6 and row['f_1p2_hz'] >= 25e6,
            row['tuning_ratio'] >= 1.5,
            row['kvco_min_hz_per_v'] >= 30e6 and row['kvco_linearity_ratio'] <= 1.5,
            row['frequency_settling_drift'] <= .001,
            .45 <= row['duty_cycle'] <= .55,
            row['startup_time_s'] <= 100e-9,
            row['output_low_fraction'] <= .10 and row['output_high_fraction'] >= .90,
            row['power_w'] <= 200e-6,
        ]
        return check_rows([(name, ok, 'Exact source primary_checks predicate at ' + row['name'])
                           for name, ok in zip(self.source.PRIMARY_NAMES, predicates)])

    def original_suite_checks(self, rows, run_summary):
        normalized = [{**r, 'point': tuple(r['point'])} for r in rows]
        return check_rows([*self.source.primary_checks([r for r in normalized if r['bench'] == 'tune'], len(self.source.PVT)),
                           self.source.push_check([r for r in normalized if r['bench'] == 'push'])])
