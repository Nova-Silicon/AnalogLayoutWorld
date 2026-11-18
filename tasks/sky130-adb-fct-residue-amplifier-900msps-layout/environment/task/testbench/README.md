[English](README.md) | [简体中文](README.zh-CN.md)

# Native FCT simulation fixtures

These two TT examples preserve AnalogDesignBench's original final-signoff
fixture, clock timing, measurement statements, and loads. The original
`fct_fixture.spi` and `samples_32.inc` are included inline so each deck can
run as a standalone native SPICE file.

| File | Input | Conditions |
|---|---|---|
| `tb_10mv_tt.spi` | 10 mV differential peak, FFT bin 5 | TT, 1.8 V, 27 C |
| `tb_20mv_tt.spi` | 20 mV differential peak, FFT bin 3 | TT, 1.8 V, 27 C |

Both use 900 MS/s, 64 startup cycles, and 32 scored held samples. For the full
specification, run each amplitude at `tt`, `ss`, `ff`, `fs`, and `sf` by
changing only the `.lib` corner. Keep the continuous model library and its
micrometre geometry convention. Its `models_global.spice` already sets
`.option scale=1.0u`; no additional scale option is needed in these decks.

From the workspace:

```bash
source ./eda_env.sh
mkdir -p work/fct-10mv-tt
cp "$ALB_TASK_DIR/testbench/tb_10mv_tt.spi" work/fct-10mv-tt/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/fct-10mv-tt/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/fct-10mv-tt/.spiceinit
(
  cd work/fct-10mv-tt
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

Use a fresh directory for each run. The source DUT uses the fixed physical MIM
capacitors from `task/circuit.spice`. For post-layout simulation, point
`dut.spice` to the PEX netlist and adapt only the DUT subcircuit name and port
order if needed. Do not change stimuli, loads, connections, or limits to
manufacture a pass.

The log provides `outp_NNN`, `outn_NNN` held samples,
`outp_early_NNN`, `outn_early_NNN` tracking samples (NNN=000..031), and `power_w`.
Use the gain, SFDR, common-mode, range, hold-movement, and power definitions
in the task instructions. All 129 required raw values must be finite and
present; an exit code of zero does not establish SPEC compliance. No
256-point FFT or extra warmup is required. Fixture ideal switches/capacitors
are external test conditions and must not be laid out as part of the DUT.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_10mv_tt.spi`, `tb_20mv_tt.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
