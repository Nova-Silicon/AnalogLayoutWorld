[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a Current-Starved Ring VCO

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `current_starved_ring_vco`, with ports in this order:
`vss vctrl vdd vout`.
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

The tuning, startup, waveform, and power requirements apply across all 27 combinations of tt, ss, ff; 1.62, 1.80, 1.98 V; and -40, 27, 125 C. `vout` drives 20 fF.

- At every PVT point, the tuning range must include 25 MHz: `10 MHz <= f(0.9 V) <= 25 MHz` and `f(1.2 V) >= 25 MHz`. The tuning ratio `f(1.2 V)/f(0.9 V)` must be at least 1.5.
- Frequency is averaged over five complete periods at each fixed-control plateau, beginning 300 ns after that plateau starts. Every measured edge must remain inside the 1 us plateau. Frequency must increase at every step; minimum KVCO >= 30 MHz/V and maximum/minimum KVCO <= 1.50.
- Startup to the first rising half-supply crossing <= 100 ns. Frequency settling drift <= 0.10%, comparing two periods beginning 300 ns after each plateau starts with two periods beginning 300 ns before that plateau ends. Duty cycle at 1.1 V must be within 45--55%, and output swing must cross 10% and 90% of VDD.
- Average VDD power at 1.2 V control <= 200 uW. Supply pushing <= 100%/V.
- Supply pushing is measured at 27 C for each process corner, with `vctrl=1.1 V` and VDD at 1.71 and 1.89 V.
The fixed netlist determines the on-chip biasing and delay devices.

The nominal tuning staircase runs first. Failure there blocks the remaining PVT matrix; failure of tuning PVT blocks the three process-corner pushing tests.

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

- Save the layout as `submission/layout.gds`, with top cell `current_starved_ring_vco`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_push.spi`, `tb_tune.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
