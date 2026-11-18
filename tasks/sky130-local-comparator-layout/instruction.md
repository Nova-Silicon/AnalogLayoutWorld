[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a dynamic latch comparator

The English version is authoritative.

Implement the fixed dynamic latch and its two output buffers. The exposed internal-node ports are part of the declared interface and must remain available with their original names.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `comparator`, with ports in this order:
`clk gnd vdd net0 net1 net069 intern interp crossp crossn outm outp`.
Preserve topology, device models, connections and fixed dimensions.

`net0` is the positive input, `net1` the negative input. For a positive difference, `outp` must go high and `outm` low; the roles reverse for a negative difference. The clock, input voltages, power supply and separate 20 fF loads on `outp`/`outm` are external fixtures.

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

- Run all 90 combinations of process `tt`/`ff`/`ss`/`sf`/`fs`, temperature -40/27/125 °C, VDD=1.71/1.80/1.89 V, and input common mode 0.9/1.1 V.
- The clock is a 0–VDD, 50 MHz pulse, first rising at 10 ns, with 100 ps rise/fall times and 9.8 ns high time. Simulate to 100 ns with 20 fF on each output.
- Apply `net0 = VCM + ΔV/2`, `net1 = VCM − ΔV/2`. ΔV starts at +10 mV, changes to −10 mV over 40–41 ns, and returns to +10 mV over 80–81 ns.
- Check decisions at 18/38/58/78/98 ns: the selected output must be at least 0.9 VDD and the unselected output's absolute value at most 0.1 VDD. At reset samples 8/28/48/68/88 ns, both output absolute values must be at most 0.1 VDD.
- At the first decision and the first decision after each polarity reversal, delay from the clock's 50% rising crossing to the selected output's 50% rising crossing must be between 0 and 2 ns.
- Average supply power `−mean(I(VDD)) × VDD` during 20–100 ns must be at most 100 µW.
- Do not add offset, noise or kickback targets to this task.

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

- Save the layout as `submission/layout.gds`, with top cell `comparator`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_comparator.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
