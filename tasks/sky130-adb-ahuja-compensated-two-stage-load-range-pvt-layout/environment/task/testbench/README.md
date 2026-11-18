[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These files come from this task's qualified pre-layout simulation fixtures,
using the current fixed circuit and its selected SKY130 model library. Each analysis has a
representative condition, not the complete PVT/load/seed matrix. The English
task instruction defines the full requirements.
The SPICE files state the supplies, stimuli, loads and analysis parameters.

## Model selection

The source fixture's continuous library lacks the fixed-width physical resistor
definitions used by this task: `sky130_fd_pr__res_high_po_1p41`.
These testbenches therefore use the native binned entry
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice`.
Use the supplied model path and task initialization. The current complete pre-layout
qualification applies to this entry; the continuous and binned electrical models
are not asserted to be equivalent.

## Files and conditions

| File | Analysis | Example condition | Extra ngspice arguments | Native output |
|---|---|---|---|---|
| [tb_light.spi](tb_light.spi) | `light` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_heavy.spi](tb_heavy.spi) | `heavy` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_step.spi](tb_step.spi) | `step` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_guard.spi](tb_guard.spi) | `guard` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_light.spi" work/sim-01/testbench.spi
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

The four native fixtures cover light-load AC (20 pF), heavy-load AC (200 pF), a follower step (200 pF), and the intermediate-load AC guard (63 pF). Measurements are printed in simulation.log. For the return-above-0-dB check, ngspice may report an out-of-interval/failed measurement for return_above_0db_hz when no rising 0 dB crossing exists; this expected absence only supports the guard after the AC analysis completes and the other required AC measurements are valid. A missing result from an aborted analysis is not evidence of stability. The step measures settling from each input 1% command crossing to the last 6 mV error-boundary crossing in 2–12 us or 12–20 us, and reports target errors at 12/20 us. Preserve the supplied binned model and scale=1e-6; older upstream examples used a different model/path and are not interchangeable with these fixtures.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_guard.spi`, `tb_heavy.spi`, `tb_light.spi`, `tb_step.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
