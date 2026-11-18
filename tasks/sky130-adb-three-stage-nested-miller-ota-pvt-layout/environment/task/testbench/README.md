[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These files come from this task's qualified pre-layout simulation fixtures,
using the current fixed circuit and its selected SKY130 model library. Each analysis has a
representative condition, not the complete PVT/load/seed matrix. The English
task instruction defines the full requirements.
The SPICE files state the supplies, stimuli, loads and analysis parameters.

## Files and conditions

| File | Analysis | Example condition | Extra ngspice arguments | Native output |
|---|---|---|---|---|
| [tb_pvt.spi](tb_pvt.spi) | `pvt` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_input_bias.spi](tb_input_bias.spi) | `input_bias` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_swing.spi](tb_swing.spi) | `swing` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_slew.spi](tb_slew.spi) | `slew` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_pvt.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -r analysis.raw -o simulation.log testbench.spi
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


- `tb_pvt.spi`: Raw OP/AC plots yield DC gain, UGB, phase margin, output common-mode error, power and the specified drive FoM.

- `tb_input_bias.spi`: Read absolute input-source currents from the OP raw plot.

- `tb_swing.spi`: Raw follower DC sweep: obtain the contiguous valid output interval using the source error criterion.

- `tb_settling.spi`: Raw transient: determine the final-in-band settling time and error fraction with the source command targets/windows.

- `tb_slew.spi`: Raw transient: determine rising/falling slew rates from the original threshold-crossing definitions.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_pvt.spi`, `tb_settling.spi`, `tb_slew.spi`, `tb_swing.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
`tb_input_bias.spi` is retained as a diagnostic fixture. Its MOS-gate DC input-current check is identically zero in this model and is excluded from post-layout scoring.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
