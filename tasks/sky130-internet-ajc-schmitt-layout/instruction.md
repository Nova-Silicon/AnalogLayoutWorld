[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout an eight-transistor Schmitt trigger

The English version is authoritative.

Implement the standalone non-inverting Schmitt-trigger block used in a power-on-reset circuit.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `schmitt_trigger`, with ports in this order:
`dvdd in out dvss`.
Preserve topology, device models, connections and fixed dimensions.

Implement all eight MOS instances and their explicit body connections. The supply, input waveform and 50 fF output capacitor are external fixtures.

The layout must pass DRC and LVS using the installed SKY130 decks and meet the following electrical specifications after parasitic extraction. Maximize area utilization through compact placement and routing without compromising process or electrical requirements.

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

- Run all nine combinations of process `tt`/`ss`/`ff` and temperature -40/27/125 °C, at VDD=1.8 V and 50 fF output load.
- Apply two complete 0→1.8→0 V triangular input cycles. Hold 0 V to 1 µs; rise to 1.8 V at 11 µs, hold to 12 µs, fall to 0 V at 22 µs, hold to 23 µs, rise to 1.8 V at 33 µs, hold to 34 µs, fall to 0 V at 44 µs, and hold to 45 µs.
- Define each switching threshold by the input voltage when the output crosses 0.9 V. Each rising-input threshold must be 1.10–1.35 V; each falling-input threshold must be 0.02–0.40 V. The corresponding hysteresis width must be 0.85–1.20 V. Both cycles must switch correctly.
- While the input is above 99% of VDD, the output must be at least 1.62 V; while the input is below 1% of VDD, the output must be at most 0.18 V.
- Average supply power over the complete 45 µs waveform must be at most 50 µW. These requirements use 1.8 V only; no additional low-supply or mismatch corner is required.

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

- Save the layout as `submission/layout.gds`, with top cell `schmitt_trigger`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_schmitt_trigger.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
