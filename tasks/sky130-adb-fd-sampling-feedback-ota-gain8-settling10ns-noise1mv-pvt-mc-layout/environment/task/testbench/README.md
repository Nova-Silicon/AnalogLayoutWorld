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
| [tb_loop.spi](tb_loop.spi) | `loop` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_ranges.spi](tb_ranges.spi) | `ranges` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_cmfb_recovery.spi](tb_cmfb_recovery.spi) | `cmfb_recovery` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=tt; supply_V=1.8; temperature_C=27; seed=41000` | — | simulation.log |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_loop.spi" work/sim-01/testbench.spi
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


- `tb_loop.spi`: Native scalars include loop gain/UGB/phase margin, closed-loop differential gain, output common-mode error and power.

- `tb_settling.spi`: Native transient measures/let expressions print static/dynamic errors and both settling times; retain the task-specific tolerance and timing windows.

- `tb_noise.spi`: Native noise analysis prints integrated differential output_noise_vrms.

- `tb_ranges.spi`: Native DC sweep derives differential output range from the local-gain drop criterion. Gain1 source requires nominal range only; Gain8 requires ranges at all 30 PVT points.

- `tb_cmfb_recovery.spi`: Native transient measures common-mode static error, peak deviation and residual errors at specified recovery times.

- `tb_mc.spi`: Native scalars are common-mode and supply feedthrough gains at 10Hz. CMRR/PSRR equal the nominal loop fixture closed-loop differential gain minus each feedthrough gain in dB; all 20 original seeds are needed.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_cmfb_recovery.spi`, `tb_loop.spi`, `tb_noise.spi`, `tb_ranges.spi`, `tb_settling.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
