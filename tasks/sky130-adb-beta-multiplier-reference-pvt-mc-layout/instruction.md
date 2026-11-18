[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a beta-multiplier current reference

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `beta_multiplier_reference`, with ports in this order:
`vss vdd vref iout`.
Preserve the circuit topology, device models, connections, dimensions, and declared
multiplicity parameters. External test sources, loads, clocks, and any
explicitly described package fixtures are not part of the DUT layout.

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

## Fixed circuit variant

This task uses a qualified derivative of the source circuit. Its physical
resistors use `sky130_fd_pr__res_generic_po`: approximately 14.80 kΩ for the core
resistor and 1 MΩ for the startup resistor, with dimensions fixed in
`task/circuit.spice`. The resistor choices and values were changed; this is not a
naming-only conversion. The replacements use the PDK's two-terminal generic-poly
definition, instead of the original three-terminal resistor models. Main signal
connections, the MOS devices and their connections, top-level ports, source
continuous model library and electrical requirements are preserved.

## Spec

The nominal target is 40 uA with `iout` held at 0.9 V. At TT/1.8 V/27 C, output current must remain between 35 and 45 uA.

Complete PVT signoff covers every Cartesian combination of process corners tt, ss, ff; supplies 1.62, 1.8, 1.98 V; and temperatures -40, 27, 125 C. At all 27 points:

- Output current must remain between 20 and 60 uA.
- `vref` must remain between 0.60 and 0.75 V.
- Total DUT electrical power (`vdd` input power plus the power absorbed at the current-sink output held at 0.9 V) must not exceed 100 uW.
- Sweeping `iout` from 0.4 to 1.6 V must keep peak-to-peak current variation divided by mean current below 8%.

Startup signoff applies 1 and 10 us linear supply ramps in every corner at three paired supply/temperature stresses: 1.62 V/125 C, 1.8 V/27 C, and 1.98 V/-40 C. These pairs exercise low-headroom/hot, nominal, and high-supply/cold startup without redundantly repeating all nine DC points. Final current and `vref` must meet their PVT ranges. Settling time is measured from the end of the ramp to the first point after which output current remains within +/-10% of its final 1 us average and must not exceed 10 us. Peak output-current overshoot must stay below 1.5 times final current, peak positive VDD current below 100 uA, and positive energy drawn through ramp end plus 10 us below 1 nJ.

At 1.8 V/27 C, 50 deterministic combined process-and-local-mismatch samples require at least 90% of outputs between 30 and 50 uA and sample sigma no greater than 4 uA. The sample mean is reported but is not a separate pass condition.

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

- Save the layout as `submission/layout.gds`, with top cell `beta_multiplier_reference`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_compliance.spi`, `tb_startup.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
