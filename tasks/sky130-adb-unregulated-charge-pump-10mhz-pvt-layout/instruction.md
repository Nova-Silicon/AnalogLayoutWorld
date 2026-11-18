[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout an Unregulated Charge Pump

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `charge_pump_unregulate`, with ports in this order:
`AVDD AVSS CLK EN VOUT`.
Preserve the circuit topology, device models, connections, dimensions, and declared
multiplicity parameters. External test sources, loads, clocks, and any
explicitly described package fixtures are not part of the DUT layout.
`EN` is an active-high enable input.

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

Evaluation uses these eight representative process-temperature points at a
fixed 1.8 V supply:

- `tt` at 40 C;
- `ss` at -10 C and 125 C;
- `ff` at -10 C and 125 C;
- `sf` at -10 C and 125 C;
- `fs` at 40 C.

This set spans all five Sky130 process corners and all three declared
temperatures. It includes the low-output/high-current, high-output, and
ripple/leakage stresses identified by full-matrix reference characterization.
`CLK` is a 10 MHz rail-to-rail square wave with 1 ps edges and a 50%
duty cycle. The clock and enable controls each drive the DUT through 50 ohm
source resistance. The enabled output drives 1 nF to ground and a constant
50 uA load to ground; the disabled-current bench drives only 1 nF. A 200 us transient
is simulated at all eight representative points. The enabled circuit must reach
its qualifying steady state within 200 us, and its metrics use the 190--200 us
interval. The disabled-current bench holds `EN=0`, keeps the external clock
running at 10 MHz, and averages supply current from 9 us through 10 us after
powerdown has been asserted from time zero.

- Enabled mean `VOUT` must be from 2.2 V through 2.8 V.
- Enabled output ripple, `max(VOUT)-min(VOUT)`, must be at most 5 mVpp.
- Enabled average supply current must be at most 200 uA.
- Disabled average supply current with `EN=0` must be at most 100 nA.

All four limits apply at every PVT point. Enabled and disabled supply currents
are measured in separate bench runs through ideal supply sense sources, so no
fixture or DUT instance shares current between operating states. Other
supplies, temperatures, clock rates, loads,
unlisted process-temperature combinations, startup behavior after 200 us,
efficiency, and statistical mismatch are outside this representative task's
declared scope. This task does not claim a complete Cartesian PVT qualification.

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

- Save the layout as `submission/layout.gds`, with top cell `charge_pump_unregulate`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_disabled.spi`, `tb_enabled.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
