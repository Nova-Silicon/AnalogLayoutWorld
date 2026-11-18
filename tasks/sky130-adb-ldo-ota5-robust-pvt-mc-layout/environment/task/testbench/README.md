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
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_pvt_dc.spi](tb_pvt_dc.spi) | `pvt_dc` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw`, `result.raw` |
| [tb_dropout_pvt.spi](tb_dropout_pvt.spi) | `dropout_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.03` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_nominal.spi](tb_loop_nominal.spi) | `loop_nominal` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_pvt.spi](tb_loop_pvt.spi) | `loop_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_output_network.spi](tb_loop_output_network.spi) | `loop_output_network` | `corner=tt; vin=1.8; temp=27; cap=8e-07; esr=0.02; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_psrr_nominal.spi](tb_psrr_nominal.spi) | `psrr_nominal` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_psrr_pvt.spi](tb_psrr_pvt.spi) | `psrr_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.03` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup_dynamic.spi](tb_startup_dynamic.spi) | `startup_dynamic` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_load_tran_dynamic.spi](tb_load_tran_dynamic.spi) | `load_tran_dynamic` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_tran_dynamic.spi](tb_line_tran_dynamic.spi) | `line_tran_dynamic` | `corner=tt; vin=1.98; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup_output_network.spi](tb_startup_output_network.spi) | `startup_output_network` | `corner=ss; vin=1.62; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_load_tran_output_network.spi](tb_load_tran_output_network.spi) | `load_tran_output_network` | `corner=ss; vin=1.62; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_tran_output_network.spi](tb_line_tran_output_network.spi) | `line_tran_output_network` | `corner=ss; vin=1.98; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=mc; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01; seed=72000` | `-r analysis.raw` | `analysis.raw` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_noise.spi" work/sim-01/testbench.spi
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


- `tb_noise.spi`: Raw noise plot: integrate the output-noise density over the declared band.

- `tb_pvt_dc.spi`: Important: the native control block writes/appends nine single operating-point plots (load-major: 1, 10, 30 mA x VIN 1.62, 1.8, 1.98 V) to result.raw, not analysis.raw. Each point comes from its own transient power-up, not a DC sweep. Quiescent current is `abs(i(@vin[i])) - i(vlmeas)`, i.e. it subtracts the measured load.

- `tb_dropout_pvt.spi`: Raw slow transient VIN ramp (1.15 -> 1.8 V over 10 ms, quasi-static) instead of a DC sweep: interpolate the supply at the stated output-error boundary to obtain dropout at the fixed load.

- `tb_loop_nominal.spi`: Middlebrook double injection at the gate_drive/gate break: the control block appends two AC plots to analysis.raw, first VLOOP ac=1 with IINJ ac=0, then VLOOP ac=0 with IINJ ac=1 (1 A into gate). Take Tv = -v(gate_drive)/v(gate) from the first plot and Ti = -i(vloop)/(i(vloop)+1) from the second; the loop gain is T = (Tv*Ti-1)/(Tv+Ti+2). Derive low-frequency gain, first unity crossing, phase margin and UGB from T. Voltage injection alone is not used because the OTA output impedance is not small compared with the pass-device gate impedance near crossover, which would overstate phase margin. Keep load/COUT/ESR case values.

- `tb_loop_pvt.spi`: Middlebrook double injection at the gate_drive/gate break: the control block appends two AC plots to analysis.raw, first VLOOP ac=1 with IINJ ac=0, then VLOOP ac=0 with IINJ ac=1 (1 A into gate). Take Tv = -v(gate_drive)/v(gate) from the first plot and Ti = -i(vloop)/(i(vloop)+1) from the second; the loop gain is T = (Tv*Ti-1)/(Tv+Ti+2). Derive low-frequency gain, first unity crossing, phase margin and UGB from T. Voltage injection alone is not used because the OTA output impedance is not small compared with the pass-device gate impedance near crossover, which would overstate phase margin. Keep load/COUT/ESR case values.

- `tb_loop_output_network.spi`: Middlebrook double injection at the gate_drive/gate break: the control block appends two AC plots to analysis.raw, first VLOOP ac=1 with IINJ ac=0, then VLOOP ac=0 with IINJ ac=1 (1 A into gate). Take Tv = -v(gate_drive)/v(gate) from the first plot and Ti = -i(vloop)/(i(vloop)+1) from the second; the loop gain is T = (Tv*Ti-1)/(Tv+Ti+2). Derive low-frequency gain, first unity crossing, phase margin and UGB from T. Voltage injection alone is not used because the OTA output impedance is not small compared with the pass-device gate impedance near crossover, which would overstate phase margin. Keep load/COUT/ESR case values.

- `tb_psrr_nominal.spi`: Raw VIN/VOUT AC response: calculate rejection at 100Hz, 1kHz, 100kHz and 1MHz.

- `tb_psrr_pvt.spi`: Raw VIN/VOUT AC response: calculate rejection at 100Hz, 1kHz, 100kHz and 1MHz.

- `tb_startup_dynamic.spi`: Raw transient: t90, post-ramp settling and overshoot with the declared output network.

- `tb_load_tran_dynamic.spi`: Raw VOUT transient: excursion and final settling after specified load-current edges.

- `tb_line_tran_dynamic.spi`: Raw VIN/VOUT transient: excursion and final settling after supply steps. Some group labels retain the high supply; use the actual piecewise supply in the rendered deck.

- `tb_startup_output_network.spi`: Raw transient: t90, post-ramp settling and overshoot with the declared output network.

- `tb_load_tran_output_network.spi`: Raw VOUT transient: excursion and final settling after specified load-current edges.

- `tb_line_tran_output_network.spi`: Raw VIN/VOUT transient: excursion and final settling after supply steps. Some group labels retain the high supply; use the actual piecewise supply in the rendered deck.

- `tb_mc.spi`: One mismatch OP sample gives VOUT; aggregate output-voltage yield requires the complete original seed set.

- Load and operating points: the output load is drawn by a test-bench NMOS cascode current mirror (`XTBLD_*`), whose ideal reference current `ILOAD` is the commanded load; `i(VLMEAS)` is the current actually drawn from `vout`. A transistor mirror cannot pull `vout` below ground. In these load decks every operating point, including the initial point of each transient, comes from a transient power-up (`optran 0 0 0 <tstep> <tstop> 0`: no Newton/gmin/source-stepping DC attempt), so the analyses start from the steady state the circuit physically reaches. Keep these load and `optran` lines for post-layout simulation.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_dropout_pvt.spi`, `tb_line_tran_dynamic.spi`, `tb_line_tran_output_network.spi`, `tb_load_tran_dynamic.spi`, `tb_load_tran_output_network.spi`, `tb_loop_nominal.spi`, `tb_loop_output_network.spi`, `tb_loop_pvt.spi`, `tb_noise.spi`, `tb_psrr_nominal.spi`, `tb_psrr_pvt.spi`, `tb_pvt_dc.spi`, `tb_startup_dynamic.spi`, `tb_startup_output_network.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
