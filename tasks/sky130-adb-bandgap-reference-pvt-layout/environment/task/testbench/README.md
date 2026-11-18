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
| [tb_op.spi](tb_op.spi) | `op` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup.spi](tb_startup.spi) | `startup` | `corner=tt; vdd=1.8; temp_c=27; ramp_s=1e-06` | `-r analysis.raw` | `analysis.raw` |
| [tb_ac.spi](tb_ac.spi) | `ac` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_step.spi](tb_line_step.spi) | `line_step` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=mc; vdd=1.8; temp_c=27; seed=61000` | `-r analysis.raw` | `analysis.raw` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_op.spi" work/sim-01/testbench.spi
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


- `tb_op.spi`: Read VREF and supply current from the operating-point raw plot; power is max(0,-VDD*I(VDD)). Temperature coefficient and line regulation require the complete temperature/supply sweeps, not one OP.

- `tb_startup.spi`: Raw transient: evaluate the declared post-ramp voltage window, peak voltage/current and integrate supply power for startup energy.

- `tb_ac.spi`: Raw AC VREF response to the unit supply perturbation; take the maximum transfer magnitude over the specified band.

- `tb_noise.spi`: Integrate the squared output-noise spectral density over the specified band and take its square root.

- `tb_line_step.spi`: Raw transient: measure VREF excursion and final-in-band settling after each supply step, using the matching operating-point target.

- `tb_mc.spi`: One process/mismatch OP sample prints no aggregate yield. Retain the seed and VREF; yield and sample sigma need all 30 original seeds.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac.spi`, `tb_line_step.spi`, `tb_noise.spi`, `tb_op.spi`, `tb_startup.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
