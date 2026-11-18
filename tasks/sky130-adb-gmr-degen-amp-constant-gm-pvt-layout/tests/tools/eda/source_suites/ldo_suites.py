"""Capless-LDO source suite; fixed matrices and explicit electrical predicates."""
from .additional_suites import ScalarFixture
from .ota_suites import check_rows
from .common import point_id


class CaplessLdo(ScalarFixture):
    slug = 'capless-ldo-1v0-20ma-pvt'
    nominal = ('tt', 1.8, 27)
    excursion = ('droop_v', 'w1max_v', 'bump_v', 'w2min_v')
    recovery = ('t1max_v', 't1min_v', 't2max_v', 't2min_v')

    def plan(self):
        s = self.source
        jobs = []
        for corner in s.CORNERS:
            for index in s.POINTS:
                point = (corner, s.SUPPLIES[index // len(s.TEMPERATURES)], s.TEMPERATURES[index % len(s.TEMPERATURES)])
                jobs.extend((bench, point, index) for bench in ('matrix', 'step'))
            jobs.extend(('psr', (corner, supply, 27), index) for index, supply in enumerate(s.SUPPLIES))
        jobs.extend(('start', (corner, supply, temperature), 0) for corner, temperature, supply in s.START_POINTS)
        return [{'id': bench + '__' + point_id(point), 'score_group': point_id(point),
                 'bench': bench, 'point': point, 'index': index} for bench, point, index in jobs]

    def deck(self, case, design, model):
        s = self.source
        text = (s.HERE / 'benches' / f'tb_{case["bench"]}.spi').read_text()
        corner, supply, temperature = case['point']
        substitutions = {f'.lib "{s.MODEL}" tt': f'.lib "{model}" {corner}',
                         '.include "/app/circuit.spi"': f'.include "{design}"'}
        if case['bench'] in ('matrix', 'step'):
            substitutions['set points = ( 0 1 2 3 4 5 )'] = f'set points = ( {case["index"]} )'
        elif case['bench'] == 'psr':
            substitutions['set points = ( 0 1 )'] = f'set points = ( {case["index"]} )'
        else:
            substitutions.update({'.param vfin=1.8': f'.param vfin={supply}', '.temp 27': f'.temp {temperature}'})
        for old, new in substitutions.items():
            if old not in text:
                raise ValueError(f'Original capless-LDO fixture lost expected input {old!r}')
            text = text.replace(old, new)
        if self.reference and case['bench'] == 'matrix' and tuple(case['point']) == self.nominal:
            self.reference_policy = s.submission_policy_failures(design.read_text())
        if text.splitlines()[0].lstrip().startswith('.'):
            text = '* Original capless LDO fixture; explicit ngspice title\n' + text
        return text, False

    def analyze(self, case, work, run):
        values = self.parse_measures((work / 'ngspice.log').read_text(errors='replace'))
        prefix = f'm{case["index"]}_'
        row = {'bench': case['bench'], 'point': tuple(case['point']),
               'name': f'{case["point"][0]}/{case["point"][1]:.1f}V/{case["point"][2]:+d}C',
               'supply': case['point'][1],
               **{k[len(prefix):]: v for k, v in values.items() if k.startswith(prefix)}}
        if self.reference and case['bench'] == 'matrix' and tuple(case['point']) == self.nominal:
            row['source_reference_device_policy_failures'] = getattr(self, 'reference_policy', ['reference policy evidence missing'])
        return row

    def checks(self, case, row):
        row = self.normalized(case, row)
        s = self.source
        if case['bench'] == 'matrix':
            checks = [s.dc_check([row], 1), s.iq_check([row], 1)]
            if self.reference and tuple(case['point']) == self.nominal:
                problems = row.get('source_reference_device_policy_failures', ['source policy evidence missing'])
                checks.append(('reference_device_policy', not problems, '; '.join(problems) or 'Original reference policy passed'))
            return check_rows(checks)
        if case['bench'] == 'psr':
            bounds = [('psr_1khz', 'psr1k_db', s.PSR_1K_DB_MIN[case['point'][1]]),
                      ('psr_100khz', 'psr100k_db', s.PSR_100K_DB_MIN),
                      ('psr_1mhz', 'psr1meg_db', s.PSR_1MEG_DB_MIN)]
            return check_rows([(name, field in row and row[field] >= bound,
                                f'Original source per-supply PSR lower bound {bound} dB') for name, field, bound in bounds])
        if case['bench'] == 'step':
            return check_rows([(name, all(m in row for m in fields) and
                                max(abs(row[m] - s.VOUT_TARGET) for m in fields) <= limit,
                                'Exact source absolute error predicate for all required extrema in this window')
                               for name, fields, limit in [('load_step_excursion', self.excursion, s.STEP_EXCURSION_V),
                                                           ('load_step_recovery', self.recovery, s.STEP_TAIL_TOL_V)]])
        complete = all(m in row for m in ('peak_v', 'smax_v', 'smin_v'))
        passed = complete and row['peak_v'] <= s.START_PEAK_V_MAX and max(abs(row[m] - s.VOUT_TARGET) for m in ('smax_v', 'smin_v')) <= s.START_TOL_V
        return check_rows([('startup', passed, 'Original source peak and 200..400 us tail-window constraints')])

    def original_suite_checks(self, rows, run_summary):
        s = self.source
        by = {bench: [r for r in rows if r['bench'] == bench] for bench in ('matrix', 'step', 'psr', 'start')}
        start = {r['name']: {'m0_' + k: r[k] for k in ('peak_v', 'smax_v', 'smin_v') if k in r} for r in by['start']}
        checks = [s.dc_check(by['matrix'], s.MATRIX), s.iq_check(by['matrix'], s.MATRIX),
                  s.psr_check_1k(by['psr']), s.psr_check_flat(by['psr'], 'psr100k_db', s.PSR_100K_DB_MIN, 'psr_100khz', '100kHz'),
                  s.psr_check_flat(by['psr'], 'psr1meg_db', s.PSR_1MEG_DB_MIN, 'psr_1mhz', '1MHz'),
                  s.step_excursion_check(by['step']), s.step_recovery_check(by['step']), s.start_check(start)]
        if self.reference:
            nominal = next((r for r in by['matrix'] if tuple(r['point']) == self.nominal), {})
            problems = nominal.get('source_reference_device_policy_failures', ['reference policy evidence missing'])
            checks.append(('reference_device_policy', not problems, '; '.join(problems) or 'Original reference policy passed'))
        return check_rows(checks)
