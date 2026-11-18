[English](instruction.md) | [简体中文](instruction.zh-CN.md)

# Layout a regulated 10 MHz charge pump

The English version is authoritative.

Create a fully routed SKY130 layout for the fixed circuit in `task/circuit.spice`.
The top-level subcircuit is `charge_pump_regulated`, with ports in this order:
`AVDD AVSS CLK EN IBN1U VOUT`.
Preserve the circuit hierarchy or its electrically equivalent flattening, topology,
device models, connections, dimensions, and multiplicities. The supplies, clock,
enable sources, external bias currents, and output loads belong to the testbench
and are not part of the DUT layout.

The fixed source already uses physical SKY130 devices. In particular, keep the
`sky130_fd_pr__res_xhigh_po` resistors at `w=0.69` and their specified lengths,
the `sky130_fd_pr__nfet_05v0_nvt` native devices, and the MIM capacitor sizes.
The supplied `task/lvs_reference.spice` expresses these same devices in the
installed LVS reader's syntax; it is for LVS, not simulation. Use
`task/circuit.spice` or the extracted DUT for simulation.

For these 0.69 µm xhigh-poly resistors, the installed Magic generator can emit a
1.09 µm-wide URPM marker, whereas the installed DRC rule `MR_urpm.WID.1` requires
at least 1.27 µm. Enlarge the URPM marker to satisfy that rule while preserving
the resistor body's fixed width 0.69 µm and lengths 50/80 µm. This is a marker
geometry adjustment, not permission to resize the electrical resistor or modify
the PDK generator.

The layout must pass DRC and LVS using the installed SKY130 decks and meet the
electrical requirements after parasitic extraction. Maximize area utilization
by keeping placement and routing compact without compromising process or
electrical requirements.

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

Evaluation uses a deterministic representative PVT/load set rather than the full Cartesian product. Across the set it covers all five process corners, all three declared supplies and temperatures, and all three enabled loads:

- `tt`, 1.80 V, 40 C at 1 uA, 25 uA, and 50 uA.
- `ss`, 1.62 V, 125 C at 50 uA.
- `ff`, 1.62 V, 125 C at 1 uA.
- `ff`, 1.98 V, -10 C at 50 uA.
- `sf`, 1.98 V, -10 C at 1 uA.
- `fs`, 1.62 V, 125 C at 50 uA.

This is eight enabled operating points. Power-down current is a static specification, so it is measured by DC operating-point analysis at five leakage-oriented points: `tt`/1.80 V/40 C, `ss`/1.62 V/125 C, `ff`/1.98 V/125 C, `sf`/1.62 V/125 C, and `fs`/1.98 V/125 C. This coverage is representative signoff and does not claim full Cartesian PVT qualification.

`CLK` is a fixed 10 MHz rail-to-rail square wave with 1 ns rise and fall times and 50% duty cycle. The finite public edge rate avoids treating the external clock as an unattainable impulse while preserving the captured clock frequency. The clock and enable controls each drive the DUT through 50 ohm source resistance. Each `IBN1U` receives 1 uA from its corresponding supply before the supply-current sense element. Every output drives 1 nF to ground; enabled outputs also drive their specified constant load current. A 200 us transient is simulated, and every metric uses the 190--200 us interval.

- Enabled mean `VOUT` must be within 5% of `1.3*VDD` at every declared enabled operating point.
- Enabled output ripple, `max(VOUT)-min(VOUT)`, must be at most 5 mVpp.
- Enabled average current through the `AVDD` pin must be at most 200 uA.
- Disabled average current through `AVDD` with `EN=0` must be at most 100 nA.

Enabled transient and disabled DC benches use separate supplies and sense elements. Bias-source current is outside the declared `AVDD`-pin current metric. Other clock rates, unlisted PVT/load combinations, regulation dynamics, efficiency, and statistical mismatch are outside this task's declared scope. Meeting the final-window limits also demonstrates that the enabled output has reached the required operating range by 200 us.


## Environment

Run `source ./eda_env.sh` in the workspace. Read `GUIDE.md` for native EDA
commands and `DEVICE_API.md` for the installed SKY130 device interfaces.
You may write your own layout, checking, and simulation scripts.

The native testbench and its command are in `task/testbench/README.md`.
`ALB_MODEL_LIB` selects this task's original continuous SKY130 model library.
Use `ALB_NGSPICE_INIT` as described in `GUIDE.md`; this task does not enable
`ngbehavior=hsa`. Numeric device dimensions use micrometres with
`.option scale=1e-6`.

Work offline using the supplied files, installed software, and local documentation.
Do not access the network through browsers, web tools, shell commands, package
managers, or scripts. The harness's model API connection is managed by the
evaluation infrastructure and is the only permitted network use.

## Deliverables

Save the generated layout to `submission/layout.gds` early and keep it updated as you iterate, even if DRC, LVS, or post-layout simulation has not yet passed, so the current layout remains available for evaluation when your run ends.

- Save the layout as `submission/layout.gds`, with top cell `charge_pump_regulated`.
- Save the layout generation code under `submission/src/`.
- Keep temporary files and diagnostic output under `work/`.

## Evaluation coverage in this release

The complete original SPEC above remains the design target. This release evaluates
only the supplied public `tb_charge_pump_regulated_ff_hot.spi`: one 200 us
transient at FF, 1.98 V and 125 C, containing an enabled instance with a 50 uA
load and an unloaded disabled instance. Both receive the same running 10 MHz
clock. Measurements use 190--200 us. Post-layout evaluation uses this exact
fixture with the extracted DUT.

At this selected public point, the release checks enabled mean VOUT against
2.4453--2.7027 V, ripple against 5 mVpp, absolute enabled AVDD current against
200 uA, and absolute disabled AVDD transient-average current against 100 nA.
The latter is a check of this public transient, not the original static/DC
power-down measurement. The enabled FF/1.98 V/125 C/50 uA stress point is also
outside the original eight-point enabled signoff set. These distinctions are
retained explicitly; passing this public fixture does not prove the original
disabled DC specification or the complete PVT/load requirements. The original
thirteen signoff cases are not expanded or executed automatically in this release.
DRC, LVS, and deliverables are unchanged.
