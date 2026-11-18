[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a 15-transistor symmetrical-current-branch amplifier

The English version is authoritative.

This is a fixed SKY130 LVT circuit selected from LOADBench. Its accepted electrical target is the task specification below, not the source benchmark’s broad sizing filter.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `SymmetricalOpAmp3`, with ports in this order:
`ibias in1 in2 out sourceNmos sourcePmos`.
Preserve topology, device models, connections and fixed dimensions.

Preserve the source W/L/m and all explicit body connections. NMOS bodies connect to `sourceNmos`; PMOS devices whose bodies use different internal nets require separate wells. The 10 µA bias source, 1 pF output load, input sources and measurement feedback elements are external. For the tests, `sourceNmos` is ground and `sourcePmos` is VDD.

For LVS, use `task/lvs_reference.spice`. It only adapts primitive-instance naming to the installed reader; connections and physical sizes remain unchanged. For simulation, use `task/circuit.spice` or the extracted DUT, not the LVS-only reference.

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

- Use process `tt`, VDD=1.8 V, temperatures 0/27/85 °C, a 1 pF output load and a 10 µA external current from `ibias` to ground. The nominal input common-mode voltage is 0.9 V. `in1` is the non-inverting input and `in2` is the inverting input under the declared test connection.
- At each of the three temperatures: 1 Hz open-loop gain ≥45 dB; unity-gain frequency ≥60 MHz; phase margin ≥60 degrees; quiescent supply power ≤7 mW; low-frequency CMRR ≥45 dB; low-frequency PSRR ≥40 dB; absolute unity-follower offset at 0.9 V ≤5 mV.
- First find the unity-follower operating point at 0.9 V. In the open-loop AC fixture, place a DC source from the 0.9 V common-mode node to the inverting input with value `0.9 V - Vout(follower)`; drive the non-inverting input with a 1 V AC source relative to the common-mode node. Sweep 1 Hz–1 GHz at 20 points/decade. Use the source-compatible linear interpolation of samples on either side of 0 dB for unity-gain frequency and phase. Subtract the phase at the first AC point before unwrapping; phase margin is 180 degrees plus the interpolated phase. CMRR and PSRR subtract the corresponding DC `.tf` common-mode or VDD transfer gain from the differential gain at 10 Hz. Supply power is VDD times current drawn from the supply in the unity-follower operating point.
- In a 0–1.8 V unity-follower DC sweep with 10 mV input increments, use the 10 mV absolute tracking-error crossings to define the common-mode boundaries, reporting the output voltage at each crossing as in the source measurement. The lower boundary must be ≤0.75 V and the upper boundary ≥1.6 V.
- Measure output range with the non-inverting input at 0.9 V, a 1 GΩ input resistor and 10 GΩ feedback resistor on the inverting input. Sweep the resistor input from 0 to 1.8 V in 5 mV increments. Use the 5% departure from the finite-open-loop-gain closed-loop slope (magnitude `0.95 / (1/A0 + 1/10 + 1/(10*A0))`) to define the boundaries. The lower output boundary must be ≤0.7 V and the upper boundary ≥1.0 V.
- At TT, 27 °C only, run a unity-follower transient with a 0.85↔0.95 V input, first rising at 5 µs, 10 ns edges, 5 µs high time and 10 µs period, through 20 µs. Maximum absolute tracking error in each window 4–4.9, 9–9.9, 14–14.9 and 19–19.9 µs must be ≤5 mV. This is the independent dynamic requirement; a positive AC phase-margin value alone is insufficient.
- No additional process/supply corner, mismatch-yield target or large-signal slew-rate target is required.

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

- Save the layout as `submission/layout.gds`, with top cell `SymmetricalOpAmp3`.
- Save layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_closed_loop_step.spi`, `tb_source_combined.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
