"""Original FD Miller PVT, representative transient and20-seed rejection tests."""
from .release_power_suites import SourceScalar
from .release_reference_suites import predicates,available_rows,apply_reduction
from .common import point_id


class FdMiller(SourceScalar):
    slug='fd-two-stage-miller-opamp-gain60-pm60-noise50uv-pvt'

    def plan(self):
        s=self.source;jobs=[(a,p,None) for p in s.PVT for a in ('op_ac','noise')]
        jobs += [(a,p,None) for p in s.REPRESENTATIVE_POINTS for a in ('swing','settling','cm_recovery')]
        jobs += [('mc',s.NOMINAL,s.FIRST_SEED+i) for i in range(s.MC_RUNS)]
        return [{'id':a+'__'+point_id(p)+(('__'+str(seed)) if seed is not None else ''),'score_group':point_id(p),
                 'analysis':a,'point':p,'seed':seed,'profile':'tt' if p==s.NOMINAL and seed is None else 'pvt'} for a,p,seed in jobs]

    def deck(self,case,design,model):
        s=self.source;replacements=s.substitutions(tuple(case['point']))
        if case['analysis'] in ('op_ac','noise'):
            replacements['set points = ( 0 1 2 3 4 5 6 7 8 )']=f'set points = ( {s.point_index(tuple(case["point"]))} )'
        if case['seed'] is not None:replacements['.option seed=41000']=f'.option seed={case["seed"]}'
        return self.render('tb_'+case['analysis']+'.spi',replacements,design,model)

    def analyze(self,case,work,run):
        values=self.parse((work/'ngspice.log').read_text(errors='replace'));s=self.source;a=case['analysis']
        if a in ('op_ac','noise'):
            fields=s.OP_AC_METRICS if a=='op_ac' else ('input_noise_vrms',)
            prefix=f'm{s.point_index(tuple(case["point"]))}_'
            values={name:values[prefix+name] for name in fields if prefix+name in values}
        return {'point':tuple(case['point']),'analysis':a,'seed':case['seed'],'values':values}

    def checks(self,case,row):
        s=self.source;a=case['analysis'];v=row['values']
        fields={'op_ac':s.OP_AC_METRICS,'noise':('input_noise_vrms',),'mc':s.MC_METRICS,
                'swing':('closed_loop_range_vpp','closed_loop_tracking_error_v_max'),
                'settling':('settling_time_s','settling_error_fraction'),
                'cm_recovery':('cm_recovery_time_s','cm_recovery_error_v')}[a]
        complete=self.require(case,row,fields)
        if not complete[0]['passed'] or a=='mc':return complete
        if a=='op_ac':
            items=[('gain',v['dc_gain_db']>=s.GAIN_LIMIT_DB),('ugb',v['ugb_hz']>=s.UGB_LIMIT_HZ),
                   ('phase_margin',v['phase_margin_deg']>=s.PHASE_MARGIN_LIMIT_DEG),
                   ('common_mode',v['output_common_mode_error_v']<=s.OUTPUT_COMMON_MODE_LIMIT_V),
                   ('balance',v['output_balance_error_v']<=s.OUTPUT_BALANCE_LIMIT_V),('power',v['power_w']<=s.POWER_LIMIT_W)]
        elif a=='noise':items=[('noise',v['input_noise_vrms']<=s.NOISE_LIMIT_VRMS)]
        elif a=='swing':items=[('range',v['closed_loop_range_vpp']>=.8),('tracking',v['closed_loop_tracking_error_v_max']<=5e-3)]
        elif a=='settling':items=[('settling_time',v['settling_time_s']<=15e-9),('settling_error',v['settling_error_fraction']<=.01)]
        else:items=[('recovery_time',v['cm_recovery_time_s']<=100e-9),('recovery_error',v['cm_recovery_error_v']<=10e-3)]
        return predicates([(name,ok,str(v)) for name,ok in items])

    def normalize(self,rows,a):
        s=self.source
        return [{'point':tuple(r['point']),'name':s.point_name(r['point'])+(('/seed-'+str(r['seed'])) if r['seed'] is not None else ''),
                 'bench':a,**r['values']} for r in rows if r['analysis']==a]

    def reduce_suite(self,records,report):
        rows=available_rows(records);s=self.source;mc=self.normalize(rows,'mc')
        secondary=[r for a in ('swing','settling','cm_recovery') for r in self.normalize(rows,a)]
        checks=predicates(s.secondary_checks(secondary,mc))
        rejection=[c for c in checks if c['name'] in ('common_mode_rejection','supply_rejection')]
        apply_reduction(report,point_id(s.NOMINAL),rejection);return report

    def reduce_selected(self, records, report, plan):
        """Apply the original rejection limits to the selected public seeds.

        Selecting the public seed 41000 does not establish the original
        twenty-seed requirement. Per-analysis completeness is checked by the
        runner; this reduction keeps the rejection calculation within each
        selected seed, rather than mixing gains between samples.
        """
        selected = [case for case in plan if case['analysis'] == 'mc']
        by_id = {record['case_id']: record for record in records}
        for case in selected:
            record = by_id.get(case['id'])
            row = record.get('row') if record else None
            checks = []
            if row is None or record.get('error'):
                checks = predicates([('public_mismatch_complete', False, case['id'])])
            else:
                complete = self.require(case, row, self.source.MC_METRICS)
                checks.extend(complete)
                if complete[0]['passed']:
                    values = row['values']
                    gain = values['mc_differential_10_db']
                    cmrr = gain - values['mc_common_mode_10_db']
                    positive = gain - values['mc_vdd_10_db']
                    negative = gain - values['mc_vss_10_db']
                    checks.extend(predicates([
                        ('public_common_mode_rejection', cmrr >= 50, f'{case["id"]}: {cmrr} dB >= 50 dB'),
                        ('public_supply_rejection', positive >= 40 and negative >= 40,
                         f'{case["id"]}: PSRR+={positive}, PSRR-={negative} dB >= 40 dB'),
                    ]))
            apply_reduction(report, case['score_group'], checks)
        return report

    def original_suite_checks(self,rows,run_summary):
        s=self.source;primary=s.primary_checks(self.normalize(rows,'op_ac'))
        noise=s.threshold(self.normalize(rows,'noise'),s.PVT_COUNT,('pvt_input_noise','input_noise_vrms',s.NOISE_LIMIT_VRMS,False,1e6,'uVrms'))
        secondary=[r for a in ('swing','settling','cm_recovery') for r in self.normalize(rows,a)]
        return predicates(primary+[noise]+s.secondary_checks(secondary,self.normalize(rows,'mc')))
