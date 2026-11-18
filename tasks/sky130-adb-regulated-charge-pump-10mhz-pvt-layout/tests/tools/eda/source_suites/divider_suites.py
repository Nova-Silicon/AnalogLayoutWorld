"""CML divider: complete per-cycle checks and target-frequency tone evidence."""
import math
from pathlib import Path

from .additional_suites import ScalarFixture
from .ota_suites import check_rows
from .common import load_source, point_id


class CmlDivider(ScalarFixture):
    slug = 'cml-divider-div2-range1gto10g'
    nominal = ('tt', 1.8, 27)

    def __init__(self, source_path: Path | None = None, reference: bool = False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        self.parse_measures = self.source.parse_measures

    def plan(self):
        cases = []
        for corner in self.source.CORNERS:
            point = (corner, 1.8, 27)
            group = point_id(point)
            for label, frequency in self.source.SPEEDS:
                cases.append({'id': label + '__' + group, 'score_group': group, 'bench': 'divider',
                              'point': point, 'label': label, 'frequency': frequency,
                              'frequency_hz': float(frequency[:-3]) * 1e9})
            cases.append({'id': 'power__' + group, 'score_group': group, 'bench': 'power', 'point': point})
        return cases

    def deck(self, case, design, model):
        s = self.source
        text = (s.HERE / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        corner = case['point'][0]
        text = s.instantiate(text, corner, case.get('frequency'), '300m' if case['bench'] == 'divider' else None)
        text = text.replace(f'.lib "{s.MODEL}" {corner}', f'.lib "{model}" {corner}', 1)
        text = text.replace('.include "/app/circuit.spi"', f'.include "{design}"', 1)
        if str(design) not in text or str(model) not in text:
            raise ValueError('Original CML fixture paths unresolved')
        return text, case['bench'] == 'divider'

    def analyze(self, case, work, run):
        if case['bench'] == 'power':
            return super().analyze(case, work, run)
        waveform = self.source.parse_raw(work / 'analysis.raw')
        metrics = self.source.divider_metrics(waveform, case['frequency_hz'])
        return {'bench': case['bench'], 'point': tuple(case['point']), 'corner': case['point'][0],
                'label': case['label'], 'frequency_hz': case['frequency_hz'], 'metrics': metrics,
                'waveform_sample_count': len(waveform), 'error': None}

    def checks(self, case, row):
        row = self.normalized(case, row)
        if case['bench'] == 'power':
            return check_rows([('dc_power', 'power_w' in row and row['power_w'] < self.source.POWER_MAX_W,
                                'Original power_check uses strict <1.5 mW at each corner')])
        if row.get('label') != case['label'] or row.get('frequency_hz') != case['frequency_hz'] or row.get('corner') != case['point'][0]:
            raise ValueError('Divider data belongs to another speed/corner')
        metrics = row.get('metrics', {})
        required = ('output_swing_vpp', 'minimum_cycle_swing_vpp', 'target_tone_vpp', 'alternating_cycles')
        complete = all(k in metrics and math.isfinite(metrics[k]) for k in required)
        return check_rows([('divide_operating_point', complete and metrics.get('pass') is True,
                            'Original divider_metrics requires 40 complete alternating cycles, per-cycle swing, and time-weighted input/2 tone')])

    def original_suite_checks(self, rows, run_summary):
        speed, evidence = self.source.speed_check([r for r in rows if r['bench'] == 'divider'], self.source.CORNERS)
        power = [r for r in rows if r['bench'] == 'power']
        complete = len(power) == len(self.source.CORNERS) and {tuple(r['point'])[0] for r in power} == set(self.source.CORNERS) and all('power_w' in r for r in power)
        # Original power_check() owns simulation; reuse its exact final
        # reduction without executing a second hidden native run.
        power_ok = complete and max(r['power_w'] for r in power) < self.source.POWER_MAX_W
        return check_rows([speed, ('dc_power', power_ok, 'Original all-corner finite power maximum <1.5 mW')])
