[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a 2 MHz Low-Power Oscillator

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `osc_2m`, with ports in this order:
`AVDD AVSS CLKO IBN2U`.
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

## Spec

Evaluation uses five disclosed, representative Sky130 PVT points:

- `tt` / 1.80 V / 27 C (nominal functional gate)
- `ff` / 1.62 V / 27 C
- `ss` / 1.98 V / 85 C
- `ss` / 1.62 V / -40 C
- `ff` / 1.98 V / -40 C

Together these points cover the declared `tt`, `ss`, and `ff` process corners, all three supplies (1.62 V, 1.80 V, and 1.98 V), and all three temperatures (-40 C, 27 C, and 85 C). They are representative stresses rather than a complete Cartesian PVT claim. At each point the supply ramps from 0 V to its declared value in 1 us, the bench sources 2 uA from the measured supply path into `IBN2U`, and `CLKO` drives 1 pF to ground. Metrics use the saved 10--20 us steady-state interval of a 20 us transient, so the oscillator must have started and reached the specified behavior by 10 us.

- Output frequency, measured over ten consecutive rising-edge periods at half supply, must be from 1.8 MHz through 2.2 MHz.
- Output peak-to-peak swing over the steady-state interval must be from 0.95 through 1.05 times the applicable `VDD`.
- At the nominal `tt` / 1.80 V / 27 C point, average total power drawn from the supply during the steady-state interval, including the fixed 2 uA bias input and output-load drive, must be at most 20 uW.

Other process corners, supplies, temperatures, loads, startup behavior before 10 us, phase noise, jitter, and statistical mismatch are outside this task's declared scope.

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

- Save the layout as `submission/layout.gds`, with top cell `osc_2m`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_osc.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
