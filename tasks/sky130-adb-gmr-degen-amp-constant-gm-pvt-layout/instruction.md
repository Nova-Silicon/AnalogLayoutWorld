[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a constant-gain source-degenerated GM-R amplifier

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `gmr_degen`, with ports in this order:
`IREF VCM VDD VIN VIP VON VOP VSS`.
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

Implement `.subckt gmr_degen IREF VCM VDD VIN VIP VON VOP VSS`. The verifier runs the complete 15-point Cartesian product of five process corners (`tt`, `ff`, `ss`, `fs`, `sf`) and three temperatures (-40 C, 27 C, 85 C), all at `VDD = 1.80 V`. It supplies `IREF = 50 uA`, drives both input common-mode and `VCM` at 0.90 V, and connects 1 pF from each output to ground. `IREF` remains a required compatibility port even when a legal implementation obtains its local bias from `VCM`.

Every process-temperature point must meet every requirement:

- **Differential AC gain at 1 MHz:** 1.98 to 2.02 V/V.
- **Upper -3 dB differential bandwidth:** greater than 60 MHz relative to the 1 MHz gain. A response still above that level at the 10 GHz check point is reported as at least 10 GHz.
- **Total externally supplied DC power:** less than 1.5 mW. The measurement sums the absolute DC power at `VDD`, `VCM`, `VIN`, and `VIP`; the 50 uA `IREF` path is already supplied through `VDD`.
- **Large-signal SDR:** greater than 60 dB for a 3 MHz, 100 mV-peak differential sine input, while its fitted fundamental gain remains from 1.90 to 2.10 V/V. Over the final 1 us of a 1.5 us transient, the verifier fits the differential output to DC plus 3 MHz sine and cosine terms, then computes `10*log10(fundamental power / residual mean-square power)`.

The complete in-range 1 MHz gain matrix is the functional prerequisite for bandwidth and power checks. The verifier runs one nominal AC/power gate, the remaining process-temperature points, and only then the longer SDR transients.

This signoff excludes supply-voltage variation and statistical mismatch.

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

- Save the layout as `submission/layout.gds`, with top cell `gmr_degen`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac_power.spi`, `tb_sdr.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
