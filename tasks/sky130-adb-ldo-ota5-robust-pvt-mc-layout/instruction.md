[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a Robust PMOS-Pass LDO Across PVT and Mismatch

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `ldo_ota5`, with ports in this order:
`vin vout vss vref ibias fb gate_drive gate`.
Preserve the circuit topology, device models, connections, dimensions, and declared
multiplicity parameters. External test sources, loads, clocks, and any
explicitly described package fixtures are not part of the DUT layout.
`gate_drive` is the error-amplifier output and `gate` is the pass-device gate.
The external bench inserts the loop-injection source between them; do not short them inside the DUT.

The layout must pass DRC and LVS using the installed SKY130 decks and meet the
following electrical specifications after parasitic extraction. Maximize area
utilization through compact placement and routing without compromising process
or electrical requirements.

## Execution budget and layout objectives

You have **3 hours (10800 seconds) of wall-clock Agent execution time** for
layout generation, debugging and self-checks. Plan your work within this budget
and save the required deliverables before it expires. The subsequent official
verification is outside this three-hour Agent budget.

Passing DRC, LVS and the post-layout simulation tests covered by this release
is a basic requirement. Within the fixed circuit constraints, maximize area
utilization by minimizing the total layout area through compact placement and
routing, without compromising process or electrical requirements. As appropriate
for the circuit, consider device matching and symmetry, parasitics and coupling
on sensitive nets, power and ground routing, body/well contacts and isolation.

## Spec

The testbench applies `vref=0.8 V`, sources 50 uA from `vin` into `ibias`, and connects an external 300 kohm/600 kohm feedback divider for a 1.2 V target. The nominal external output network is 1 uF with 50 milliohm ESR; stability and dynamic robustness also use 0.8 and 1.2 uF with 20 and 100 milliohm ESR. These ideal elements represent specified board-level components and are not part of the on-chip DUT.

DC signoff covers all 135 Cartesian combinations of tt, ff, ss, fs, sf; 1.62, 1.8, 1.98 V input; 1, 10, 30 mA load; and -40, 27, 125 C. The specified minimum load is 1 mA. At every point, `abs(vout-1.2 V)` must not exceed 20 mV. Quiescent input current, `abs(I(VIN))-ILOAD`, must not exceed 200 uA and must not be negative; `ILOAD` is the load current actually drawn from `vout` by the test-bench current mirror (measured, not the commanded value).

At 30 mA, input voltage is swept upward from 1.15 to 1.8 V at all five process corners and three temperatures. Dropout is the interpolated `VIN-VOUT` where `VOUT` first reaches and thereafter remains above 99% of 1.2 V; it must not exceed 250 mV.

Loop return ratio is measured at the `gate_drive`/`gate` break by Middlebrook double injection (series voltage injection plus shunt current injection into `gate`, combined into the true return ratio). Require loop gain at 1 Hz of at least 40 dB, phase margin of at least 60 degrees, and unity-gain bandwidth of at least 50 kHz. Coverage includes TT/27 C over all supplies and loads; the five representative process/temperature/supply conditions listed under transient signoff at 1 and 30 mA with the nominal output network; and every one of those five conditions crossed with all four output-capacitance/ESR extremes at 1 and 30 mA. This explicitly checks the PVT-by-output-network stability interaction.

At TT/27 C over all supplies and loads, plus five representative process/temperature/supply extremes at 30 mA, PSRR must be at least 40 dB at 100 Hz and 1 kHz, 20 dB at 100 kHz, and 10 dB at 1 MHz. At TT/1.8 V/27 C and 10 mA, integrated device noise from 10 Hz through 1 MHz must not exceed 150 uVrms.

Startup, load-step, and line-step signoff runs at TT/1.8 V/27 C, SS/1.62 V/125 C, FF/1.98 V/-40 C, SF/1.62 V/125 C, and FS/1.98 V/-40 C with the nominal output network. It is repeated at the low-headroom SS/1.62 V/125 C stress for all output-capacitance/ESR extremes.

- With a 120 ohm startup load and a 20 us input ramp beginning at 1 us, output must reach and thereafter remain above 90% of 1.2 V by 30 us from transient start, and must enter and remain within +/-2% of 1.2 V no more than 10 us after the ramp; overshoot above 1.2 V must not exceed 50 mV.
- A 1 to 25 mA to 1 mA load pulse with 200 ns edges must stay within 20 mV of the commanded 1.2 V output target and enter and remain within 15 mV of that target in no more than 5 us after either edge.
- A 1.98 to 1.62 to 1.98 V line pulse with 200 ns edges at 10 mA must meet the same 20 mV excursion plus 15 mV / 5 us settling limits relative to the commanded 1.2 V target.

At 1.8 V/27 C and 10 mA, 30 deterministic process-plus-local-mismatch runs require at least 90% of outputs between 1.17 and 1.23 V.

## Environment

Run `source ./eda_env.sh` in the workspace. Read `GUIDE.md` for native EDA
commands and `DEVICE_API.md` for the installed SKY130 device interfaces.
You may write your own layout, checking, and simulation scripts.

Native simulation examples and their commands are provided in
`task/testbench/README.md`. They cover representative conditions; the complete
required operating conditions remain those specified above.

`ALB_MODEL_LIB` selects this task's qualified SKY130 model library.
`ALB_NGSPICE_INIT` contains its ngspice initialization; use it as described in
`GUIDE.md` for both pre-layout and post-layout simulation. Select the specified
process corner with `.lib` and use `.option scale=1e-6` for numeric device
dimensions in micrometres. Preserve the fixed physical devices and their sizes.
When `task/lvs_reference.spice` is supplied, it describes the same devices using
the installed LVS reader's syntax. Use `task/circuit.spice` or the extracted DUT
for simulation, not the LVS-only reference.

Work offline using the provided files, installed software, and local documentation.
Do not access the network through browsers, web tools, shell commands, package
managers, or scripts. The harness's model API connection is managed by the
evaluation infrastructure and is the only permitted network use.

## Deliverables

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

- Save the layout as `submission/layout.gds`, with top cell `ldo_ota5`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_dropout_pvt.spi`, `tb_line_tran_dynamic.spi`, `tb_line_tran_output_network.spi`, `tb_load_tran_dynamic.spi`, `tb_load_tran_output_network.spi`, `tb_loop_nominal.spi`, `tb_loop_output_network.spi`, `tb_loop_pvt.spi`, `tb_noise.spi`, `tb_psrr_nominal.spi`, `tb_psrr_pvt.spi`, `tb_pvt_dc.spi`, `tb_startup_dynamic.spi`, `tb_startup_output_network.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
