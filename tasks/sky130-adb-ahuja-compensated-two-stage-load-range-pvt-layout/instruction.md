[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a two-stage OTA for a 10:1 capacitive-load range

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `ahuja_ota`, with ports in this order:
`vss iref vdd vinp vinn vout`.
Preserve the circuit topology, device models, connections, and dimensions.
The bias sources, input signals, output loads, and measurement feedback network
are external test conditions and are not part of the DUT layout.

The internal resistors are `sky130_fd_pr__res_high_po_1p41` devices with their
third terminals connected to `vss`; the internal capacitors are
`sky130_fd_pr__cap_mim_m3_1` devices. Their model names and dimensions in the
netlist are fixed. For LVS, use `task/lvs_reference.spice`: its MIM area/perimeter
syntax describes the same physical sizes for the installed reader. For simulation,
use `task/circuit.spice` or the extracted DUT, not the LVS-only reference.

The layout must pass DRC and LVS using the installed SKY130 decks and meet the
following electrical specifications after parasitic extraction. Maximize area
utilization by keeping placement and routing compact without compromising
process or electrical requirements.

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

- The bench supplies 50 uA at `iref`. The output target and the input common-mode voltage are 0.9 V.
- The 20 pF and 200 pF AC conditions, DC follower condition, and 200 pF follower transient each run all 45 combinations of `tt`/`ff`/`ss`/`fs`/`sf`, 1.62/1.80/1.98 V, and -40/27/125 C. A 63 pF AC stability guard runs at 1.80 V and 27 C in every process corner.
- AC uses a 1 V small-signal source at `vinp` and a 500 Mohm/50 mF DC servo from `vout` to `vinn`; the servo is open over the measured AC band. At 20 pF, gain at 10 Hz must be at least 58 dB and the first falling 0 dB crossover must be at least 6.5 MHz. At each declared AC point, phase margin at that crossover must be at least 60 degrees, and the loop gain must not return above 0 dB before 300 MHz.
- In the 20 pF DC follower condition, absolute output offset from 0.9 V must be at most 6 mV and supply power must be at most 2 mW.
- With a 200 pF load and direct unity feedback (`vinn = vout`), `vinp` makes a 0.9 V to 1.2 V to 0.9 V pulse with 10 ns edges. Measured from the 1% command crossing on either edge, `vout` must enter and remain within 6 mV of the known 0.3 V-step target within 2 us. The error at the end of each commanded level must also be at most 6 mV.

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

- Save the layout as `submission/layout.gds`, with top cell `ahuja_ota`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_guard.spi`, `tb_heavy.spi`, `tb_light.spi`, `tb_step.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
