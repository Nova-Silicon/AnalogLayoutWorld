"""Original TIA noise-spectrum and coherent transient FFT measurement contract."""
import math
from .release_power_suites import SourceScalar
from .release_reference_suites import predicates
from .common import point_id
from .release_waveform import require_table_axis


class Tia(SourceScalar):
    slug='tia-zt8k-bw750m-noise5p-sfdr70-power5m-pt'

    def analysis_dependencies(self, case):
        # Each analyzer reads only its own log/table, never a previous row.
        return []

    def plan(self):
        return [{'id':a+'__'+point_id(p),'score_group':point_id(p),'analysis':a,'point':p,
                 'profile':'tt' if p==self.source.NOMINAL else 'pvt'}
                for p in self.source.POINTS for a in ('ac_power','noise','sfdr')]

    def deck(self,case,design,model):
        text,raw=self.render('tb_'+case['analysis']+'.spi',self.source.substitutions(tuple(case['point'])),design,model)
        return text.replace('NOISE_DATA_PATH','noise.dat').replace('SFDR_DATA_PATH','sfdr.dat'),raw

    def analyze(self,case,work,run):
        values=self.parse((work/'ngspice.log').read_text(errors='replace'));a=case['analysis'];s=self.source
        if a=='ac_power':
            zt=values.get('zt_1m_ohm');high=values.get('zt_10g_ohm')
            if 'bandwidth_hz' not in values and zt is not None and high is not None and high>=.7071067811865476*zt:
                values['bandwidth_hz']=10e9
        elif a=='noise':
            final_frequency=10e6 * 10**(math.floor(math.log10(500e6/10e6)*100+1e-7)/100)
            require_table_axis(work/'noise.dat',10e6,final_frequency)
            values={'noise_density_a_per_rt_hz':s.spectrum_max(work/'noise.dat'),'integrated_noise_a_rms':values['inoise_total']}
        else:
            require_table_axis(work/'sfdr.dat',10e-9,170e-9,first_tolerance=20e-12*1.01)
            zt,sfdr,spur=s.sfdr_metrics(work/'sfdr.dat');values={'large_signal_zt_ohm':zt,'sfdr_db':sfdr,'largest_spur_hz':spur}
        return {'analysis':a,'point':tuple(case['point']),'name':s.point_name(case['point']),**values}

    def checks(self,case,row):
        row={**row,'point':tuple(row['point'])};p=tuple(case['point']);s=self.source
        if row['point']!=p or row['analysis']!=case['analysis']:raise ValueError('TIA case identity mismatch')
        if case['analysis']=='ac_power':checks=s.ac_checks([row],{p})
        elif case['analysis']=='noise':checks=s.noise_checks([row],{p})
        else:checks=[s.sfdr_check([row],{p})]
        return predicates(checks)

    def original_suite_checks(self,rows,run_summary):
        rows=[{**r,'point':tuple(r['point'])} for r in rows];points=set(self.source.POINTS)
        groups={a:[r for r in rows if r['analysis']==a] for a in ('ac_power','noise','sfdr')}
        return predicates(self.source.ac_checks(groups['ac_power'],points)+self.source.noise_checks(groups['noise'],points)+[self.source.sfdr_check(groups['sfdr'],points)])
