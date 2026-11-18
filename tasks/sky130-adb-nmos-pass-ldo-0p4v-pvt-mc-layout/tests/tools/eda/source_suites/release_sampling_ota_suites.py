"""Fixed sampling-feedback OTA contracts; no synthesized feedback components."""
import contextlib
import io
import math
from .release_power_suites import SourceScalar
from .release_reference_suites import predicates, available_rows, apply_reduction, unassessed
from .common import point_id


class SamplingOta(SourceScalar):
    def plan(self):
        s=self.source
        jobs=[(a,p,None) for p in s.PVT for a in ('loop','settling','noise')]
        jobs += [('ranges',p,None) for p in self.range_points()]
        jobs += [('cmfb_recovery',p,None) for p in s.REPRESENTATIVE]
        jobs += [('mc',s.NOMINAL,s.FIRST_SEED+i) for i in range(s.MC_RUNS)]
        return [{'id':a+'__'+point_id(p)+(('__'+str(seed)) if seed is not None else ''),
                 'score_group':point_id(p),'analysis':a,'point':p,'seed':seed,
                 'profile':'tt' if p==s.NOMINAL and seed is None else 'pvt'} for a,p,seed in jobs]

    def deck(self,case,design,model):
        replacements=self.source.substitutions(tuple(case['point']))
        if case['seed'] is not None:
            replacements['.option seed=41000']=f'.option seed={case["seed"]}'
        return self.render('tb_'+case['analysis']+'.spi',replacements,design,model)

    def analyze(self,case,work,run):
        return {**super().analyze(case,work,run),'seed':case['seed']}

    def accuracy_limits(self):
        return self.source.STATIC_ERROR_LIMIT, self.source.DYNAMIC_ERROR_LIMIT

    def range_points(self):
        return [self.source.NOMINAL]

    def checks(self,case,row):
        s=self.source;v=row['values'];a=case['analysis']
        fields={'loop':s.LOOP_METRICS,'settling':s.SETTLING_METRICS,'noise':s.NOISE_METRICS,
                'ranges':s.RANGE_METRICS,'cmfb_recovery':s.CMFB_METRICS,'mc':s.MC_METRICS}[a]
        required=self.require(case,row,fields)
        if not required[0]['passed'] or a=='mc':return required
        if a=='loop':
            items=[('phase_margin',v['phase_margin_deg']>=s.PM_LIMIT_DEG),
                ('output_common_mode',v['output_common_mode_error_v']<=s.OUTPUT_COMMON_MODE_LIMIT_V),
                ('power',v['power_w']<=s.POWER_LIMIT_W)]
        elif a=='settling':
            static_limit,dynamic_limit=self.accuracy_limits()
            items=[('static_accuracy',max(v['high_static_error_fraction'],v['low_static_error_fraction'])<=static_limit),
                ('dynamic_accuracy',max(v['rise_dynamic_error_fraction'],v['fall_dynamic_error_fraction'])<=dynamic_limit),
                ('settling',max(v['rise_settling_time_s'],v['fall_settling_time_s'])<=s.SETTLING_LIMIT_S)]
        elif a=='noise':items=[('output_noise',v['output_noise_vrms']<=s.NOISE_LIMIT_VRMS)]
        elif a=='ranges':items=[('output_range',v['output_range_max_v']-v['output_range_min_v']>=s.OUTPUT_RANGE_V)]
        else:items=[('cmfb_peak',v['cmfb_max_deviation_v']<=s.CMFB_PEAK_DEVIATION_LIMIT_V),
                    ('cmfb_20ns',v['cmfb_residual_20ns_v']<=s.CMFB_RESIDUAL_20NS_LIMIT_V),
                    ('cmfb_100ns',v['cmfb_residual_100ns_v']<=s.CMFB_RESIDUAL_100NS_LIMIT_V)]
        return predicates([(name,ok,str(v)) for name,ok in items])

    def reduce_suite(self,records,report):
        rows=available_rows(records);s=self.source
        mc=[r for r in rows if r['analysis']=='mc'];nominal=next((r for r in rows if r['analysis']=='loop' and tuple(r['point'])==s.NOMINAL),None)
        complete=(len(mc)==s.MC_RUNS and {r['seed'] for r in mc}==set(range(s.FIRST_SEED,s.FIRST_SEED+s.MC_RUNS)) and nominal is not None)
        checks=[]
        for name,field,limit in [('mc_cmrr','mc_closed_cm_10_db',s.CMRR_LIMIT_DB),
                                ('mc_psrr_plus','mc_closed_vdd_10_db',s.PSRR_LIMIT_DB),
                                ('mc_psrr_minus','mc_closed_vss_10_db',s.PSRR_LIMIT_DB)]:
            gain=nominal['values'].get('closed_loop_differential_gain_db') if nominal else None
            values=[gain-r['values'][field] for r in mc] if complete and gain is not None and all(field in r['values'] for r in mc) else []
            checks.append((name,bool(values) and len(values)==s.MC_RUNS and all(math.isfinite(v) and v>=limit for v in values),str(min(values) if values else None)))
        apply_reduction(report,point_id(s.NOMINAL),predicates(checks));return report

    def reduce_selected(self, records, report, plan):
        s = self.source
        selected_seeds = {c['seed'] for c in plan if c['analysis'] == 'mc'}
        if selected_seeds:
            rows = available_rows(records)
            samples = [r for r in rows if r['analysis'] == 'mc']
            nominal = next((r for r in rows if r['analysis'] == 'loop'
                            and tuple(r['point']) == s.NOMINAL), None)
            gain = nominal['values'].get('closed_loop_differential_gain_db') if nominal else None
            complete = (len(samples) == len(selected_seeds)
                        and {r['seed'] for r in samples} == selected_seeds
                        and isinstance(gain, (int, float)) and math.isfinite(gain))
            checks = []
            for name, field, limit in (
                ('mc_cmrr', 'mc_closed_cm_10_db', s.CMRR_LIMIT_DB),
                ('mc_psrr_plus', 'mc_closed_vdd_10_db', s.PSRR_LIMIT_DB),
                ('mc_psrr_minus', 'mc_closed_vss_10_db', s.PSRR_LIMIT_DB),
            ):
                values = ([gain - r['values'][field] for r in samples]
                          if complete and all(field in r['values'] for r in samples) else [])
                checks.append((name, bool(values) and all(math.isfinite(v) and v >= limit for v in values),
                               f'Selected samples, same-point nominal loop gain: {values}'))
            apply_reduction(report, point_id(s.NOMINAL), predicates(checks))
        if selected_seeds != set(range(s.FIRST_SEED, s.FIRST_SEED + s.MC_RUNS)):
            unassessed(report, 'complete_mismatch_seed_coverage',
                       f'{len(selected_seeds)}/{s.MC_RUNS} original fixed samples selected.')
        return report

    def original_suite_checks(self,rows,run_summary):
        """Replay frozen source control flow with recorded rows; never rerun SPICE."""
        s=self.source;indexed={(r['analysis'],tuple(r['point']),r['seed']):r for r in rows};captured=[]
        expected={(c['analysis'],tuple(c['point']),c['seed']) for c in self.plan()}
        if set(indexed)!=expected or len(rows)!=len(expected):
            return predicates([('complete_source_matrix',False,f'{len(rows)}/{len(expected)}')])
        original_run,original_write=s.run,s.write_results
        def lookup(bench,point,seed=None):
            r=indexed[(bench,tuple(point),seed)]
            return {'point':tuple(point),'name':s.point_name(point)+(('/seed-'+str(seed)) if seed is not None else ''),**r['values']}
        try:
            s.run=lookup;s.write_results=lambda checks:captured.extend(checks)
            with contextlib.redirect_stdout(io.StringIO()):s.main()
        finally:s.run=original_run;s.write_results=original_write
        return predicates(captured)


class SamplingGain1(SamplingOta):
    slug='fd-sampling-feedback-ota-gain1-settling40ns-noise300uv-pvt-mc'


class SamplingGain8(SamplingOta):
    slug='fd-sampling-feedback-ota-gain8-settling10ns-noise1mv-pvt-mc'

    def accuracy_limits(self):
        return self.source.ERROR_LIMIT, self.source.ERROR_LIMIT

    def range_points(self):
        return self.source.PVT
