"""Scalar measurements for the low-power oscillator and unregulated charge pump."""
from pathlib import Path
import math

from .common import load_source, point_id
from .release_reference_suites import predicates, available_rows, apply_reduction


class SourceScalar:
    def __init__(self, source_path: Path, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        self.parse = self.source.run_spice.__globals__['parse_measures']

    def render(self, filename, replacements, design, model):
        text = (self.source.HERE / 'benches' / filename).read_text()
        for old, new in replacements.items():
            # Some original substitution maps cover several fixture kinds.
            # Match the authors' str.replace semantics for irrelevant keys.
            text = text.replace(old, str(new))
        text = text.replace('/app/circuit.spi', str(design))
        text = text.replace(self.source.MODEL, str(model))
        if str(design) not in text or str(model) not in text:
            raise ValueError('DUT/model substitution incomplete')
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Frozen source electrical fixture\n' + text
        return text, False

    def analyze(self, case, work, run):
        return {'point': tuple(case['point']), 'analysis': case['analysis'],
                'values': self.parse((work / 'ngspice.log').read_text(errors='replace'))}

    @staticmethod
    def require(case, row, names):
        valid = (tuple(row['point']) == tuple(case['point']) and row['analysis'] == case['analysis']
                 and all(name in row['values'] and math.isfinite(float(row['values'][name])) for name in names))
        return predicates([('required_measurements', valid, 'Exact case identity and every finite source measurement')])


class LowPowerOscillator(SourceScalar):
    slug = 'low-power-oscillator-2mhz-pvt'

    def plan(self):
        return [{'id': point_id(p), 'score_group': point_id(p), 'point': p,
                 'analysis': 'osc', 'profile': 'tt' if p == self.source.NOMINAL else 'pvt'}
                for p in self.source.POINTS]

    def deck(self, case, design, model):
        corner, supply, temperature = case['point']
        return self.render('tb_osc.spi', {
            f'.lib "{self.source.MODEL}" ff': f'.lib "{self.source.MODEL}" {corner}',
            '.param supply=1.62': f'.param supply={supply}', '.temp 85': f'.temp {temperature}'}, design, model)

    def checks(self, case, row):
        completeness = self.require(case, row, self.source.REQUIRED)
        if not completeness[0]['passed']:
            return completeness
        point = tuple(case['point'])
        state = self.source.characterize({'point': point, 'name': point_id(point), 'values': row['values']})
        if state is None:
            return predicates([('valid_oscillation', False, 'Nonpositive or invalid period')])
        items = [('pvt_frequency', 1.8e6 <= state['frequency'] <= 2.2e6, str(state['frequency'])),
                 ('pvt_output_swing', state['swing_low'] <= state['swing'] <= state['swing_high'], str(state['swing']))]
        if point == self.source.NOMINAL:
            items.append(('nominal_power', state['power'] <= 20e-6, str(state['power'])))
        return predicates(items)

    def original_suite_checks(self, rows, run_summary):
        normalized = [{'point': tuple(r['point']), 'name': point_id(r['point']), 'values': r['values']} for r in rows]
        return predicates(self.source.checks(normalized, set(self.source.POINTS)))


class UnregulatedChargePump(SourceScalar):
    slug = 'unregulated-charge-pump-10mhz-pvt'

    def plan(self):
        return [{'id': a + '__' + point_id(p), 'score_group': point_id(p), 'point': p,
                 'analysis': a, 'profile': 'tt' if p == self.source.NOMINAL else 'pvt'}
                for p in self.source.PVT for a in ('enabled', 'disabled')]

    def deck(self, case, design, model):
        corner, temperature = case['point']
        filename = 'tb_charge_pump.spi' if case['analysis'] == 'enabled' else 'tb_charge_pump_pd.spi'
        return self.render(filename, {
            f'.lib "{self.source.MODEL}" ff': f'.lib "{self.source.MODEL}" {corner}',
            '.temp 40': f'.temp {temperature}'}, design, model)

    def checks(self, case, row):
        fields = self.source.REQUIRED[:4] if case['analysis'] == 'enabled' else self.source.REQUIRED[4:]
        return self.require(case, row, fields)

    @staticmethod
    def combine(rows):
        merged = {}
        for row in rows:
            p = tuple(row['point'])
            merged.setdefault(p, {'point': p, 'name': point_id(p)}).update(row['values'])
        return merged

    def reduce_suite(self, records, report):
        rows = self.combine(available_rows(records))
        for p in self.source.PVT:
            checks = predicates(self.source.checks([rows[p]] if p in rows else [], {p}))
            apply_reduction(report, point_id(p), checks)
        return report

    def reduce_selected(self, records, report, plan):
        rows = self.combine(available_rows(records))
        for point in sorted({tuple(c['point']) for c in plan}):
            selected = {c['analysis'] for c in plan if tuple(c['point']) == point}
            if selected != {'enabled', 'disabled'}:
                raise ValueError('Selected charge-pump point requires enabled and disabled fixtures')
            checks = predicates(self.source.checks([rows[point]] if point in rows else [], {point}))
            apply_reduction(report, point_id(point), checks)
        report['passed_group_count'] = sum(g['passed'] for g in report['group_results'].values())
        return report

    def original_suite_checks(self, rows, run_summary):
        return predicates(self.source.checks(list(self.combine(rows).values()), set(self.source.PVT)))
