[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a 1.2 V bandgap reference

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `bandgap`, with ports in this order:
`vdd vss vref`.
Preserve topology, device models, connections and fixed dimensions, including the startup circuit and the internal amplifier.

The circuit combines the base-emitter voltage and a proportional-to-absolute-temperature contribution from two PNP branches. The PNP cells are `sky130_fd_pr__pnp_05v5_W0p68L0p68`, with multiplicities 1 and 8. All 33 high-poly resistor segments belong to the DUT: their model is `sky130_fd_pr__res_high_po`, their width is 0.35 µm, and their individual lengths and connections are fixed by the netlist. Preserve both `sky130_fd_pr__cap_mim_m3_1` capacitors, including the 38.58 µm × 38.58 µm Miller capacitor and the 31.475 µm × 31.475 µm capacitor. Preserve all MOS W/L/m values and body connections.

The external test load is 10 pF in parallel with 100 MΩ from `vref` to `vss`. The supply source and its startup ramp are external. Do not add an external bias or reference source.

For LVS, use `task/lvs_reference.spice`. It describes the same device geometry and connections in the installed reader's syntax: the 0.35 µm high-poly family name carries the fixed resistor width, MIM capacitors use area/perimeter parameters, and parallel PNP units are explicit. It does not change resistor lengths or electrical targets. For simulation, use `task/circuit.spice` or the extracted DUT, not the LVS-only reference.

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

### Temperature sweep

- Run all 27 combinations of corner `tt`/`ff`/`ss`/`sf`/`fs`/`ll`/`hh`/`hl`/`lh` and VDD=1.71/1.80/1.89 V.
- At each combination, sweep temperature from −40 °C through 125 °C in 5 °C increments: 34 points, including the 25 °C reference point. Use the same 10 pF and 100 MΩ external load.
- At every temperature point, the reference voltage must be between 1.17 V and 1.23 V, inclusive.
- The box temperature coefficient must be ≤100 ppm/K. For each sweep, calculate `(Vmax − Vmin) / Vref(25 °C) / 165 × 10^6` from all 34 temperature points.
- Quiescent supply current must be ≤50 µA at every temperature point. Measure the maximum of `−I(VDD)` over the complete sweep, with the supply source's positive terminal connected to `vdd`.

### Startup

- Run all 45 combinations of MOS corner `tt`/`ff`/`ss`/`sf`/`fs`, temperature −40/27/125 °C and VDD=1.71/1.80/1.89 V.
- Also run two conditions for each passive corner `ll`/`hh`/`hl`/`lh`: (−40 °C, 1.71 V) and (125 °C, 1.89 V). These add 8 cases, for 53 startup cases in total.
- Start from zero-state power-up with `UIC`. Ramp VDD linearly from 0 V to its target in 10 µs, and hold it there through 2 ms. Do not use an external bias or reference source.
- Vref must be inside the inclusive 1.17–1.23 V window at 1 ms and remain inside that window throughout 1–2 ms. This is a deadline for entering the specified voltage window; it does not require complete settling by 1 ms.
- Use the same external 10 pF and 100 MΩ load.

The complete specification contains 27 temperature sweeps and 53 startup analyses. MOS corners use nominal passive models; `ll`/`hh`/`hl`/`lh` use typical MOS models. These separate passive checks do not claim joint MOS/passive extremes. Monte Carlo offset/yield, independent BJT process extremes, trimming yield, PSRR, noise and load regulation are outside this task's electrical requirements.

## Environment

Run `source ./eda_env.sh` in the workspace. Read `GUIDE.md` for native EDA
commands and `DEVICE_API.md` for the installed SKY130 device interfaces.
You may write your own layout, checking, and simulation scripts.

Native simulation examples and their commands are provided in
`task/testbench/README.md`. They cover representative conditions; the complete
required operating conditions remain those specified above.

`ALB_MODEL_LIB` selects this task's qualified continuous SKY130 model library.
`ALB_NGSPICE_INIT` contains its ngspice initialization, including
`set ngbehavior=hsa`; use it as described in `GUIDE.md` for both pre-layout and
post-layout simulation. Select the specified process corner with `.lib` and
use `.option scale=1e-6` for numeric device dimensions in micrometres.

The native examples include a SPICE model-binding subcircuit for extracted
`sky130_fd_pr__res_high_po_0p35` instances. It binds the fixed 0.35 µm family
name to the original continuous `sky130_fd_pr__res_high_po` model. Keep the
extracted length, multiplicity, three terminals and parasitic elements; do not
replace them with schematic values. See the testbench README for the exact
usage.

Work offline using the provided files, installed software, and local documentation.
Do not access the network through browsers, web tools, shell commands, package
managers, or scripts. The harness's model API connection is managed by the
evaluation infrastructure and is the only permitted network use.

## Deliverables

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

- Save the layout as `submission/layout.gds`, with top cell `bandgap`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_startup.spi`, `tb_temperature.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
