"""Fixed original bandgap OP/startup/noise/line-step/Monte-Carlo contract."""
import math
from pathlib import Path

from .common import load_source, point_id
from .release_waveform import require_native_coverage
from .release_reference_suites import BetaMultiplier, predicates, available_rows, apply_reduction, unassessed


class Bandgap(BetaMultiplier):
    slug = 'bandgap-reference-pvt'

    def __init__(self, source_path: Path, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference
        self.nominal = ('tt', 1.8, 27)
        self.op_targets = {}

    def plan(self):
        cases = []
        for item in self.source.build_cases(self.source.SPEC):
            p = (item['corner'], item['vdd'], item['temp_c'])
            ident = item['group']+'__'+point_id(p)
            if 'seed' in item:
                ident += '__seed'+str(item['seed'])
            if 'ramp_s' in item:
                ident += '__ramp'+str(item['ramp_s'])
            group = point_id(self.nominal if item['group'] == 'mc' else p)
            cases.append({**item, 'id': ident, 'score_group': group,
                          'profile': 'tt' if p == self.nominal else 'pvt'})
        return cases

    def analysis_dependencies(self, case):
        """Line-step settling uses independent DC targets at both supplies.

        These are existing original OP cases, not extra scoring conditions or
        targets inferred from the transient being assessed.
        """
        if case['group'] != 'line_step':
            return []
        config = self.source.SPEC['line_step']
        result = []
        for supply in (config['high_supply_v'], config['low_supply_v']):
            matches = [item['id'] for item in self.plan()
                       if item['group'] == 'op' and item['corner'] == case['corner']
                       and item['temp_c'] == case['temp_c'] and item['vdd'] == supply]
            if len(matches) != 1:
                raise ValueError(f'Line-step needs one source OP at {supply}V '
                                 f'for {case["corner"]}/{case["temp_c"]}C')
            result.append(matches[0])
        return result

    def deck(self, case, design, model):
        source = self.source; spec = source.SPEC
        text = (Path(source.__file__).parent/'benches'/case['bench']).read_text()
        if case['group'] == 'mc':
            text = text.replace('%SEED%', str(case['seed']))
        elif case['group'] == 'line_step':
            cfg = spec['line_step']
            values = {'VDD_INITIAL': cfg['initial_supply_v'], 'VDD_HIGH':cfg['high_supply_v'],
                      'VDD_LOW':cfg['low_supply_v'], 'STEP_UP':cfg['step_up_time_s'],
                      'STEP_UP_END':cfg['step_up_time_s']+10e-9, 'STEP_DOWN':cfg['step_down_time_s'],
                      'STEP_DOWN_END':cfg['step_down_time_s']+10e-9, 'STOP':cfg['stop_time_s'],
                      'CLOAD':spec['operating']['output_load_f']}
            for name, value in values.items():
                text = text.replace('%'+name+'%', f'{value:g}')
        ramp = case.get('ramp_s')
        stop = ramp+spec['operating']['startup_stop_after_ramp_s'] if ramp is not None else None
        return source.instantiate(text, model, design, case['corner'], case['vdd'], case['temp_c'], case['group'], ramp, stop), True

    def analyze(self, case, work, run):
        require_native_coverage(work)
        row = self.source.analyze(self.identity(case), work/'analysis.raw', self.source.SPEC, self.op_targets)
        if case['group'] == 'op':
            self.op_targets[(case['corner'], case['temp_c'], case['vdd'])] = row['reference_voltage_v']
        return {**row, 'run_time_s':run['wall_seconds']}

    def checks(self, case, row):
        if any(row.get(key) != value for key, value in self.identity(case).items()):
            raise ValueError('Bandgap case identity mismatch')
        lim = self.source.SPEC['limits']; g = case['group']
        def bounds(name, value, low=-math.inf, high=math.inf):
            return (name, math.isfinite(value) and low <= value <= high, str(value))
        if g == 'op':
            return predicates([bounds('reference_voltage', row['reference_voltage_v'], lim['reference_voltage_v_min'],lim['reference_voltage_v_max']),
                               bounds('power', row['power_w'],0,lim['power_w_max'])])
        if g == 'startup':
            return predicates([bounds('startup_window_low',row['startup_window_v_min'],lim['reference_voltage_v_min']),
                bounds('startup_window_high',row['startup_window_v_max'],high=lim['reference_voltage_v_max']),
                bounds('startup_overshoot',row['startup_overshoot_v'],high=lim['startup_overshoot_v_max']),
                bounds('startup_peak_current',row['startup_peak_supply_current_a'],high=lim['startup_peak_supply_current_a_max']),
                bounds('startup_energy',row['startup_energy_j'],high=lim['startup_energy_j_max'])])
        if g == 'ac':
            return predicates([bounds('supply_gain',row['supply_gain_max'],high=lim['supply_gain_max'])])
        if g == 'noise':
            return predicates([bounds('integrated_noise',row['integrated_noise_v'],high=lim['integrated_noise_v_max'])])
        if g == 'line_step':
            return predicates([bounds('line_step_excursion',row['line_step_excursion_v'],high=lim['line_step_excursion_v_max']),
                               bounds('line_step_settling',row['line_step_settling_time_s'],high=lim['line_step_settling_time_s_max'])])
        if g == 'mc':
            return predicates([bounds('finite_mc_sample',row['reference_voltage_v'])])
        raise ValueError('Unknown bandgap analysis')

    def reduce_suite(self, records, report):
        rows = available_rows(records); spec=self.source.SPEC; lim=spec['limits']; pvt=spec['pvt']
        for corner in pvt['corners']:
            temp = [r for r in rows if r['group']=='op' and r['corner']==corner and self.source.belongs_to(r,'temperature')]
            line = [r for r in rows if r['group']=='op' and r['corner']==corner and self.source.belongs_to(r,'line')]
            values = [r['reference_voltage_v'] for r in temp]
            tc = math.inf
            if len(values)==len(pvt['temperature_sweep_c']) and sum(values)>0:
                tc=(max(values)-min(values))/(sum(values)/len(values))/(max(pvt['temperature_sweep_c'])-min(pvt['temperature_sweep_c']))*1e6
            values = [r['reference_voltage_v'] for r in line]
            lr=(max(values)-min(values))/(max(pvt['supply_voltages_v'])-min(pvt['supply_voltages_v'])) if len(values)==len(pvt['supply_voltages_v']) else math.inf
            checks=predicates([('temperature_coefficient',math.isfinite(tc) and tc<=lim['temperature_coefficient_ppm_per_c_max'],str(tc)),
                               ('line_regulation',math.isfinite(lr) and lr<=lim['line_regulation_v_per_v_max'],str(lr))])
            for group in report['group_results']:
                if group.startswith(corner+'__'):
                    apply_reduction(report,group,checks)
        apply_reduction(report, point_id(self.nominal), self.mc_checks(rows))
        return report

    def original_suite_checks(self, rows, run_summary):
        return self.source_checks(rows, run_summary)

    def reduce_selected(self, records, report, plan):
        # These multi-point statistics are not inferable from the public single
        # OP and single mismatch sample. Full-plan scoring remains above.
        selected_ops = [case for case in plan if case['group'] == 'op']
        if len(selected_ops) > 1:
            raise ValueError('Bandgap selected evaluation supports the public single-OP fixture; '
                             'a different sweep needs an explicit statistical coverage definition')
        selected_mc = [case for case in plan if case['group'] == 'mc']
        full_mc = {case['id'] for case in self.plan() if case['group'] == 'mc'}
        if selected_mc and {case['id'] for case in selected_mc} == full_mc:
            # Reference qualification selects the complete fixed seed set:
            # apply the original yield and sigma limits, nothing else.
            rows = [row for row in available_rows(records) if row['group'] == 'mc']
            apply_reduction(report, point_id(self.nominal), self.mc_checks(rows))
        elif len(selected_mc) > 1:
            raise ValueError('Bandgap selected evaluation supports one MC sample or the complete '
                             'fixed seed set; a partial set has no statistical definition')
        else:
            unassessed(report, 'mc_yield_and_sigma',
                       f'{len(selected_mc)}/{self.source.SPEC["monte_carlo"]["runs"]} fixed samples selected.')
        unassessed(report, 'temperature_coefficient',
                   'The selected OP fixture does not include the full temperature sweep.')
        unassessed(report, 'line_regulation',
                   'The selected OP fixture does not include the full DC supply sweep. '
                   'The separate selected line-step transient is still checked.')
        report['passed_group_count'] = sum(group['passed'] for group in report['group_results'].values())
        return report

    def mc_checks(self, rows):
        """Original 30-seed yield and sigma limits (shared by full-plan and qualification)."""
        spec = self.source.SPEC; lim = spec['limits']; expected = spec['monte_carlo']['runs']
        first = spec['monte_carlo']['first_seed']
        mc = [r for r in rows if r['group'] == 'mc']
        complete = len(mc) == expected and {r.get('seed') for r in mc} == set(range(first, first + expected))
        values = [r['reference_voltage_v'] for r in mc]; mean = sum(values) / len(values) if values else 0
        sigma = math.sqrt(sum((v - mean) ** 2 for v in values) / (len(values) - 1)) if len(values) > 1 else math.inf
        yield_fraction = sum(spec['monte_carlo']['reference_voltage_v_min'] <= v <= spec['monte_carlo']['reference_voltage_v_max']
                             for v in values) / expected
        return predicates([
            ('mc_yield', complete and yield_fraction >= lim['mc_reference_yield_min'], str(yield_fraction)),
            ('mc_sigma', complete and math.isfinite(sigma) and sigma <= lim['mc_reference_sigma_v_max'], str(sigma))])
