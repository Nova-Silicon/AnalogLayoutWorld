[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a 0.4 V NMOS-Pass LDO Across PVT and Mismatch

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `nmos_pass_ldo`, with ports in this order:
`vdd vout vss vref ibias loop_out pass_gate`.
Preserve the circuit topology, device models, connections, dimensions, and declared
multiplicity parameters. External test sources, loads, clocks, and any
explicitly described package fixtures are not part of the DUT layout.
`loop_out` is the regulator amplifier output and `pass_gate` is the power-device
control node. The external bench connects the series injection source between them; do not short these pins inside the DUT.

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

The fixed DUT is a transistor-level LDO with a nominal 1.8 V input and 0.4 V reference. The testbench sinks 40 uA from `ibias`, applies a 10 pF external output capacitor, and evaluates both 1 mA and 5 mA load current.

DC, loop-stability, PSRR, and headroom signoff covers all 54 combinations of tt/ss/ff process, 1.6/1.8/2.0 V input, -40/27/125 C, and 1/5 mA load. At every point:

- `vout` must remain from 0.35 V through 0.45 V.
- Quiescent current is `-I(VDD) - ILOAD - 40 uA`, where `ILOAD` is the load current actually drawn from `vout` by the test-bench current mirror (measured, not the commanded value); it must be nonnegative and less than 400 uA.
- Phase margin must exceed 45 degrees and gain margin must exceed 6 dB.
- PSRR at 1 kHz, defined as `-20log10(|VOUT/VDD|)` for a 1 V AC supply perturbation, must exceed 40 dB.
- Every current-carrying MOSFET must have `|VDS|-|VDSAT| > 30 mV`. MOS devices carrying less than 1 nA are excluded so MOS capacitors and disabled branches do not impose a false saturation requirement. This definition is topology-independent.

Spectre STB is not required. The verifier inserts a zero-volt series source between `loop_out` and `pass_gate`, applies an AC perturbation, and uses the Middlebrook return ratio `-V(loop_out)/V(pass_gate)`. Phase margin is measured at the first falling 0 dB crossing; gain margin is measured at the first falling -180-degree phase crossing.

Mismatch signoff uses 50 deterministic `tt_mm` samples at 1.8 V and 27 C. For each of the 1 mA and 5 mA loads, the measured output mean plus or minus three sample standard deviations must remain inside 0.35-0.45 V.

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

- Save the layout as `submission/layout.gds`, with top cell `nmos_pass_ldo`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_pvt.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_mc.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
