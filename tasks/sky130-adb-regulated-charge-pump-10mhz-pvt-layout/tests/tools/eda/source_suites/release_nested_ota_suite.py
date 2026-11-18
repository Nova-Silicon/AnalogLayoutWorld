"""Original five-analysis,45-PVT nested-Miller OTA electrical contract."""
from pathlib import Path
import math
from .common import load_source,point_id
from .release_waveform import require_native_coverage
from .release_reference_suites import predicates


class NestedMiller:
    slug='three-stage-nested-miller-ota-pvt'

    def __init__(self,source_path:Path,reference=False):
        self.source=load_source(self.slug,source_path);self.reference=reference

    def plan(self):
        return [{'id':g+'__'+point_id(p),'score_group':point_id(p),'group':g,'point':p,
                 'profile':'tt' if p==self.source.NOMINAL else 'pvt'}
                for p in self.source.PVT for g in self.source.GROUPS]

    def deck(self,case,design,model):
        return self.source.instantiate(self.source.BENCHES[case['group']].read_text(),model,design,tuple(case['point'])),True

    def analyze(self,case,work,run):
        require_native_coverage(work)
        point=tuple(case['point']);group=case['group']
        return {'group':group,'point':point,'name':self.source.point_name(point),'run_time_s':run['wall_seconds'],
                **self.source.extract_metrics(group,self.source.parse_raw(work/'analysis.raw'),point)}

    def checks(self,case,row):
        s=self.source;g=case['group'];lim=s.LIMITS
        if tuple(row['point'])!=tuple(case['point']) or row['group']!=g:
            raise ValueError('Nested Miller row identity mismatch')
        if not all(k in row and math.isfinite(row[k]) for k in s.EXPECTED_METRICS[g]):
            return predicates([('complete_measurements',False,'Every original field must be finite')])
        if g=='pvt':
            items=[('gain',row['dc_gain_db']>=lim['dc_gain_db_min']),('bandwidth',row['ugb_hz']>=lim['ugb_hz_min']),
                   ('drive_fom',row['drive_fom_khz_pf_per_uw']>=lim['drive_fom_khz_pf_per_uw_min']),
                   ('phase_margin',row['phase_margin_deg']>=lim['phase_margin_deg_min']),
                   ('bias',row['output_common_mode_error_v']<=lim['output_common_mode_error_v_max']),
                   ('power',row['power_w']<lim['power_w_max'])]
        elif g=='input_bias':items=[('input_bias',max(row['input_bias_vinp_a'],row['input_bias_vinn_a'])<=lim['input_bias_current_a_max'])]
        elif g=='swing':items=[('closed_loop_range',row['closed_loop_range_vpp']>=lim['closed_loop_output_range_vpp_min'])]
        elif g=='settling':items=[('settling_time',row['settling_time_s']<lim['settling_time_s_max']),('settling_error',row['settling_error_fraction']<=lim['settling_error_fraction_max'])]
        else:items=[('slew',min(row['slew_rise_v_per_us'],row['slew_fall_v_per_us'])>=lim['slew_rate_v_per_us_min'])]
        return predicates([(name,ok,str({k:row[k] for k in s.EXPECTED_METRICS[g]})) for name,ok in items])

    def original_suite_checks(self,rows,run_summary):
        rows=[{**r,'point':tuple(r['point'])} for r in rows]
        nominal=self.source.nominal_functional([r for r in rows if r['point']==self.source.NOMINAL and r['group'] in ('pvt','settling')],[])
        checks,_=self.source.full_checks(rows,run_summary.get('failed_runs',[]),nominal)
        return predicates(checks)
