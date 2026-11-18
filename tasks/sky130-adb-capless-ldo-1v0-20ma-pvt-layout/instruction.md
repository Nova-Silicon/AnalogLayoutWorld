[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a Fully-Integrated External-Capacitor-Free LDO

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `capless_ldo`, with ports in this order:
`vin vout vss vref`.
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

The external testbench supplies an ideal unlimited-drive `vref = 0.4 V` and an output load sunk by a test-bench NMOS current mirror whose ideal reference current is the commanded load; being a transistor sink, it cannot pull `vout` below ground. Current drawn from `vref` is not included in quiescent current. There is no external output capacitor, divider, or bias port; the supplied fixed DUT defines the on-chip capacitance and feedback divider.

DC regulation and quiescent-current signoff cover all 30 Cartesian combinations of tt, ff, ss, fs, sf; 1.5 and 1.8 V input; and -40, 27, and 85 C. At every point, over the full 0-20 mA load range (a slow, quasi-static load ramp that starts from the powered-up no-load state), `vout` must stay within 30 mV (3%) of 1.0 V, and the no-load current drawn from `vin`, which includes the internal divider but excludes the ideal `vref` source, must not exceed 100 uA.

Dynamic operation is specified from 0.5 mA to 20 mA. Zero external load is a DC-regulation and quiescent-current condition, not a dynamic-load guarantee. Internal return ratio, unity-gain frequency, and phase margin are design diagnostics rather than scores because a submitted full-LDO netlist does not provide a verifier-owned, topology-independent loop-break point.

At 27 C and 20 mA load, for all five corners at both supplies, PSR must be at least 30 dB (1.5 V input) / 35 dB (1.8 V input) at 1 kHz, 20 dB at 100 kHz, and 10 dB at 1 MHz. The 1.5 V input operates 0.5 V from dropout, which is why its 1 kHz limit is lower.

Load-step signoff covers all 30 Cartesian corner/supply/temperature combinations used by DC signoff. Startup signoff runs at tt/1.8 V/27 C, sf/1.5 V/-40 C, fs/1.8 V/85 C, and ss/1.5 V/85 C.

- A 0.5 mA to 20 mA to 0.5 mA load step with 1 us edges (edges start at 20 us and 60 us) is applied. From each edge start until 20 us after that edge completes (20-41 us and 60-81 us), `vout` must stay within 150 mV (15%) of the 1.0 V target; from 20 us after each edge completes until the next edge starts or the end of the 100 us transient (41-60 us and 81-100 us), `vout` must stay within 30 mV (3%) of the same target. The recovery band matches the full-PVT DC regulation band.
- For startup, `vin` ramps from 0 to its target over 100 us into a 2 kohm load, which draws 0.5 mA at the 1.0 V target without an unphysical constant-current pull-down while the supply is off. `vout` must never exceed 1.05 V and must stay within 20 mV of 1.0 V from 200 us to 400 us.

All limits are fixed engineering targets, and evaluation scores only the published external electrical behavior. The DC/IQ and load-step matrices carry the full declared corner, line, and temperature axes; PSR is a declared 27 C full-load test. Mismatch, Monte Carlo, and output noise are out of scope.

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

- Save the layout as `submission/layout.gds`, with top cell `capless_ldo`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_matrix.spi`, `tb_psr.spi`, `tb_start.spi`, `tb_step.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
