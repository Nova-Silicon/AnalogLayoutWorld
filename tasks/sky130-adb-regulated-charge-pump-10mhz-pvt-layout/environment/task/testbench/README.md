[English](README.md) | [简体中文](README.zh-CN.md)

# Native charge-pump testbench

`tb_charge_pump_regulated_ff_hot.spi` is the original ADB public electrical
diagnostic. Its circuit, sources, load, analysis, and measurement interval are
preserved. The file changes only local paths, adds an explicit title and geometry
scale, and includes a static SPICE binding for the extracted 0.69 µm resistor name.
The fixed DUT netlist remains unchanged.

| Analysis | Conditions | Measurements |
|---|---|---|
| One two-instance transient | FF, 1.98 V, 125°C; 10 MHz; 200 µs | Enabled 50 µA-load output and supply current; unloaded disabled-instance supply current; final 190–200 µs |

## Run

From the workspace:

```bash
source ./eda_env.sh
mkdir -p work/pump-sim
cp "$ALB_TASK_DIR/testbench/tb_charge_pump_regulated_ff_hot.spi" work/pump-sim/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/pump-sim/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/pump-sim/.spiceinit
(
  cd work/pump-sim
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

Use a new output directory for each run. This test uses the original continuous
model library, `.option scale=1e-6`, and `set num_threads=1`; it does not enable
`ngbehavior=hsa`. The `.measure` results are written to `simulation.log`.
Do not pass `-r`: ngspice may then skip the transient `.measure` evaluations.

For post-layout simulation, link `dut.spice` to the extracted DUT and adapt only
the instance name/pin ordering if the extractor uses a different interface.
The testbench contains `sky130_fd_pr__res_xhigh_po_0p69`, a three-terminal wrapper
that passes the actual extracted length and fixed width 0.69 µm to the original
continuous `sky130_fd_pr__res_xhigh_po` model. It does not replace the circuit's
resistors, alter their extracted dimensions, or modify a PDK model.

## Selected measurements

| Scalar | This release's limit |
|---|---|
| `vout_en_avg` | 2.4453–2.7027 V |
| `ripple_vpp` | 0–5 mVpp |
| `abs(i_avdd_en_avg)` | ≤200 µA |
| `abs(i_avdd_pd_avg)` | ≤100 nA in this public clock-running transient |

The complete original SPEC remains in `instruction.md`. Its original disabled
current is a static/DC measurement with the clock held low; the public bench
instead runs a clock on the disabled instance. Its enabled FF/1.98 V/125°C/50 µA
stress point is outside the original eight enabled signoff points. This release
checks the numerical limits above on this public fixture and does not infer the
unmeasured DC/PVT results. Private post-layout grading uses the same public
stimuli, analysis, model, initialization, and limits with the extracted DUT.
