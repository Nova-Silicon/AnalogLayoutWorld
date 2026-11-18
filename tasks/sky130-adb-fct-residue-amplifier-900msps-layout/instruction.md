[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a 900 MS/s Floating Charge Transfer Residue Amplifier

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `test_fct`, with ports in this order:
`cinn cinp coutn coutp ib sam transfer vcm vddana vdddig vssana vssdig`.
Preserve topology, device models, connectivity, MOS dimensions/multiplicities,
and capacitor dimensions. All 14 internal capacitors are fixed
`sky130_fd_pr__cap_mim_m3_1` devices. The clock buffer and inverter subcircuits
are part of the DUT.

The external flying capacitors, sampling/transfer switches, output precharge,
track-and-hold switches, supplies, bias/reference sources, stimuli, and output
loads belong to the testbench, not the layout.
`vssana` and `vssdig` are distinct DUT nets; the testbench ties them together
externally. Preserve all independent NMOS and PMOS body connections.

The layout must pass KLayout DRC and Magic extraction plus Netgen LVS using
the installed SKY130 technology/setup. Compare against `task/circuit.spice`
directly. Meet the following specifications after parasitic extraction.
Maximize area utilization through compact placement and routing without
compromising process or electrical requirements.

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

FCT is a sampled-data charge-transfer circuit, not a continuous-time amplifier.
The fixed fixture applies a one-time 1 ns startup precharge. During each
subsequent `sam` phase it samples the input relative to `vcm` on two 400 fF
flying capacitors and precharges the fixture outputs to `vocm`. During
`transfer` it connects the flying capacitors to `vcm` and DUT `cinn/cinp`;
during `sample_out` it tracks `coutn/coutp` onto `voutn/voutp`, then releases
those held outputs.

- Use `tt`, `ss`, `ff`, `fs`, and `sf` process corners at 1.8 V and 27 C.
  This is the original deterministic global-corner specification; supply and
  temperature sweeps, mismatch, and passive process sweeps are not required.
- The two DUT supply pins share an external 1.8 V source. The two DUT ground
  pins share an external ground. The reference current is 50 µA.
  Input common mode is 1.0 V. The 0.9 V output precharge reference does not
  continuously regulate output common mode. Each fixture output load is 50 fF.
- Sampling rate is 900 MS/s. Use the fixed clock phases and edge timings in
  the supplied native fixtures without changing them.
- At every process corner, run both a 10 mV peak differential coherent sine
  at FFT bin 5 (140.625 MHz) and a 20 mV peak differential coherent sine at
  bin 3 (84.375 MHz). There are 10 required transients in total.
- Each transient runs 64 startup cycles and then measures exactly 32 coherent
  samples. Measure while tracking at 0.78 ns and after release at 0.88 ns
  relative to each scored cycle boundary. Gain, SFDR, common mode, and range
  use the held `voutp/voutn` samples at 0.88 ns.

At both input amplitudes and all five corners:

| Metric | Requirement |
|---|---|
| Sampled differential gain | 5.5–6.5 V/V |
| Sampled SFDR | ≥60 dB |
| Mean sampled output common mode | 0.3–1.2 V |
| Every sampled output voltage | 0.2–1.6 V |
| Normalized track-to-hold movement | ≤0.015 (1.5%) |
| Average total power delivered through powered DUT ports | 0–5 mW |

Remove the DC term only for the gain/SFDR FFT. Gain is the fundamental peak
of the 32-sample differential output divided by the commanded input peak.
SFDR is the fundamental-to-largest-other-non-DC-bin ratio, including the
Nyquist bin. If `d_track[k]` and `d_held[k]` are the differential samples at
0.78 ns and 0.88 ns, hold movement is
`sqrt(sum((d_track-d_held)^2) / sum(d_held^2))`.
It is movement across track-to-hold, not absolute settling to a commanded target.

Average power from cycle 64 through cycle 96. Sum power delivered by the common
DUT VDD source, the separate DUT `vcm`, `sam`, and `transfer` voltage sources,
and the 50 µA `ib` source. The VDD term includes both DUT supply pins.
Fixture-owned switches, references, precharge/hold paths, and stimulus sources
use separate sources and are excluded. The supplied fixtures preserve this
accounting. Both TT amplitudes and the remaining eight cases must pass.

## Environment

Run `source ./eda_env.sh`. Read `GUIDE.md` for native tool commands and
`DEVICE_API.md` for SKY130 device interfaces. You may write your own scripts.
`task/testbench/README.md` explains the supplied native fixtures.
Use the task's continuous SKY130 model entry and `ALB_NGSPICE_INIT`; do not
add a separate `scale` option to these continuous-model decks. Numeric device
dimensions use the model's micrometre parameter convention; the selected library
already sets `.option scale=1.0u` in `models_global.spice`.

Work offline using the provided files and installed software. Do not access
the network through browsers, web tools, shell commands, package managers, or
scripts. The harness model API connection is managed by the evaluation
infrastructure and is the only permitted network use.

## Deliverables

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

- Save `submission/layout.gds` with top cell `test_fct`.
- Save layout generation code under `submission/src/`.
- Keep temporary scripts, extraction outputs, and simulation logs under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_10mv_tt.spi`, `tb_20mv_tt.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
