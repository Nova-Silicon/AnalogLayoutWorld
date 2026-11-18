[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These files come from this task's qualified pre-layout simulation fixtures,
using the current fixed circuit and its selected SKY130 model library. Each analysis has a
representative condition, not the complete PVT/load/seed matrix. The English
task instruction defines the full requirements.
The SPICE files state the supplies, stimuli, loads and analysis parameters.

## Model selection

The earlier standalone fixture used a benchmark-authored alias because the continuous
library lacks `sky130_fd_pr__res_xhigh_po_1p41`. That alias was not an official SKY130 model.
These testbenches instead load the native definition through
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice`.
Use the model path and initialization already supplied in this task. The current
complete pre-layout qualification applies to this native binned entry; it does
not establish electrical equivalence to the earlier continuous-plus-alias model.

## Files and conditions

| File | Analysis | Example condition | Extra ngspice arguments | Native output |
|---|---|---|---|---|
| [tb_rc_osc.spi](tb_rc_osc.spi) | `rc_osc` | `corner=tt; supply_V=1.8; temperature_C=27` | — | `wave.tsv` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_rc_osc.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

Use `ALB_NGSPICE_INIT` from this task's `eda_env.sh`; do not universally add or
remove `ngbehavior=hsa`. Each deck already specifies its qualified model path,
geometry scaling, and stimuli. Do not use `-n`, which skips initialization.
The run directory's `dut.spice` is the circuit under test.

For post-layout simulation, point `dut.spice` to the PEX netlist. Adjust the DUT
instance to the extracted `.subckt` name and port order. Only adapt the name and
port order; do not change electrical connectivity, stimuli, loads, or limits to
manufacture a pass. See the workspace's `GUIDE.md` for the native PEX procedure.

`.meas` and `print` results appear in `simulation.log`; `wrdata`, `write` and
`-r` waveform outputs appear in the run directory. Some metrics require waveform
analysis using the task's measurement definitions. A zero ngspice exit code does
not establish SPEC compliance. A single MC seed does not establish the specified
mismatch statistics. Set the remaining PVT, loads, common modes and seeds according
to the complete task instruction.

## Measurement notes

The transient bench writes wave.tsv with time, enable voltage, output voltage and I(VDD); it does not print the derived oscillator metrics. Retain the complete 6 ms waveform. Interpolate output crossings at VDD/2: use rising edges strictly between 1 and 2.5 ms for frequency = 1/median(period), period variation = (maximum period - minimum period)/mean(period), and each period's high-time fraction. Startup and restart are the first subsequent rising edges relative to 100.01 us and 4.00001 ms respectively. Enabled power is -VDD times the time-averaged supply current over the sampled 1–2.5 ms window; disabled current is minus the sample mean of I(VDD), and disabled output is its maximum voltage, over 3.3–3.8 ms. Read the raw waveform and compute these quantities using the task definitions; no pass/fail decision is emitted by this bench.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_rc_osc.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
