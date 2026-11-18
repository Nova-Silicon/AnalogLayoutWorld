"""Original NMOS LDO PVT/load/headroom and fixed-seed mismatch checks."""
from pathlib import Path
import math
import re
import statistics

from .common import load_source, point_id
from .release_reference_suites import predicates, available_rows, apply_reduction, unassessed


class NmosLdo:
    slug = 'nmos-pass-ldo-0p4v-pvt-mc'

    def __init__(self, source_path: Path, reference=False):
        self.source = load_source(self.slug, source_path)
        self.reference = reference

    def plan(self):
        cases = []
        for p in self.source.POINTS:
            point = (p.corner,p.vin_v,p.temp_c)
            cases.append({'id': 'pvt__'+point_id((*point,p.load_a)), 'score_group':point_id(point),
                'point':point,'load':p.load_a,'analysis':'pvt', 'profile':'tt' if p == self.source.NOMINAL else 'pvt'})
        for seed in self.source.MC_SEEDS:
            cases.append({'id':'mc__'+str(seed),'score_group':point_id(('tt',1.8,27)),
                'point':('tt',1.8,27),'seed':seed,'analysis':'mc','profile':'pvt'})
        return cases

    def deck(self, case, design, model):
        path=Path(self.source.__file__).parent/'benches'/('tb_point.spi' if case['analysis']=='pvt' else 'tb_mc.spi')
        text=path.read_text().replace('/app/circuit.spi',str(design)).replace('/opt/sky130/continuous/sky130.lib.spice',str(model))
        values={'@@CORNER@@':case['point'][0], '@@VIN_V@@':case['point'][1], '@@TEMP_C@@':case['point'][2],
                '@@LOAD_A@@':case.get('load',0), '@@SEED@@':case.get('seed',0)}
        for old,value in values.items():text=text.replace(old,str(value))
        if case['analysis'] == 'pvt':
            # The source headroom check consumes only vds, vdsat and id from
            # MOS tables. ngspice's device-type selector includes hierarchical
            # MOS instances and preserves the table format used by the source
            # parser; avoid dumping every extracted resistor/capacitor and all
            # unrelated device parameters. Redirect only stdout so later
            # stderr convergence diagnostics cannot split a buffered table.
            # See ngspice 46 manual 13.5.80 and 13.4.1.
            text, count = re.subn(r'(?im)^[ \t]*show[ \t]+all[ \t]*$',
                                 'show m : vds vdsat id > mos_headroom.log', text)
            if count != 1:
                raise ValueError('Expected one source MOS headroom show command')
        return text,False

    def analyze(self, case, work, run):
        text=(work/'ngspice.log').read_text(errors='replace')
        margins=()
        headroom={'required':case['analysis']=='pvt', 'path':'mos_headroom.log',
                  'complete':False, 'device_count':0, 'error':None}
        if headroom['required']:
            try:
                table=(work/'mos_headroom.log').read_text()
                headroom.update(self._headroom_table_integrity(table))
                if headroom['complete']:
                    margins=self.source.parse_active_mos_margins(table)
            except (OSError, UnicodeError) as exc:
                headroom['error']=f'{type(exc).__name__}: {exc}'
        return {'values':self.source.parse_measures(text),'margins':margins,
                'headroom_output':headroom,
                'point':case['point'],'load':case.get('load'),'seed':case.get('seed'),'analysis':case['analysis']}

    def _headroom_table_integrity(self, text):
        # The unmodified upstream parser skips incomplete groups. Require all
        # selected MOS columns to be present before applying that same parser.
        groups=[]
        current=None
        for line in text.splitlines():
            if match:=self.source.DEVICE.match(line):
                current={'count':len(match.group(1).split()), 'parameters':set()}
                groups.append(current)
            elif current is not None and (match:=self.source.PROPERTY.match(line)):
                try:
                    values=[float(value) for value in match.group(2).split()]
                except ValueError:
                    continue
                if len(values)==current['count'] and all(math.isfinite(v) for v in values):
                    current['parameters'].add(match.group(1).lower())
        complete=bool(groups) and all(g['count']>0 and g['parameters']=={'vds','vdsat','id'} for g in groups)
        return {'complete':complete, 'device_count':sum(g['count'] for g in groups),
                'error':None if complete else 'Missing or incomplete MOS vds/vdsat/id table'}

    def checks(self, case, row):
        s=self.source;v=row['values']
        if row['analysis']!=case['analysis'] or tuple(row['point'])!=tuple(case['point']):
            raise ValueError('NMOS LDO row identity mismatch')
        fields=s.REQUIRED_POINT_MEASURES if case['analysis']=='pvt' else ('mc_vout_1ma_v','mc_vout_5ma_v')
        complete=all(k in v and math.isfinite(v[k]) for k in fields)
        if not complete or case['analysis']=='mc':
            return predicates([('finite_source_measurements',complete,'All original scalar measurements required')])
        return predicates([
            ('output_range',s.OUTPUT_MIN_V<=v['vout_dc_v']<=s.OUTPUT_MAX_V,str(v['vout_dc_v'])),
            ('quiescent_current',0<=v['iq_a']<s.IQ_MAX_A,str(v['iq_a'])),
            ('phase_margin',v['phase_margin_deg']>s.PHASE_MARGIN_MIN_DEG,str(v['phase_margin_deg'])),
            ('gain_margin',v['gain_margin_db']>s.GAIN_MARGIN_MIN_DB,str(v['gain_margin_db'])),
            ('psrr',v['psrr_1khz_db']>s.PSRR_1KHZ_MIN_DB,str(v['psrr_1khz_db'])),
            ('active_mos_headroom',bool(row['margins']) and all(math.isfinite(m) and m>s.HEADROOM_MIN_V for m in row['margins']),
             str(row['margins']) if row['margins'] else str(row.get('headroom_output',{})))])

    def mc_checks(self, rows):
        s=self.source;mc=[r for r in rows if r['analysis']=='mc']
        complete=len(mc)==len(s.MC_SEEDS) and {r['seed'] for r in mc}==set(s.MC_SEEDS)
        checks=[]
        for field in ('mc_vout_1ma_v','mc_vout_5ma_v'):
            values=[r['values'].get(field) for r in mc]
            valid=complete and all(isinstance(v,(float,int)) and math.isfinite(v) for v in values)
            bounds=None
            if valid:
                mean=statistics.fmean(values);sigma=statistics.stdev(values);bounds=(mean-3*sigma,mean+3*sigma)
            checks.append((field+'_3sigma',valid and bounds[0]>=s.OUTPUT_MIN_V and bounds[1]<=s.OUTPUT_MAX_V,str(bounds)))
        return predicates(checks)

    def reduce_suite(self, records, report):
        apply_reduction(report,point_id(('tt',1.8,27)),self.mc_checks(available_rows(records)))
        return report

    def reduce_selected(self, records, report, plan):
        selected = {case['seed'] for case in plan if case['analysis'] == 'mc'}
        if selected == set(self.source.MC_SEEDS):
            return self.reduce_suite(records, report)
        unassessed(report, 'mc_output_3sigma',
                   f'{len(selected)}/{len(self.source.MC_SEEDS)} fixed samples selected; '
                   'the full-sample mean +/-3 sigma requirement is not measured.')
        return report

    def original_suite_checks(self, rows, run_summary):
        expected={(c['analysis'],tuple(c['point']),c.get('load'),c.get('seed')) for c in self.plan()}
        actual={(r['analysis'],tuple(r['point']),r.get('load'),r.get('seed')) for r in rows}
        checks=predicates([('complete_source_matrix',len(rows)==len(expected) and actual==expected,
                            f'{len(rows)}/{len(expected)} exact original cases')])
        by={(r['analysis'],tuple(r['point']),r.get('load'),r.get('seed')):r for r in rows}
        for case in self.plan():
            key=(case['analysis'],tuple(case['point']),case.get('load'),case.get('seed'))
            if key in by and case['analysis']=='pvt':
                for check in self.checks(case,by[key]):
                    checks.append({**check,'name':case['id']+'__'+check['name']})
        return checks+self.mc_checks(rows)
