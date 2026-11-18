[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a three-stage nested-Miller amplifier for 200 pF loads

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `three_stage_nmc_ota`, with ports in this order:
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

The fixed DUT is a three-gain-stage amplifier with nested Miller compensation for a 200 pF capacitive load. The bench supplies a 5 uA reference on `iref`, uses 0.9 V input common mode and output target, and evaluates the complete 45-point Cartesian product of process corners `tt`, `ff`, `ss`, `fs`, and `sf`; supplies 1.62 V, 1.80 V, and 1.98 V; and temperatures -40 C, 27 C, and 125 C. Every metric below is checked once at every declared point.

- Low-frequency return-ratio gain at 0.1 Hz must be at least 110 dB, unity-gain bandwidth must be at least 0.4 MHz, and return-ratio phase margin must be at least 70 degrees.
- Quiescent output error from 0.9 V must be at most 10 mV, and total supply power must be less than 300 uW.
- The large-load drive figure of merit `UGB(kHz) * 200 pF / power(uW)` must be at least 300 kHz*pF/uW. This efficiency class corresponds to 0.4 MHz under the stated load at about 267 uW, coupling the bandwidth class to the micro-power envelope.
- Absolute DC current at each input pin must be at most 100 nA.
- The largest contiguous unity-feedback input interval whose output tracks within 20 mV must span at least 0.8 Vpp.
- For a 0.4 V to 0.9 V command with a 100 ns edge, the output must enter and remain within 2% of the commanded 0.5 V step in less than 3 us, and final tracking error must also be at most 2%.
- For a unity-feedback 0.65 V to 1.15 V step, both the rising and falling 0.75 V to 1.05 V slew rates must be at least 0.2 V/us.

The electrical test conditions use ideal independent external sources and an ideal 200 pF load. Local mismatch and Monte Carlo variation, package effects, and aging are outside this task.

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

- Save the layout as `submission/layout.gds`, with top cell `three_stage_nmc_ota`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_pvt.spi`, `tb_settling.spi`, `tb_slew.spi`, `tb_swing.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
`tb_input_bias.spi` is retained as a diagnostic fixture. Its MOS-gate DC input-current check is identically zero in this model and is excluded from post-layout scoring.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
