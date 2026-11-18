[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These files come from this task's qualified pre-layout simulation fixtures,
using the current fixed circuit and its selected SKY130 model library. Each analysis has a
representative condition, not the complete PVT/load/seed matrix. The English
task instruction defines the full requirements.
The SPICE files state the supplies, stimuli, loads and analysis parameters.

## Model selection

The source fixture's continuous library lacks the fixed-width physical resistor
definitions used by this task: `sky130_fd_pr__res_high_po_1p41`, `sky130_fd_pr__res_high_po_5p73`.
These testbenches therefore use the native binned entry
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice`.
Use the supplied model path and task initialization. The current complete pre-layout
qualification applies to this entry; the continuous and binned electrical models
are not asserted to be equivalent.

## Files and conditions

| File | Analysis | Example condition | Extra ngspice arguments | Native output |
|---|---|---|---|---|
| [tb_op_ac.spi](tb_op_ac.spi) | `op_ac` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_psrr.spi](tb_psrr.spi) | `psrr` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_cmrr.spi](tb_cmrr.spi) | `cmrr` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_swing.spi](tb_swing.spi) | `swing` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_slew.spi](tb_slew.spi) | `slew` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_op_ac.spi" work/sim-01/testbench.spi
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


- `tb_op_ac.spi`: Native OP/AC measurements report gain, unity-gain bandwidth, phase margin and supply power.

- `tb_noise.spi`: Native noise measurement reports integrated input-referred noise over the frequency range in the file.

- `tb_psrr.spi`: Native supply injection reports supply rejection at the frequency points in the file.

- `tb_cmrr.spi`: Native common-mode input injection reports common-mode rejection at the frequency points in the file.

- `tb_swing.spi`: Native DC sweep measurements report closed-loop output swing and tracking.

- `tb_settling.spi`: Native transient measurements report step settling and final error using the command and measurement windows in the file.

- `tb_slew.spi`: Native large-signal transient measurements report positive and negative slew behavior.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_cmrr.spi`, `tb_noise.spi`, `tb_op_ac.spi`, `tb_psrr.spi`, `tb_settling.spi`, `tb_slew.spi`, `tb_swing.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
