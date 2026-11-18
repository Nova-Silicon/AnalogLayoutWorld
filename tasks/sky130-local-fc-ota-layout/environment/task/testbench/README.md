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
| [tb_ac.spi](tb_ac.spi) | `ac` | `corner=tt; VDD_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_follower.spi](tb_follower.spi) | `follower` | `corner=tt; VDD_V=1.8; temperature_C=27` | — | simulation.log |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_ac.spi" work/sim-01/testbench.spi
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

The AC bench prints the operating point and measures gain_dc at 1 Hz, ugb at the first falling 0 dB crossing and phase_ugb using continuous phase. Phase margin is phase_ugb + 180 degrees; quiescent power is -VDD times the printed I(VDD), including the external 10 uA reference branch. The follower bench directly measures output samples, extrema and transition durations. For the 0.8–1.0 V command, compare samples at 1.5/3.5 us to 1.0/0.8 V, divide 0.16 V by the measured 0.82–0.98 V rise/fall duration, and use the extrema over 1–3/3–5 us. Both fixtures use the specified 2 pF load; the AC DC-only feedback fixture is not part of the layout.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac.spi`, `tb_follower.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
