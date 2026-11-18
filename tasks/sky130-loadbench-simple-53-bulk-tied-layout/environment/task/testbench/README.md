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
| [tb_source_combined.spi](tb_source_combined.spi) | `source_combined` | `corner=tt; temperature_C=27` | — | `result_op.raw`, `result_dc.raw`, `result_ac_vtran.raw`, `result_ac_vdd.raw`, `result_ac_vdc.raw`, `result_dc_vout.raw`, `result_tran.raw` |
| [tb_closed_loop_step.spi](tb_closed_loop_step.spi) | `closed_loop_step` | `corner=tt; temperature_C=27` | — | `transient.tsv` |

## Run

Run this example from the workspace. Use a new directory for each simulation to
avoid overwriting measurements or waveforms. When selecting another testbench,
use the table to decide whether `-r analysis.raw` is required.

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_source_combined.spi" work/sim-01/testbench.spi
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

The combined bench writes result_op.raw, result_dc.raw, result_ac_vtran.raw, result_ac_vdd.raw, result_ac_vdc.raw, result_dc_vout.raw and result_tran.raw. Some intermediate measurements are printed, but the source definitions derive the final AC metrics from raw samples: 1 Hz gain; linear interpolation around 0 dB for unity-gain frequency and phase; phase referenced to the first AC sample before unwrapping; CMRR/PSRR = differential gain at 10 Hz minus the respective DC .tf gain. Power and offset use the unity-follower operating point; DC range limits use the crossing definitions in the task instruction. The separate step bench writes transient.tsv (time, input, output); compute the maximum absolute tracking error in each of 4–4.9, 9–9.9, 14–14.9 and 19–19.9 us, then take the largest. Preserve this bench's supplied initialization and model/scale settings rather than replacing them with another task's defaults. The files provide raw analyses, not an automatic SPEC verdict.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_closed_loop_step.spi`, `tb_source_combined.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
