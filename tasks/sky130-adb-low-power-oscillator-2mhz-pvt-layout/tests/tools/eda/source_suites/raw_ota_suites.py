"""Raw-waveform OTAs with original row-schema and case predicates."""
from pathlib import Path

from .basic import Telescopic
from .bounded_times import adapt_timing_sentinels


class FoldedCascode(Telescopic):
    slug = 'folded-cascode-ota-gain130-pm60-noise50uv-pvt'

    def deck(self, case, design, model):
        text = (Path(self.source.__file__).parent / 'benches' / case['bench']).read_text()
        return self.source.instantiate(text, model, design, self.source.point_key(case)), case['group'] != 'noise'

    def analyze(self, case, work, run):
        group = case['group']
        if group == 'noise':
            values = self.source.parse_measures((work / 'ngspice.log').read_text(errors='replace'))
            if 'input_noise_vrms' not in values:
                raise ValueError('Missing original finite integrated noise measurement')
            metrics = {'input_noise_vrms': values['input_noise_vrms']}
        else:
            plots = self.source.parse_raw(work / 'analysis.raw')
            if group == 'op_ac':
                metrics = {**self.source.ac_metrics(self.source.plot(plots, 'AC Analysis')),
                           **self.source.op_metrics(self.source.plot(plots, 'Operating Point'), case['vdd'])}
            elif group == 'range':
                metrics = self.source.range_metrics(self.source.plot(plots, 'DC transfer characteristic'))
            elif group == 'settling':
                tran = self.source.plot(plots, 'Transient Analysis')
                metrics = self.source.settling_metrics(tran)
                metrics = adapt_timing_sentinels(self.source, case, tran, run, metrics)
            else:
                raise ValueError('Unknown original folded-cascode analysis')
        return {**{k: case[k] for k in ('group', 'bench', 'corner', 'vdd', 'temp_c')},
                **metrics, 'run_time_s': run['wall_seconds']}
