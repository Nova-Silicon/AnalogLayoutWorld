[English](README.md) | [简体中文](README.zh-CN.md)

# Native bandgap simulation examples

The English version is authoritative.

These are ordinary ngspice decks for the fixed DUT. `tb_temperature.spi`
demonstrates a complete −40–125 °C temperature sweep at `tt`, VDD=1.8 V.
`tb_startup.spi` demonstrates startup at `tt`, 27 °C, VDD=1.8 V. Both use
10 pF and 100 MΩ external loads. The task instruction specifies the full
27-sweep and 53-startup matrix and all limits.

## Run a reference simulation

From the workspace:

```bash
source ./eda_env.sh
mkdir -p work/sim-temperature
cp "$ALB_TASK_DIR/testbench/tb_temperature.spi" work/sim-temperature/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-temperature/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-temperature/.spiceinit
(
    cd work/sim-temperature
    SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

For startup, use a fresh working directory and copy `tb_startup.spi` instead.
The decks select the continuous model library under
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/combined/continuous/`.
Keep `set ngbehavior=hsa`, `set num_threads=1` and `.option scale=1e-6`.
Do not use `ngspice -n`, which suppresses the initialization file.

For the other required conditions, select the corner in `.lib` and set the
supply value. The temperature-sweep deck must still cover all 34 points in
5 °C increments. For startup, set `.temp` and the target voltage in the
`alter @VDD[pwl]` command while preserving its 10 µs ramp and 2 ms duration.

## Read the native outputs

`simulation.log` contains ngspice messages and scalar `.meas` results.

- Temperature: `ref_min`, `ref_max` and `ref_25` are voltage measurements.
  `temp_curve.dat` has four numeric columns: temperature, Vref, temperature
  again, and I(VDD). Confirm all 34 finite rows at −40, −35, …, 125 °C.
  Calculate box temperature coefficient as
  `(max(Vref) − min(Vref)) / Vref(25 °C) / 165 × 10^6` ppm/K.
  Quiescent current is `max(−I(VDD))` over these same rows. The current sign
  follows the supply source orientation in the deck.
- Startup: `ref_end` measures Vref at 1 ms; `ref_min_steady` and
  `ref_max_steady` measure its extrema from 1 to 2 ms.
  All must lie in the task's voltage window. The names containing `steady`
  refer to that measurement window, not an additional complete-settling
  requirement. `ref_start` at 1 µs is a diagnostic value, not another target.
  `startup.dat` contains time and Vref for inspecting the transient.

Missing measurements, non-finite values or incomplete sweeps are not successful
checks.

## Simulate the extracted DUT

In a fresh working directory, link or copy the native extracted netlist as
`dut.spice`. Set the `XDUT` subcircuit name and port order to match its actual
`.subckt` declaration; the reference uses `bandgap vdd vss vref`.
Keep the specified external stimuli and loads. Preserve extracted parasitic
elements and device geometry.

Each example contains this native SPICE model binding:

```spice
.subckt sky130_fd_pr__res_high_po_0p35 p n b l=1 mult=1
XR p n b sky130_fd_pr__res_high_po w=0.35 l={l} mult={mult}
.ends sky130_fd_pr__res_high_po_0p35
```

The original schematic uses the continuous model
`sky130_fd_pr__res_high_po` with explicit W=0.35 µm. Native extraction names
that physical width as `sky130_fd_pr__res_high_po_0p35`. The binding supplies
that fixed width to the original continuous model and passes through the
actual extracted length, statistical `mult` parameter and three terminals.
An instance's parallel `m` multiplier remains on that instance. Keep all
other extracted devices and parasitics unchanged.

The binding is unused when the original `circuit.spice` is simulated. For
post-layout simulation it does not substitute a schematic length, a nominal
resistance or a different resistor width. Do not replace the continuous
library with the binned library, or use `lvs_reference.spice` for simulation.

## Evaluation coverage in this release

The complete task SPEC, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_startup.spi`, `tb_temperature.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
