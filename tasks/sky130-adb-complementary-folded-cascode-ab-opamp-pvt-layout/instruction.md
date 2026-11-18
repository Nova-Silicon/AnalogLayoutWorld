[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a complementary rail-to-rail Class-AB operational amplifier

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `complementary_folded_cascode_ab_opamp`, with ports in this order:
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

Use the 1.8 V SKY130 core models. The top-level interface provides a 20 µA reference-current port. The verifier evaluates all five process corners (`tt`, `ff`, `ss`, `fs`, and `sf`) at each of these five voltage-temperature stresses:

- 1.62 V at −40 °C
- 1.62 V at 125 °C
- 1.80 V at 27 °C
- 1.98 V at −40 °C
- 1.98 V at 125 °C

This is a declared representative 25-point PVT matrix: for each process corner it covers the nominal voltage-temperature point and the four corners of the supply-temperature box. It is not the complete 45-point Cartesian product of five process corners, three supplies, and three temperatures.

The named design target uses complementary NMOS/PMOS input paths, a folded-cascode current-summing stage, a floating-current-source Class-AB output stage, and series-RC Miller compensation. These functional stages define the task identity and design intent.

The required top-level subcircuit is:

```spice
.subckt complementary_folded_cascode_ab_opamp vss iref vdd vinn vinp vout
* complete transistor-level implementation
.ends complementary_folded_cascode_ab_opamp
```

`vss`, `iref`, and `vdd` are the supply/bias ports. `vinn` and `vinp` are the differential inputs; `vout` is the single-ended output.

The 4 pF output load and all stimulus sources are external testbench elements.

**Reproducible acceptance envelope.**

The following limits are the SKY130/ngspice sign-off contract used by the verifier. They are deliberately stated with the exact load, common-mode points, integration band, and PVT matrix so that another implementation cannot pass by exploiting an undefined measurement.

- With the specified 4 pF capacitive load, the AC bench uses DC-only level-shifted feedback to hold the output at `VDD/2` while independently sweeping input common mode; a 1 TΩ return to `VDD/2` prevents a floating output without materially loading it. At every published PVT point it evaluates `VCM = 0.1 V`, `0.2 V`, `VDD/2`, `VDD−0.2 V`, and `VDD−0.1 V`. Open-loop gain at 10 Hz is at least 90 dB at the three core-range points and at least 80 dB at the two 0.1 V near-rail points.
- Unity-loop UGB is at least 1 MHz at all five common-mode points. Phase margin is at least 60° at the three core-range points and at least 55° at the two near-rail points. The UGB maximum/minimum ratio over the complete PVT and common-mode AC matrix is at most 2.0. Missing gain, a missing unity crossing, a non-finite phase measurement, or an incomplete matrix fails closed. Closed-loop tracking and transient benches separately verify output swing and large-signal behavior; the AC test does not bias the output at a supply rail.
- With a 10 kΩ load to `VDD/2`, unity-gain tracking error is at most 20 mV from 0.1 V to VDD−0.1 V and at most 5 mV from 0.2 V to VDD−0.2 V. The measured input common-mode span is at least 1.5 V and reaches within 0.1 V of each rail.
- Static supply power, including the 20 µA reference branch, is at most 1.5 mW. The verifier checks both the mid-supply AC operating point and the maximum closed-loop power over an input sweep from 0 V to VDD at every published PVT point.
- A 0.2 V ↔ VDD−0.2 V unity-gain step drives 4 pF in parallel with 10 kΩ to `VDD/2`. Both slew rates must be at least 2 V/µs. During the final 100 ns of each 2 µs command plateau, the output must remain within 5 mV of the commanded level.
- Common-mode rejection, supply rejection, and distortion use the fixed absolute common-mode point `VCM = 0.9 V` at TT/1.80 V/27 °C, SS/1.62 V/125 °C, and FF/1.98 V/−40 °C. Common-mode rejection is at least 70 dB at 1 kHz and 55 dB at 1 MHz; supply rejection is at least 45 dB at 10 Hz and 10 dB at 1 MHz.
- Integrated unity-gain input-referred noise from 10 Hz to 1 MHz is at most 70 µVrms across all 25 PVT points at `VCM = VDD/2`, with 4 pF in parallel with 10 kΩ to `VDD/2`. At each of the three representative points above, a unity-gain 1 kHz, 0.4 V-peak sine centered at 0.9 V has Fourier THD at most 0.01% and a bounded distortion residual at most 0.5% of the command amplitude. Three deterministic `tt_mm` seeds at TT/1.80 V/27 °C and `VCM = VDD/2` must each have closed-loop offset no greater than 5 mV. These fixed seeds are regression coverage, not a statistical-yield claim.

The tracking, step, noise, distortion, and offset benches use 4 pF in parallel with 10 kΩ to `VDD/2`. The self-contained CMRR and PSRR benches use their published differential reference instances, 4 pF loads, and 100 MΩ DC returns. The noise band, signal amplitude, source impedance, load, and measurement definitions are fixed by these electrical requirements. Missing, non-finite, or incomplete PVT rows fail closed; partial measurements do not establish a pass.

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

- Save the layout as `submission/layout.gds`, with top cell `complementary_folded_cascode_ab_opamp`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Post-layout scoring runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac.spi`, `tb_cmrr.spi`, `tb_noise.spi`, `tb_psrr.spi`, `tb_step.spi`, `tb_thd.spi`, `tb_track.spi`; other operating points are not expanded automatically. The extracted DUT uses those same test conditions.
The mismatch/Monte Carlo fixture `tb_offset.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
