[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a static CML divide-by-2 frequency divider

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `cml_div2`, with ports in this order:
`vss iref vdd clkn clkp outn outp`.
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

Implement the top-level DUT:

```spice
.subckt cml_div2 vss iref vdd clkn clkp outn outp
```

The external `iref` port is driven by a 150 uA reference current. The clock
common-mode is 0.9 V and the output load is 10 fF from each output to `vss`.
The signoff uses the `tt`, `ff`, `ss`, `fs`, and `sf` process corners at
1.80 V and 27 C. Every requirement must pass at every process corner.
The complementary clock sources have 10 ps rise and fall times and drive the
DUT through 50 ohm series resistors. The transient bench supplies a released
operating-point hint of `outp=1.0 V` and `outn=0.8 V` only to select one of the
divider's two equivalent phases; it does not force either output during the
transient.

Every declared process corner must satisfy both requirements:

- **Divide-by-2 operating points:** with a 300 mV differential peak-to-peak
  clock at 1 GHz, 2 GHz, 5 GHz, and 10 GHz, the output must contain a continuous
  divide-by-2 waveform for at
  least 40 observed input cycles after startup, with output differential swing
  at least 200 mV peak-to-peak in every observed input period. The verifier
  also checks that the output contains a measurable component at the expected
  divide-by-2 frequency (`f_input/2`), so an unrelated free-running waveform
  or a single output spike is not sufficient. The target-frequency component
  must be at least 200 mV peak-to-peak. The verifier checks 1 GHz,
  2 GHz, 5 GHz, and 10 GHz. All four
  frequencies must pass at every declared process corner. The input amplitude
  is defined as `max(srcp-srcn)-min(srcp-srcn)` at the source before the 50 ohm
  input resistors.
- **Power:** quiescent external VDD power must be less than 1.5 mW.

The first 5 ns form the startup window and do not count toward the result. A
correct cycle is identified by sampling the differential output once per input
period and checking the expected alternating sign for 40 consecutive cycles.
The verifier additionally checks the minimum differential swing in each
observed input-period window and the output component at `f_input/2`; missing,
extra, or isolated output activity must fail the case. The output frequency is
therefore measured from the simulated output waveform, not inferred from a
simulator command or a private internal node. Quiescent power is measured with
both clock inputs held at their 0.9 V common-mode level.

The four nominal-corner frequency points run first. Failure there blocks the
remaining process corners and the power runs. Failure at any process-corner
frequency point blocks the power runs.

This is a fixed-voltage, fixed-temperature process-corner task. Supply and
temperature sweeps, mismatch, phase-noise signoff, and
clock-driver energy outside the declared 50 ohm source resistors are outside
the score.

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

- Save the layout as `submission/layout.gds`, with top cell `cml_div2`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_divider.spi`, `tb_power.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
