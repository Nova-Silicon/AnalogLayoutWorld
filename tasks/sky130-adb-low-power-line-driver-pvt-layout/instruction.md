[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a low-power line driver

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `low_power_line_driver`, with ports in this order:
`vss iref vdd vinn vinp vout`.
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

All requirements are evaluated over all 45 combinations of `tt`, `ff`, `ss`, `fs`, and `sf`; 1.62, 1.80, and 1.98 V supplies; and -40, 27, and 125 C. The testbench supplies 50 uA at `iref`. Closed-loop tests use two 10 kohm resistors for an inverting gain of -1 around a 0.9 V reference. The output drives a 1 uF coupling capacitor, 300 ohm line, and 200 pF lumped output/load parasitic.

- Broken-loop gain at 10 Hz must be at least 40 dB, unity-gain bandwidth at least 0.5 MHz, and phase margin at least 60 degrees.
- Quiescent output error from 0.9 V must be at most 20 mV, and quiescent VDD power at most 400 uW.
- With a 20 kHz, 0.6 V-peak sine input, output fundamental must be at least 0.55 V and THD through the ninth harmonic at most 3%.
- Peak VDD current during that sine test must be at least 2 mA and at least 10 times the quiescent supply current at the same PVT point.
- A slow closed-loop sweep must provide at least 1.5 Vpp of output range with at most 20 mV tracking error.

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

- Save the layout as `submission/layout.gds`, with top cell `low_power_line_driver`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_loopgain.spi`, `tb_swing.spi`, `tb_thd.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
