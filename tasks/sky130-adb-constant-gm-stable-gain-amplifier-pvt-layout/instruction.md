[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a gain-stable differential amplifier

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `cgm_amp`, with ports in this order:
`vss iref vdd vinp vinn voutp voutn`.
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

The interface is `.subckt cgm_amp vss iref vdd vinp vinn voutp voutn`. The bench forces 50 uA into `iref`, uses 0.95 V input common mode, and loads each output with 500 fF.

All requirements apply at every Cartesian combination of tt, ff, ss; 1.62 V, 1.80 V, 1.98 V; and -40 C, 27 C, 125 C. A functionally valid submission runs independent operating-point/differential-AC, cold-start, and DC-linearity measurements at all 27 PVT points (81 serial ngspice runs). Nominal OP/AC and startup gates run first; a failed gate blocks the dependent matrix.

| Measurement | Requirement |
|---|---:|
| Differential gain at 1 MHz | 3.0-4.0 V/V |
| Gain max/min over PVT | at most 1.15 |
| -3 dB bandwidth, relative to the 1 MHz differential gain | at least 30 MHz |
| `VDD - Vout,CM` | 150-400 mV |
| Zero-input deterministic differential output imbalance | at most 10 mV |
| Incremental-gain error for a ±60 mV differential DC sweep | at most 8% |
| Total VDD power | at most 500 uW |
| Cold power-on startup | zero-input imbalance at most 10 mV; absolute post-startup step gain 3.0-4.0 V/V; `VDD - Vout,CM` 150-400 mV before and after the step |

The output-imbalance requirement detects deterministic imbalance from unequal devices, loads, biasing, or connectivity at zero differential input. This task does not claim statistical mismatch or Monte Carlo offset coverage.

The startup experiment uses `uic` from an explicit zero-energy state. VDD and the input common mode remain at 0 V through 0.1 us and ramp to their declared values by 1.1 us. IREF remains 0 A through 1.2 us and ramps to 50 uA by 1.22 us. The differential input remains zero through 10 us, then ramps to +20 mV by 10.02 us. Zero-input output imbalance and common mode are averaged from 8-9 us; the absolute post-step differential output and common mode are averaged from 14-15 us. The startup gain is the absolute post-step differential output divided by 20 mV, not a before/after subtraction, so a persistent differential error cannot cancel out.

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

- Save the layout as `submission/layout.gds`, with top cell `cgm_amp`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete SPEC above, including its PVT, load and statistical requirements, remains the design target without reduction.
Electrical evaluation runs only the conditions, stimuli and analyses explicitly present in the public testbenches `tb_lin.spi`, `tb_pvt.spi`, `tb_startup.spi`; other operating points are not expanded automatically. Post-layout evaluation uses those same conditions with the extracted DUT.
Only requirements covered by these tests are scored. Uncovered full-range properties and multi-sample statistics are reported as unassessed; passing these tests does not establish compliance with the complete SPEC. DRC, LVS and deliverables are unchanged.
