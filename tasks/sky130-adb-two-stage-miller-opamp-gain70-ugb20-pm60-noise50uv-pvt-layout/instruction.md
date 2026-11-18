[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a Current-Biased Two-Stage Miller Op Amp: Gain 70 dB, UGB 20 MHz, PM 60 deg, Noise 50 uVrms

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `two_stage_miller_opamp`, with ports in this order:
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

The primary PVT set is the complete 27-point Cartesian product of process corners `tt`, `ff`, and `ss`; supplies 1.62 V, 1.80 V, and 1.98 V; and temperatures -40 C, 27 C, and 125 C. The bench supplies a 50 uA reference, uses 0.9 V input common mode, and loads `vout` with 2 pF.

- Low-frequency loop gain (measured at 10 Hz) >= 70 dB; UGB >= 20 MHz; return-ratio phase margin >= 60 deg. The loop-gain magnitude must not return above 0 dB beyond the unity-gain crossing.
- Quiescent output error from 0.9 V <= 25 mV; total power <= 600 uW.
- At every PVT point, input-referred integrated noise in a noise-gain-20 closed loop, from 10 Hz to that same point's measured closed-loop -3 dB bandwidth, must be <= 50 uVrms. The upper integration limit is measured independently at each point; it is neither fixed nor the open-loop UGB.
- PSRR+ >= 65 dB at 1 kHz and >= 20 dB at 1 MHz; CMRR >= 60 dB at 1 kHz.
- PSRR, CMRR, output range, settling, and slew are checked at three representative stresses: `tt`/1.80 V/27 C, `ss`/1.62 V/125 C, and `ff`/1.98 V/-40 C. At each point, unity-gain output range is the contiguous input interval whose closed-loop tracking error is at most 20 mV, and it must be >= 0.8 Vpp; a 100 mV step must settle within 30 ns, 2%, and 2 mV final error in both directions; 0.5 V slew rate must be >= 10 V/us in both directions.

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

- Save the layout as `submission/layout.gds`, with top cell `two_stage_miller_opamp`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_cmrr.spi`, `tb_noise.spi`, `tb_op_ac.spi`, `tb_psrr.spi`, `tb_settling.spi`, `tb_slew.spi`, `tb_swing.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
