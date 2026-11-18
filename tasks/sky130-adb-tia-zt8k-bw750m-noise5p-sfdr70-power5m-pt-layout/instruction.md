[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# SKY130 layout: tia-zt8k-bw750m-noise5p-sfdr70-power5m-pt

The English version is authoritative. Create a fully routed layout for the
fixed circuit in `task/circuit.spice`. Preserve topology, device models,
dimensions, multiplicities, connections and body terminals.
Top cell: `tia`. Port order: `IREF IN VCM VDD VOUT VSS`.
The fixed derivative replaces the four ideal resistors with native high-poly and extra-high-poly devices; original MOS cards and topology are unchanged. Its selected binned model entry defines these fixed-width resistor families. Preserve the supplied device models and geometry.

Pass the installed DRC and LVS checks and the stated post-extraction electrical
acceptance cases. Maximize area utilization through compact placement and routing
while meeting process and electrical requirements.

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

## Electrical acceptance in this version

Electrical acceptance in this benchmark version uses the three published TT/1.80 V/27°C fixtures below. The published SFDR fixture applies 100 MHz and 10 µA peak, the specified condition. Passing the public cases does not establish all 15 process-temperature points.

| Native fixture | Acceptance case |
|---|---|
| `tb_ac_tt.spi` | `ac_power__tt__27` |
| `tb_noise_tt.spi` | `noise__tt__27` |
| `tb_sfdr_tt.spi` | `sfdr__tt__27` |

## Original electrical design specifications

The complete source requirements below are retained as the design targets.
The acceptance scope above explicitly states which conditions this version tests;
it does not certify untested conditions. This is the original source's Spec
section verbatim; its schematic-only scope and internal sizing freedom describe
the source task. This layout task instead fixes the supplied physical netlist
and evaluates the listed public fixtures after extraction.

Implement `.subckt tia IREF IN VCM VDD VOUT VSS`. The verifier runs the complete 15-point Cartesian product of five process corners (`tt`, `ff`, `ss`, `fs`, `sf`) and three temperatures (-40 C, 27 C, 85 C), all at `VDD = 1.80 V`. It supplies `IREF = 20 uA`, drives `VCM` at 0.90 V, places 0.3 pF from `IN` to `VSS`, and places 0.2 pF from `VOUT` to `VSS`. The 0.3 pF input capacitance is the published receiver-front-end fixture; no external photodiode capacitance is added.

Official Sky130 PDK subcircuits and finite positive resistors are admitted in the DUT. Local hierarchy is allowed. The generic circuit checker enforces only this element policy, not a particular TIA topology.

Every process-temperature point must meet every requirement:

- **Transimpedance magnitude at 1 MHz:** greater than 8 kOhm.
- **Upper -3 dB bandwidth:** greater than 750 MHz relative to the 1 MHz transimpedance. A response still above that level at the 10 GHz check point is reported as at least 10 GHz.
- **Input-referred current-noise density:** less than 5 pA/sqrt(Hz) everywhere in the published 10 MHz–500 MHz receiver noise band.
- **Integrated input-referred current noise:** less than 0.10 uA rms over that same 10 MHz–500 MHz receiver noise band. This application noise band is intentionally narrower than the 750 MHz small-signal bandwidth target; the remaining bandwidth is transition margin rather than an undeclared noise-integration extension.
- **Large-signal SFDR:** greater than 70 dBc for a 100 MHz, 10 uA-peak sinusoidal input current. The verifier observes the final 16 coherent cycles, uniformly resamples 1024 points per cycle, and defines SFDR as the fitted fundamental FFT line divided by the largest remaining non-DC line. The fitted fundamental transimpedance must also remain greater than 8 kOhm.
- **Total externally supplied DC power:** less than 5 mW. The measurement sums the absolute DC power at `VDD` and `VCM`; the 20 uA `IREF` path is already supplied through `VDD`.

This signoff excludes supply-voltage variation, external photodiode capacitance, extracted interconnect parasitics, and statistical mismatch.

## Environment and deliverables

Run `source ./eda_env.sh`. Read `GUIDE.md`, `DEVICE_API.md`, and
`task/testbench/README.md` for native tools, device interfaces and static fixtures.
You may write your own scripts. Work offline with the provided files, installed
software and local documentation; do not use network access from shell commands,
package managers, scripts or web tools. Only the infrastructure's model API
connection is permitted.

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

Save `submission/layout.gds` with top cell `tia` and generation code in
`submission/src/`. Use `work/` for temporary files. The external loads, stimulus,
bias sources and measurement fixtures belong to the testbench, not the layout.
