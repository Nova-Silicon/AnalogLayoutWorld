[English](README.md) | [简体中文](README.zh-CN.md)

# Native simulation testbenches

These fixtures retain the source AnalogDesignBench electrical testbenches, with
local model/DUT include paths. The redundant AC `print` of `.meas` results was
removed; the measurements, stimuli, analyses, and limits are unchanged.
Use the original continuous SKY130 library selected by `ALB_MODEL_LIB` and the
task initialization in `ALB_NGSPICE_INIT` for both pre-layout and post-layout runs.

| File | Default condition | Native outputs |
|---|---|---|
| `tb_ac_power.spi` | `tt`, 1.80 V, 27 C; AC 1–40 MHz and operating point | Gain, input current, and power in `simulation.log` |
| `tb_sfdr.spi` | `tt`, 1.80 V, 27 C; 1 MHz large-signal sine | `dynamic.dat` and a completion marker in `simulation.log` |

The full required matrix is five process corners (`tt`, `ff`, `ss`, `fs`, `sf`).
Run AC/DC once per corner and SFDR at 1, 11, and 41 MHz in each corner: 20 analyses.
Change only the `.lib` corner and `.param test_freq` for the other declared cases.
The fixed supply, bias, common-mode source, load, and measurement definition
are retained. The complete limits are in the task instruction.

## Run

From the workspace:

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_ac_power.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

For SFDR, use `tb_sfdr.spi` in a fresh run directory with the same DUT symlink and
initialization. Do not use `-n`, which skips initialization. The continuous models
in these decks accept the stated numeric device dimensions in micrometres;
do not silently add a geometry scale or replace the model library.

For post-layout simulation, point `dut.spice` to the PEX netlist and bind its
extracted subcircuit name and port order to the same fixture. Keep stimuli,
loads, and electrical connectivity unchanged.

## Measurements

The AC deck samples 1–40 MHz at 100 points per decade. `gain_min_vv` is the
minimum differential voltage gain over that sweep. It also reports gain at
1 MHz and 40 MHz and the differential input current at 40 MHz. DC power is
`abs(VDD*I(VDD)) + abs(VCM*I(VCM)) + abs(VIN*I(VIN)) + abs(VIP*I(VIP))`.

The transient runs to 50 us, with output saved from 40 us and a 1 ns maximum
step. Its `wrdata` output columns are time, VOP, time, VON.
Compute the differential waveform `VOP - VON`, select samples satisfying
`49 us <= time < 50 us`, then linearly interpolate onto 1000 points:
`49 us + k * 1 ns`, for `k=0..999`. At least 900 source samples are required.
Use the first or last pair for endpoint extrapolation when needed.

Apply a rectangular-window DFT to those 1000 values. The fundamental bin is
`round(frequency_hz * 1e-9 * 1000)`, i.e. 1, 11, or 41.
The amplitude at bin `b` is twice the magnitude of the complex DFT coefficient
divided by 1000. Search every bin from 1 through 500 except the fundamental for
the largest spur; DC is excluded. Then:

- Fundamental gain = fundamental amplitude / 0.8.
- SFDR = `20 * log10(fundamental amplitude / max(largest spur amplitude, 1e-30))`.

All source limits are strict inequalities. A zero simulator exit code alone does
not mean the SPEC has passed; every required finite measurement must be checked.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac_power.spi`, `tb_sfdr.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
