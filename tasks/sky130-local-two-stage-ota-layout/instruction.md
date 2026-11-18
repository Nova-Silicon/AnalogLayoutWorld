[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a two-stage Miller-compensated OTA

The English version is authoritative.

Implement the fixed PMOS-input, single-ended two-stage amplifier, including its physical compensation resistor and MIM capacitor.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `two_stage_ota`, with ports in this order:
`vinp vinn vout ibias vdd vss`.
Preserve topology, device models, connections and fixed dimensions.

The two-terminal compensation resistor is `sky130_fd_pr__res_generic_po`, W=1 µm, L=20 µm; the capacitor is `sky130_fd_pr__cap_mim_m3_1`, W=L=22.2 µm. An external 5 µA reference source flows from VDD into `ibias`. The 5 pF output load, input sources and DC-only AC feedback fixture are external. Preserve MOS W/L/m and explicit body connections.

For LVS, use `task/lvs_reference.spice`. It only adapts primitive-instance naming and MIM area/perimeter representation to the installed reader; connections and physical sizes remain unchanged. For simulation, use `task/circuit.spice` or the extracted DUT, not the LVS-only reference.

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

- Use all 45 combinations of `tt`/`ff`/`ss`/`sf`/`fs`, -40/27/125 °C and VDD=1.71/1.80/1.89 V. Run both AC and follower transient at every point, with 5 pF load and the 5 µA reference supplied from VDD.
- AC input common mode is 0.5 V. Apply a 1 V small-signal source at `vinp`; establish the `vinn` DC feedback using 1 GH from `vout` to `vinn` and 1 F from `vinn` to ground, so the feedback is open over the AC band. Sweep 1 Hz–1 GHz at 60 points/decade. Gain at 1 Hz must be ≥70 dB; the first falling 0 dB crossover must be ≥5 MHz; phase margin, 180 degrees plus the continuous phase at that crossover, must be ≥60 degrees.
- Quiescent supply power must be ≤600 µW, including the external reference-current branch supplied from VDD.
- For the unity follower, directly connect `vinn` to `vout` and apply a 0.4→0.6→0.4 V pulse at `vinp`: first rising edge at 1 µs, 10 ns rise/fall times, 2 µs high time, 4 µs period; simulate through 8 µs. At 1.5 and 3.5 µs, output error from the respective commanded level must be ≤10 mV.
- The average rate over the middle 80% of each 0.2 V transition must be ≥1 V/µs: measure the time between 0.42 and 0.58 V on each edge and divide 0.16 V by that time. This is a small-step metric, not a large-signal slew-rate claim. Output maximum during 1–3 µs must be ≤0.65 V, and output minimum during 3–5 µs must be ≥0.35 V.
- In addition, run AC at all 16 combinations of passive corners `ll`/`hh`/`hl`/`lh`, -40/125 °C and VDD=1.71/1.89 V with typical MOS. The same AC gain, crossover, phase margin and power limits apply. These are separate passive-corner checks, not joint MOS/passive extremes.
- Noise, PSRR and mismatch-yield targets are not part of this task.

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

- Save the layout as `submission/layout.gds`, with top cell `two_stage_ota`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac.spi`, `tb_follower.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
