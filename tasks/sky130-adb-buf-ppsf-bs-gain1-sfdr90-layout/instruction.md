[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a differential push-pull source-follower buffer

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `buf_ppsf_bs`, with ports in this order:
`IREF VCM VDD VIN VIP VON VOP VSS`.
Preserve topology, connections, device models, dimensions, and multiplicity.
Preserve every MOS body connection, including independent NMOS body nets.
The external sources, bias, common-mode reference, and output loads are test
conditions and are not part of the DUT layout.

The eight internal resistors use `sky130_fd_pr__res_generic_po`, each with
`w=0.33 l=5684.65` in micrometres. The eight internal capacitors use
`sky130_fd_pr__cap_mim_m3_1`, each with `w=49.85 l=49.85` in micrometres.
These physical model names and dimensions are fixed.
Use the installed KLayout DRC rules and the native **Magic + Netgen LVS** route
in `GUIDE.md`, comparing directly with `task/circuit.spice`.

The layout must pass DRC and LVS and meet the following electrical specifications
after parasitic extraction. Maximize area utilization with compact placement and
routing while preserving the process and electrical requirements.

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

The electrical conditions and limits retain the source benchmark's specification.

- Check all five SKY130 process corners: `tt`, `ff`, `ss`, `fs`, and `sf`.
  Supply is 1.80 V and temperature is 27 C. Supply 20 uA into `IREF`, hold
  `VCM` at 0.90 V, drive `VIN` and `VIP` differentially with a 0.8 V-peak
  differential sine, and connect 1 pF from each output to ground.
- At 40 MHz, the magnitude of the differential AC input current
  `|I(VIP)-I(VIN)|` must be **less than 20 uA** under the 0.8 V-peak differential
  AC drive, in every process corner. A missing or nonfinite measurement fails.
- Differential AC gain magnitude must be **greater than 0.99 V/V** at every
  sampled point from 1 MHz through 40 MHz, in every process corner.
- Large-signal SFDR must be **greater than 90 dB at 1 MHz, 80 dB at 11 MHz,
  and 70 dB at 41 MHz** in every corner. Fundamental differential gain must
  also be **greater than 0.95 V/V** at every one of these 15 conditions.
  Use the full-Nyquist rectangular-window spectrum definition in
  `task/testbench/README.md`.
- Total externally supplied DC power must be **less than 1 mW** in every
  process corner. Sum the absolute DC power at `VDD`, `VCM`, `VIN`, and `VIP`.

All conditions must pass. Supply-voltage variation, temperatures other than
27 C, and statistical mismatch are outside this task's specified matrix.

## Environment

Run `source ./eda_env.sh`. `GUIDE.md` documents native checking, extraction, and
simulation commands; `DEVICE_API.md` describes the installed device interfaces.
You may write your own layout and checking scripts.
Native testbenches and exact measurement definitions are in
`task/testbench/README.md`.

Use the task's original continuous model library selected by `ALB_MODEL_LIB`
and the qualified initialization in `ALB_NGSPICE_INIT`. Keep this selection
for both pre-layout and post-layout simulation. Numeric device dimensions are
in micrometres as expected by these models; preserve the supplied testbench
scaling and initialization.

Work offline using the provided files, installed software, and local documentation.
Do not access the network through browsers, web tools, shell commands, package
managers, or scripts. The harness's model API connection is managed by the
evaluation infrastructure and is the only permitted network use.

## Deliverables

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

- Save `submission/layout.gds` with top cell `buf_ppsf_bs`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_ac_power.spi`, `tb_sfdr.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
