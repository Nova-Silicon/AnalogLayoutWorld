[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout an enable-controlled RC oscillator

The English version is authoritative.

This is the standalone relaxation oscillator from a power-on-reset design, with enable, disable and restart operation. The complete POR and its digital counter are outside this task.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `rc_osc`, with ports in this order:
`dvdd out ena dvss`.
Preserve topology, device models, connections and fixed dimensions.

Keep all source dummy transistors. The ten internal resistors are `sky130_fd_pr__res_xhigh_po_1p41` with L=111 µm each; their third terminals connect to `dvss`. `XC1` is `sky130_fd_pr__cap_mim_m3_2`, W=L=30 µm, with six parallel units (`m=6`). The supply, enable stimulus and 50 fF output load are external fixtures.

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

- Run all nine combinations of process `tt`/`ss`/`ff` and temperature -40/27/125 °C, at VDD=1.8 V with a 50 fF output load.
- Start `ena` low. Raise it from 0 to 1.8 V during 100–100.01 µs, lower it during 3–3.00001 ms, and raise it again during 4–4.00001 ms. Simulate through 6 ms.
- Detect output edges at 0.9 V. Over 1–2.5 ms, frequency is the inverse of the median rising-edge period and must be 10–70 kHz. Peak-to-peak period variation divided by mean period must be at most 0.03. Each measured duty cycle must be 0.20–0.60.
- The first output rising edge must occur within 1 ms after the end of each enable rising edge, both at initial enable and restart.
- Average supply power during 1–2.5 ms must be at most 150 µW. During 3.3–3.8 ms, average supply current must be at most 100 nA and the maximum output voltage must be at most 0.18 V.
- The specification is confined to these nine points; wider supply range, independent R/C corners and mismatch are not additional requirements.

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

- Save the layout as `submission/layout.gds`, with top cell `rc_osc`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_rc_osc.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
