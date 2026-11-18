[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a Gain-Boosted Folded-Cascode OTA: Gain 130 dB, UGB 200 MHz, PM 60 deg, Noise 50 uVrms

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `folded_cascode_ota`, with ports in this order:
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

The bench forces 50 uA from `vdd` into `iref`. Meet the main requirements at every one of the 27 unique Cartesian combinations of `tt`, `ss`, and `ff`; 1.62 V, 1.80 V, and 1.98 V; and -40 C, 27 C, and 125 C. Input and target output common modes are 0.9 V; the output drives 1 pF.

- DC gain >= 130 dB, UGB >= 200 MHz, phase margin >= 60 deg, output error <= 0.8 mV, and power <= 5.4 mW. The 10 Hz to 100 GHz return-ratio response must have exactly one falling 0 dB crossing and remain below unity after it. UGB and phase margin use that first falling crossing; no crossing or any later recross fails.
- Integrated unity-gain input noise <= 50 uVrms from 10 Hz to 10 MHz.
- Closed-loop range is checked at tt/1.80 V/27 C, ss/1.62 V/-40 C, and ss/1.62 V/125 C. The public sweep is 0.30 V through 1.50 V in 10 mV steps. The scored value is the longest continuous interval whose every sampled point has `abs(vout-vinp) <= 20 mV`, with interpolation only across the two adjacent qualified/unqualified boundary samples. That interval must be at least 0.92 Vpp.
- Closed-loop settling is checked at tt/1.80 V/27 C, ss/1.98 V/-40 C, and ff/1.98 V/-40 C. The public command rises from 0.85 V to 0.95 V and later falls back to 0.85 V, using 1 ns linear edges. For each direction, settling uses the last-entry predicate: after the reported entry sample, every remaining sample in the published observation window must stay within 0.7 mV of the commanded endpoint. The worst direction must settle within 10 ns; the final 5 ns mean error must be <= 0.7 mV and <= 0.7% of the 0.1 V step.

Mismatch, Monte Carlo, CMRR, and PSRR are outside this task.

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

- Save the layout as `submission/layout.gds`, with top cell `folded_cascode_ota`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_noise.spi`, `tb_op_ac.spi`, `tb_range.spi`, `tb_settling.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
