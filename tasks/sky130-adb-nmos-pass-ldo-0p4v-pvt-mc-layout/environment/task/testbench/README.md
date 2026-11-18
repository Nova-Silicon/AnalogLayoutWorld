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
| [tb_pvt.spi](tb_pvt.spi) | `pvt` | `corner=tt; supply_V=1.8; temperature_C=27; load=0.001` | — | simulation.log |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=tt; supply_V=1.8; temperature_C=27; seed=12345` | — | simulation.log |

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


- `tb_pvt.spi`: Native scalar OP/loop/PSRR measurements plus active-MOS headroom margins. The latter require parsing the original printed device margins, not only VOUT. Quiescent current subtracts the measured load `load_current_a = i(VLMEAS)`; the test-bench mirror transistors `XTBLD_*` are not DUT devices and are excluded from the headroom check.

- `tb_mc.spi`: Each seed produces 1mA and 5mA VOUT samples. Mean ± 3*sample-standard-deviation is computed separately for each load across all original seeds.

- Load and operating points: the output load is drawn by a test-bench NMOS low-voltage cascode current mirror (cascode gates held 0.2 V above the reference gate by `ETBLD`/`VTBLD`) (`XTBLD_*`), whose ideal reference current `ILOAD` is the commanded load; `i(VLMEAS)` is the current actually drawn from `vout`. A transistor mirror cannot pull `vout` below ground. In these load decks every operating point, including the initial point of each transient, comes from a transient power-up (`optran 0 0 0 <tstep> <tstop> 0`: no Newton/gmin/source-stepping DC attempt), so the analyses start from the steady state the circuit physically reaches. Keep these load and `optran` lines for post-layout simulation.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_pvt.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
