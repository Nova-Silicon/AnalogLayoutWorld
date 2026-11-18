"""Constant-gm source suite, including its whole-matrix gain-spread contract.

The original module has no pure whole-suite checker: it calculates the global
checks inline in main(). Those exact expressions are explicitly recorded here;
per-point OP/AC and startup use the author's pure failure predicates unchanged.
"""
from __future__ import annotations

import math
from pathlib import Path

from .additional_suites import ScalarFixture
from .ota_suites import check_rows
from .release_reference_suites import unassessed


class ConstantGm(ScalarFixture):
    slug = 'constant-gm-stable-gain-amplifier-pvt'
    pvt_names = ('gain_1mhz_vv', 'gain_1ghz_vv', 'load_drop_v', 'output_imbalance_v', 'power_w')
    startup_names = ('startup_zero_imbalance_v', 'startup_step_gain_vv',
                     'startup_zero_load_drop_v', 'startup_step_load_drop_v')
    linearity_names = ('gain_center_vv', 'gain_m60_vv', 'gain_m30_vv', 'gain_p30_vv', 'gain_p60_vv')

    def points(self):
        s = self.source
        return [(c, v, t) for c in s.CORNERS for v in s.SUPPLIES for t in s.TEMPERATURES]

    def plan(self):
        return self.cases([(bench, point) for point in self.points() for bench in ('pvt', 'startup', 'lin')])

    def deck(self, case, design, model):
        text = (Path(self.source.__file__).parent / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        replacements = self.source.replacements(*case['point'])
        replacements.update({'__MODEL__': str(model), '.include "/app/circuit.spi"': f'.include "{design}"'})
        for old, new in replacements.items():
            text = text.replace(old, str(new))
        if str(model) not in text or str(design) not in text:
            raise ValueError('Original fixture model/DUT paths not resolved')
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Constant-gm original fixture; explicit ngspice title\n' + text
        return text, False

    def analyze(self, case, work, run):
        row = super().analyze(case, work, run)
        if case['bench'] == 'pvt':
            if not self.source.finite(row, self.pvt_names):
                raise ValueError('Original run_pvt required measurements incomplete')
            if 'bandwidth_hz' not in row:
                if row['gain_1ghz_vv'] >= row['gain_1mhz_vv'] / math.sqrt(2):
                    row['bandwidth_hz'] = 1e9
                else:
                    raise ValueError('Missing bandwidth without original 1 GHz endpoint proof')
            if not self.source.finite(row, ('bandwidth_hz',)):
                raise ValueError('Nonfinite bandwidth')
        elif case['bench'] == 'startup':
            if not self.source.finite(row, self.startup_names):
                raise ValueError('Original run_startup required measurements incomplete')
        else:
            if not self.source.finite(row, self.linearity_names) or abs(row['gain_center_vv']) < 1e-12:
                raise ValueError('Original run_linearity required measurements incomplete or center gain zero')
            row['linearity_error'] = max(abs(row[name] / row['gain_center_vv'] - 1) for name in self.linearity_names[1:])
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        if case['bench'] == 'pvt':
            if not self.source.finite(row, (*self.pvt_names, 'bandwidth_hz')):
                return check_rows([('complete_signoff', False, 'Missing required original OP/AC measurements')])
            failure = self.source.pvt_failure(row)
            return check_rows([('op_ac', failure is None, str(failure) if failure else 'Original pvt_failure passed')])
        if case['bench'] == 'startup':
            if not self.source.finite(row, self.startup_names):
                return check_rows([('startup_power_on', False, 'Missing required original startup measurements')])
            failure = self.source.startup_failure(row)
            return check_rows([('startup_power_on', failure is None, failure or 'Original startup_failure passed')])
        complete = self.source.finite(row, (*self.linearity_names, 'linearity_error')) and abs(row['gain_center_vv']) >= 1e-12
        return check_rows([('linearity', complete and row['linearity_error'] <= self.source.LINEARITY_ERROR_MAX,
                            'Original main(): complete linearity at this PVT and relative error <=0.08')])

    def gain_spread_check(self, rows):
        pvt = [r for r in rows if r.get('bench') == 'pvt']
        complete = (len(pvt) == len(self.points()) and {tuple(r['point']) for r in pvt} == set(self.points())
                    and all(self.source.finite(r, (*self.pvt_names, 'bandwidth_hz')) for r in pvt))
        if not complete:
            return {'name': 'gain_spread', 'passed': False, 'message': 'Complete PVT gain matrix required',
                    'failure_attribution': 'all PVT groups', 'extrema': None}
        low = min(pvt, key=lambda r: r['gain_1mhz_vv'])
        high = max(pvt, key=lambda r: r['gain_1mhz_vv'])
        spread = high['gain_1mhz_vv'] / max(low['gain_1mhz_vv'], 1e-12)
        return {'name': 'gain_spread', 'passed': spread <= self.source.GAIN_SPREAD_MAX,
                'message': f'Original full-matrix gain_hi/max(gain_lo,1e-12)={spread:.12g} <=1.15',
                'failure_attribution': 'all PVT groups',
                'extrema': {'minimum': low, 'maximum': high}, 'gain_spread': spread}

    def reduce_suite(self, records, report):
        rows = [r['row'] for r in records if not r.get('error') and r.get('row') and r['run']['returncode'] == 0]
        spread = self.gain_spread_check(rows)
        report['suite_reductions'] = [spread]
        # This spec is a relation across PVT, not a property of one selected
        # extreme corner. Every PVT acceptance requires the declared relation.
        if not spread['passed']:
            for group in report['group_results'].values():
                group['passed'] = False
                group['suite_failure'] = spread['message']
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def reduce_selected(self, records, report, plan):
        expected_pvt = {c['id'] for c in self.plan() if c['bench'] == 'pvt'}
        selected_pvt = {c['id'] for c in plan if c['bench'] == 'pvt'}
        if selected_pvt == expected_pvt:
            return self.reduce_suite(records, report)
        unassessed(report, 'gain_spread',
                   'Original full-PVT maximum/minimum gain ratio is not assessed by the selected fixtures. Individual gain, bandwidth, power, startup and linearity checks remain active.')
        return report

    def original_suite_checks(self, rows, run_summary):
        # Literal source main() reduction, not an invented generic MIN/MAX map.
        # Its complete-signoff gate is explicit for all three bench families.
        s = self.source
        by = {bench: [r for r in rows if r.get('bench') == bench] for bench in ('pvt', 'startup', 'lin')}
        complete = all(len(rs) == len(self.points()) and {tuple(r['point']) for r in rs} == set(self.points())
                       for rs in by.values())
        for bench, rs in by.items():
            for row in rs:
                complete = complete and all(c['passed'] or c['name'] != 'complete_signoff'
                                            for c in self.checks({'bench': bench, 'point': row['point']}, row))
        if not complete:
            return check_rows([(name, False, 'Original complete matrix required') for name in s.CHECK_NAMES])
        pvt, startup, lin = by['pvt'], by['startup'], by['lin']
        gains = [r['gain_1mhz_vv'] for r in pvt]
        drops = [r['load_drop_v'] for r in pvt]
        powers = [r['power_w'] for r in pvt]
        checks = [
            ('complete_signoff', True, 'All three complete 27-point matrices'),
            ('absolute_gain_window', s.GAIN_MIN <= min(gains) and max(gains) <= s.GAIN_MAX, 'Original main() gain extrema'),
            ('bandwidth', min(r['bandwidth_hz'] for r in pvt) >= s.BANDWIDTH_MIN_HZ, 'Original main() BW minimum'),
            ('load_drop_window', s.LOAD_DROP_MIN_V <= min(drops) and max(drops) <= s.LOAD_DROP_MAX_V, 'Original main() load drop extrema'),
            ('deterministic_output_imbalance', max(r['output_imbalance_v'] for r in pvt) <= s.OUTPUT_IMBALANCE_MAX_V, 'Original main() imbalance maximum'),
            ('linearity', all(s.finite(r, (*self.linearity_names, 'linearity_error')) for r in lin)
             and max(r['linearity_error'] for r in lin) <= s.LINEARITY_ERROR_MAX, 'Original main() complete linearity maximum'),
            ('pvt_power', all(p >= 0 for p in powers) and max(powers) <= s.POWER_MAX_W, 'Original main() power range'),
            ('gain_spread', max(gains) / max(min(gains), 1e-12) <= s.GAIN_SPREAD_MAX, 'Original main() full-matrix gain ratio'),
            ('startup_power_on', all(s.finite(r, self.startup_names) and s.startup_failure(r) is None for r in startup), 'Original startup_failure at every PVT'),
        ]
        return check_rows(checks)
