[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These files come from this task's qualified pre-layout simulation fixtures,
using the current fixed circuit and its selected SKY130 model library. Each analysis has a
representative condition, not the complete PVT/load/seed matrix. The English
task instruction defines the full requirements.
The SPICE files state the supplies, stimuli, loads and analysis parameters.

## Model selection

The source fixture's continuous library lacks the fixed-width physical resistor
definitions used by this task: `sky130_fd_pr__res_high_po_1p41`, `sky130_fd_pr__res_high_po_5p73`, `sky130_fd_pr__res_xhigh_po_0p35`.
These testbenches therefore use the native binned entry
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice`.
Use the supplied model path and task initialization. The current complete pre-layout
qualification applies to this entry; the continuous and binned electrical models
are not asserted to be equivalent.

## Files and conditions

| File | Analysis | Example condition | Extra ngspice arguments | Native output |
|---|---|---|---|---|
| [tb_matrix.spi](tb_matrix.spi) | `matrix` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_step.spi](tb_step.spi) | `step` | `corner=tt; supply_V=1.8; temperature_C=27` | — | `step_{$prefix}.csv` |
| [tb_psr.spi](tb_psr.spi) | `psr` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_start.spi](tb_start.spi) | `start` | `corner=tt; supply_V=1.8; temperature_C=27` | — | `start_m0.csv` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_matrix.spi" work/sim-01/testbench.spi
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


- `tb_matrix.spi`: Native m4_* measurements report the no-load quiescent current (operating point from a transient power-up) and the output window over 0-20 mA at TT/1.8 V/27 C. The window is measured on a slow quasi-static transient load ramp (0 -> 20 mA over 2 ms after a 20 us no-load hold), not a DC sweep; `m4_iload_end_a` is the measured load at the end of the ramp.

- `tb_step.spi`: Native m4_* extrema measure both load-step excursions and both recovery windows around the 1 V target. step_m4.csv contains v(vout) versus time.

- `tb_psr.spi`: Native m1_* measurements report supply rejection at 1 kHz, 100 kHz and 1 MHz for 1.8 V supply; preserve the original injection and load.

- `tb_start.spi`: Native m0_* measurements report startup peak and final 200..400 us output extrema. start_m0.csv contains v(vout) versus time.

- Load and operating points: the output load is drawn by a test-bench NMOS cascode current mirror (`XTBLD_*`), whose ideal reference current `ILOAD` is the commanded load; `i(VLMEAS)` is the current actually drawn from `vout`. A transistor mirror cannot pull `vout` below ground. In these load decks every operating point, including the initial point of each transient, comes from a transient power-up (`optran 0 0 0 <tstep> <tstop> 0`: no Newton/gmin/source-stepping DC attempt), so the analyses start from the steady state the circuit physically reaches. Keep these load and `optran` lines for post-layout simulation.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_matrix.spi`, `tb_psr.spi`, `tb_start.spi`, `tb_step.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
