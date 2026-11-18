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
| [tb_op_ac.spi](tb_op_ac.spi) | `op_ac` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vdd=1.8; temp_c=27` | — | simulation.log |
| [tb_range.spi](tb_range.spi) | `range` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |

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


- `tb_op_ac.spi`: From analysis.raw use return ratio -v(vout)/v(vinn). Gain is evaluated at 10 Hz; bandwidth is the first falling 0 dB crossing and phase margin uses unwrapped phase there. OP output offset is relative to 0.9 V; power is -VDD*i(vdd).

- `tb_noise.spi`: Native noise measurement reports integrated input-referred noise over the frequency range in the file.

- `tb_range.spi`: Read command v(vinp) and v(vout) from the native121-point DC sweep. Tracking error is abs(Vout-command); determine the largest continuous tracking interval with interpolation at its error-band boundaries.

- `tb_settling.spi`: Read time, v(vinp) and v(vout) from analysis.raw. Evaluate rising and falling transitions separately: last entry into the specified error band within each original window, and static error from the final5 ns of that window.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_noise.spi`, `tb_op_ac.spi`, `tb_range.spi`, `tb_settling.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
