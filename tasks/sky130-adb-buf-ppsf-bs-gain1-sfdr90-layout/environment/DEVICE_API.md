[English](DEVICE_API.md) | [简体中文](DEVICE_API.zh-CN.md)

# SKY130 Device API

The English version is authoritative. The Chinese version is a translation.

This document describes native discovery, device parameters, contacts, geometry units,
and layers for SKY130 tasks. Factory availability is distinct from process-rule validity,
LVS recognition, and a task's permitted physical implementation.
Run `source ./eda_env.sh` in the workspace before importing it. The package is installed at
`/opt/analog-layout/pdks/sky130/python/sky130`.

`import sky130` loads the installed `gdsfactory/skywater130` device library.
The SKY130 technology distributed through open_pdks also supplies native Magic
generators, described below; some resistor families use that interface in this
environment. FOSSI `sky130_klayout_pdk` supplies the installed KLayout rules. This task uses its DRC rules and selects Magic + Netgen for LVS, as documented in GUIDE.md.
Its separate PCell library is not installed here. Sharing the SKY130 process
does not make these generator APIs interchangeable.

## Official Process Reference (Optional)

The original SKY130 process documentation is installed under
`/opt/analog-layout/pdks/sky130/docs/skywater-pdk/`. Its RST, CSV and TSV files are
plain text and can be read or searched directly; referenced tables and figures
are included.

- `rules.rst`: chapter contents.
- `rules/device-details.rst`: MOS, resistor, capacitor and BJT device descriptions.
- `rules/layers.rst` and `rules/gds_layers.csv`: layer definitions and GDS mapping.
- `rules/periphery.rst`, `rules/periphery-rules.rst` and `rules/summary.rst`: process rules.

These are upstream process/device reference documents. The installed PCell API,
model entry points and verification decks have their own fixed versions; query
PCell parameters as shown below and use the task-selected simulation model.

## Native offline queries

Use the installed Python and Magic interfaces directly; these queries need no network access.
In a task workspace, first run `source ./eda_env.sh`. In an image shell without a task workspace,
run `source /opt/analog-layout/env.sh` and use the installed PDK Python path shown above.

```bash
python - <<'PY'
import inspect
import pkgutil
import sky130

sky130.PDK.activate()
print(sky130.__file__)
print([m.name for m in pkgutil.iter_modules(sky130.pcells.__path__)])
print([n for n in dir(sky130.pcells) if n.startswith("sky130_fd_pr__")])
print([n for n in sorted(sky130.PDK.cells) if "cap_" in n or "res_" in n])
factory = sky130.pcells.sky130_fd_pr__res_generic_po
print(inspect.signature(factory))
help(factory)
PY
```

`sky130.PDK.cells` is the active cell registry, including parameterized and fixed cells.
`sky130.cells` is also a registry dictionary; the generated fixed-cell Python module is
available as `sky130.components`. A registered name, a SPICE model, a successfully generated
component, and a device recognized by the installed LVS deck are separate facts.
`inspect.signature` and `help` expose arguments without reading the implementation.

## Native Magic generators

Magic supplies another native interface to the installed SKY130 technology. Its parameter
names belong to Magic, not gdsfactory. Query an exact generator's defaults and then call
`magic::gencell` with an instance name and parameter/value pairs:

```bash
mkdir -p work/magic-device
(
  cd work/magic-device
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
set generator sky130::sky130_fd_pr__nfet_01v8
puts [info args magic::gencell]
puts [info procs ${generator}_defaults]
puts [${generator}_defaults]
drc off
load native_device
box values 0 0 0 0
magic::gencell $generator M0 w 2 l 0.5 nf 4 m 1 guard 1 doports 1
select top cell
gds write native_device.gds
quit -noprompt
TCL
)
```

For a direct MOS `gencell` call, `w` is the width **of one finger**, in µm. The example
contains four 2 µm fingers, a total width of 8 µm. The separate native `_convert` procedure
accepts SPICE-style parameters and divides total width by `nf`; do not convert twice.
Gates and source/drain contacts still need circuit wiring. Query `conn_gates` and the other
defaults before assuming contacts are joined. GDS export/import does not create gf ports.

The same query pattern applies to standard/LVT 1.8 V MOS, the installed 5 V MOS variants,
`diode_pw2nd_05v5`, `diode_pd2nw_05v5`, `res_generic_po`, `res_generic_m1`,
fixed-width high/xhigh poly resistors, `cap_mim_m3_1`, `cap_mim_m3_2`, and `cap_var_lvt`. Prefix these names with
`sky130::sky130_fd_pr__`. Use each generator's own defaults rather than reusing MOS
parameters for another device family. A successful process exit alone does not prove
generation succeeded: inspect the log and ensure the exported cell has geometry.

For the two-terminal `sky130_fd_pr__res_generic_po` model, a native Magic example
is shown below. `w` and `l` are physical dimensions in µm, not a resistance in ohms.
Use the model and dimensions fixed by the task netlist. This family is different
from the three-terminal fixed-width precision-poly resistors described later.

```tcl
set generator sky130::sky130_fd_pr__res_generic_po
puts [${generator}_defaults]
load generic_resistor
box values 0 0 0 0
magic::gencell $generator R0 w 1.00 l 35.25 m 1 nx 1 guard 0 doports 1
select top cell
gds write generic_resistor.gds
```

Run these Tcl commands in a Magic session started with the startup file above.
Import its GDS with `gf.import_gds`; inspect the actual geometry and labels before
routing. Keep the generic-poly model name and W/L in the LVS reference.

Inspect the exact instance that will be routed, including its transformed coordinates:

```bash
python - <<'PY'
import gdsfactory as gf
import sky130

sky130.PDK.activate()
device = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True,
)
layout = gf.Component("device_api_example")
ref = layout.add_ref(device)
ref.drotate(90)
ref.dmove((10, 10))
print(device.info)
print("dbu_um:", device.kcl.dbu, "geometry_layers:", device.layers)
print("instance_bbox_um:", ref.dbbox())
for port in ref.ports:
    print(port.name, port.dcenter, port.dwidth, port.orientation,
          gf.get_layer_tuple(port.layer), port.port_type)
print("M1:", gf.get_layer_tuple(sky130.LAYER.met1drawing))
print([(name, gf.get_layer_tuple(layer))
       for name, layer in sky130.LAYER.__members__.items()
       if name.endswith("drawing")])
PY
```

`ports` is an iterable container indexed by port name, not a `dict`; it has no `.items()`.
Use `{p.name: p for p in ref.ports}` if a mapping is useful. Port metadata describes routing
anchors; it does not create conductors, contacts, buses, or GDS labels. Some factories below
inherit `port_type="optical"` even though they generate electrical devices, so filtering only
for electrical port type can omit their contacts. Inspect names and layers explicitly.
A port center or width alone does not prove that every metal edge lies on the manufacturing
grid. Check the geometry and DRC after placement and routing.

## Standard and LVT 1.8 V MOS devices

- `sky130_fd_pr__nfet_01v8`
- `sky130_fd_pr__pfet_01v8`
- `sky130_fd_pr__nfet_01v8_lvt`
- `sky130_fd_pr__pfet_01v8_lvt`

`gate_width` is the requested width per finger in µm; the nominal total width is
`gate_width * nf`. Use a positive integer for `nf`. For the standard/LVT 01v8 SPICE
subcircuits, netlist `w` is the total width across `nf`, not the per-finger PCell width.
After interpreting the netlist's scale and units, set `gate_width = W_total_um / nf`.
For example, total `w=8 µm`, `l=.5 µm`, and `nf=4` correspond to
`gate_width=2.0, gate_length=.5, nf=4`. SPICE instance multiplier `m` is separate
from `nf`; do not multiply or divide by the finger count twice. Do not infer
nominal multiplicity from a parameter named `mult`: in the installed standard
1.8 V MOS, MIM, and PNP simulation wrappers it is used for statistical mismatch.
The Python factory's `mult` argument is a separate interface, described below.
All four upstream factories publish only these four ports:

| Port | Meaning | Layer |
|---|---|---|
| `GATE` | Center of the first gate finger | poly `(66,20)` |
| `DRAIN` | Center of the leftmost diffusion contact column | LI1 `(67,20)` |
| `SOURCE` | Center of the rightmost diffusion contact column | LI1 |
| `BODY` | Metadata at `(0, -(gate_width/2 + gate_to_polycont))`; `gate_to_polycont` is `.275` for NMOS and `.32` for PMOS | LI1 |

`BODY` is published even with `guard_ring=False`. Its name, layer, and position do not
guarantee a physical body contact at that point. With a guard ring, inspect the ring's
actual tap/LICON/LI geometry to choose a body connection; without one, provide the
required body connection in the enclosing layout. A connection to M1 also needs the
appropriate LI–M1 contact and enclosing conductors.
Port coordinates are in µm. For rotated, moved, or mirrored components, use the instance's `ports`.

For `nf` fingers, the geometry contains `nf+1` diffusion contact columns and separate
gate fingers. The four ports do not enumerate these contacts or connect them into buses.
For parallel fingers, connect alternating diffusion columns to the two source/drain nets
and connect all gates according to the netlist. With even `nf`, the two outer diffusion
columns belong to the same alternating group: the names `DRAIN` and `SOURCE` alone do
not define the correct multi-finger wiring. Inspect the geometry for the remaining
contacts. Port metadata does not create conductors or GDS text labels.

```python
from sky130.pcells.mosfets import sky130_fd_pr__nfet_01v8_lvt

device = sky130_fd_pr__nfet_01v8_lvt(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True
)
assert {p.name for p in device.ports} == {"GATE", "SOURCE", "DRAIN", "BODY"}
for port in device.ports:
    print(port.name, port.dcenter, port.dwidth)
```

These are upstream port names, not a complete physical-terminal map.

## Reserved and unimplemented options

The four factories accept these arguments but do not implement the requested changes.
They do not explicitly reject nondefault values:

| Parameter | Default | Upstream behavior |
|---|---|---|
| `dnwell` | `False` | Unused; setting it does not generate an isolated deep N-well |
| `mult` | `1` | Reserved; still generates one device. Place and connect multiple instances when required |
| `sd_width` | `0.28` | Reserved; does not affect the generated geometry |
| `end_cap` | `0.13` | Reserved; does not affect the generated geometry |

Choose finite positive dimensions and a positive integer finger count; the upstream
factories do not provide a dedicated validation contract for these conditions. Downstream
Python, geometry, or port errors are not a substitute for process-rule checks.
The option behavior above is verified for the four listed factories; inspect other variants separately.

## Other MOS generators

The following factories are also exported from `sky130.pcells` and
`sky130.pcells.mosfets`. They accept the same parameter names as the MOS signature below;
these are their actual default widths and lengths in µm, not task specifications.

| Factory | `gate_width` | `gate_length` | `sd_width` |
|---|---|---|---|
| `sky130_fd_pr__pfet_01v8_hvt` | `.42` | `.15` | `.28` |
| `sky130_fd_pr__nfet_03v3_nvt` | `.42` | `.50` | `.28` |
| `sky130_fd_pr__nfet_05v0_nvt` | `.42` | `.90` | `.28` |
| `sky130_fd_pr__nfet_g5v0d10v5` / `sky130_fd_pr__pfet_g5v0d10v5` | `.42` | `.50` | `.28` |
| `sky130_fd_pr__nfet_20v0` / `sky130_fd_pr__pfet_20v0` | `.42` | `2.0` | `.50` |

Their default components expose `GATE` on poly `(66,20)` and `SOURCE`, `DRAIN`, `BODY`
on LI `(67,20)`. These are metadata entries, not a complete physical-terminal map.
A `BODY` name does not establish that a separate body contact was created.
Inspect the requested parameter combination and its geometry before connecting it.
Default generation has been checked; this is not DRC/LVS qualification for arbitrary
parameters or a claim that every generator implements every argument.

## Resistors, MIM capacitors, diodes, and BJTs

All factories in this table are exported from `sky130.pcells`; the module column gives an
alternative direct import. Dimension arguments are in µm. Parameters are geometric dimensions,
not resistance in ohms or capacitance in farads. Their relation to a required electrical value
must follow the task's specified physical device and model.

| Module under `sky130.pcells` | Factory | Dimension defaults | Published ports and layers |
|---|---|---|---|
| `resistors` | `sky130_fd_pr__res_generic_po` | `res_width=.33, res_length=1.65` | `PLUS`, `MINUS`: M1 `(68,20)` |
| `resistors` | `sky130_fd_pr__res_generic_nd` | `res_width=.42, res_length=2.10` | `PLUS`, `MINUS`: M1 |
| `resistors` | `sky130_fd_pr__res_high_po_0p35` | `res_width=.35, res_length=.50` | `PLUS`, `MINUS`: M1 |
| `resistors` | `sky130_fd_pr__res_high_po` | Direct alias of `sky130_fd_pr__res_high_po_0p35` | Same ports |
| `capacitors` | `sky130_fd_pr__cap_mim_m3_1` | `cap_width=2.0, cap_length=2.0` | `BOTTOM`: M3 `(70,20)`; `TOP`: M4 `(71,20)` |
| `capacitors` | `sky130_fd_pr__cap_mim_m3_2` | `cap_width=2.0, cap_length=2.0` | `BOTTOM`: M4; `TOP`: M5 `(72,20)` |
| `diodes` | `sky130_fd_pr__diode_pw2nd_05v5` | `diode_width=.45, diode_length=.45` | `CATHODE`: M1; `ANODE`: LI `(67,20)` |
| `diodes` | `sky130_fd_pr__diode_pd2nw_05v5` | `diode_width=.45, diode_length=.45` | `ANODE`: M1; `CATHODE`: LI |
| `bjts` | `sky130_fd_pr__npn_05v5` | `emitter_width=1.0, emitter_length=1.0` | `EMITTER`, `BASE`, `COLLECTOR`: LI |
| `bjts` | `sky130_fd_pr__pnp_05v5` | `emitter_width=.68, emitter_length=.68` | `EMITTER`, `BASE`, `COLLECTOR`: LI |

Both BJT factories additionally accept `base_ring_width=.4`, `np_spacing=.27`,
`sdm_enclosure=.125`, `nwell_enclosure=.18`, and `li_enclosure=.08`.
The resistor, MIM, and BJT factories currently report `port_type="optical"`; the diode
factories report `"electrical"`. These metadata types do not change their physical layers.
The upstream generic-poly resistor uses `polyres` `(66,13)` over its body; the high-poly
resistor uses `rpmdrawing` `(86,20)`. A factory name does not establish which resistor
model the installed extraction deck will recognize from those layers.

Resistor ports do not include a body/guard contact. The P+/N-well diode also has an outer
substrate ring without a published substrate port. Connect any required body or substrate
contacts using the actual geometry. MIM components are asymmetric: the lower-plate port is
on the lower metal, and an additional upper-metal pickup for that plate is on the right.
Do not infer terminal position from the component bounding box. Their Python port names
are `TOP/BOTTOM`, while their existing GDS labels are `C1/C2`; use the actual extracted
netlist and task port declarations when mapping terminals.

There is a known limitation in the current default `sky130_fd_pr__npn_05v5` geometry:
its `BASE` and `COLLECTOR` metadata points lie on the same merged LI region, and the
collector strip does not provide a separate tap/LICON contact stack. It cannot be treated
as a verified independent three-terminal implementation. This observation comes from
geometry inspection, not an LVS run. The PNP's default ports lie on separate LI regions,
which also does not establish DRC/LVS validity. For all these device classes, successful
factory calls and the presence of matching SPICE names do not establish LVS compatibility.

### Fixed BJT cells

The native PDK registry also contains fixed foundry BJT layouts. For example:

```python
import gdsfactory as gf
import sky130

sky130.PDK.activate()
print([n for n in sorted(sky130.PDK.cells) if "rf_npn" in n or "rf_pnp" in n])
npn = gf.get_component("sky130_fd_pr__rf_npn_05v5_W1p00L1p00")
pnp = gf.get_component("sky130_fd_pr__rf_pnp_05v5_W0p68L0p68")
print(npn.dbbox(), pnp.dbbox())
print([(t.string, t.x, t.y) for t in pnp.get_labels((67, 5), recursive=True)])
```

These fixed cells have no gf ports. The PNP carries native LI labels `Base`, `Collector`,
and `Emitter`; this NPN has no equivalent terminal labels. Determine contacts from the
geometry and extraction, and preserve the declared model, emitter size and bulk terminal.
The native Magic BJT generator requires its fixed library cell to be loaded; the installed
RF GDS can be imported with Magic's `gds read` before invoking that generator. Do not
assume the corresponding `.mag` file exists solely because a Tcl procedure is listed.

### MIM dimensions

`cap_width` and `cap_length` describe the effective capm rectangle, not the component
bounding box or its pickup metal. For a rectangular plate, geometric area is `W*L` in
µm² and perimeter is `2*(W+L)` in µm. The fixed LVS deck compares these geometric
parameters; the electrical capacitance comes from the task-selected SPICE model.
Use the supplied reader-only LVS reference when present, without replacing its geometric
parameters by capacitance values. Array multiplicity and model mismatch parameters have
different meanings; preserve the netlist's parameters.

The native Magic MIM generator currently clamps `w` and `l` to its 2–30 µm limits.
This is a generator limit, not a process-wide maximum. The Python MIM factory has a
different interface; inspect the actual generated size and verify it before use.

## Native Magic precision-poly resistor interface

The installed Magic SKY130 PDK provides named PCells for the fixed-width P+ precision
resistors. Use the generator whose name matches the fixed netlist model:

| Magic generator and SPICE model | Fixed width `w` (µm) |
|---|---:|
| `sky130_fd_pr__res_high_po_0p35` | 0.35 |
| `sky130_fd_pr__res_high_po_0p69` | 0.69 |
| `sky130_fd_pr__res_high_po_1p41` | 1.41 |
| `sky130_fd_pr__res_high_po_2p85` | 2.85 |
| `sky130_fd_pr__res_high_po_5p73` | 5.73 |

The corresponding five `sky130_fd_pr__res_xhigh_po_*` native generators use the same
fixed-width suffixes. High and xhigh are different device models, not interchangeable
names; use the family specified in the task netlist.

Magic's `l` is the resistor body length in µm between the inner ends of the slotted
contacts. The fixed-width SPICE models take `l`; their width is determined by the model
name. Use the dimensions in the netlist. Electrical resistance depends on the model,
temperature, and process conditions; it is not simply an ideal value assigned to a shape.
`m` and `nx` control the number of generated elements along the two array directions;
keep them at 1 for a single resistor. `guard=1` creates a substrate guard contact, and
`doports=1` creates device labels. Connect that contact to the netlist's bulk node.

The Python `sky130_fd_pr__res_high_po` alias points only to the Python `0p35` factory.
Changing its `res_width` is not a supported selection interface for the other fixed-width
families. The native Magic interface below provides the named `1p41` generator directly.

For native `res_high_po_0p35` geometry, check the RPM implant layer `(86,20)`:
the installed DRC rule `MR_rpm.WID.1` requires a width of at least 1.27 µm.
The native Magic generator can produce a 0.75 µm RPM strip. Enlarge that mask
as necessary while preserving the specified resistor poly width, electrical
length and terminal connections, then rerun DRC and LVS.

This standalone example uses `w=1.41`, `l=42.36`, a size checked with the installed DRC,
LVS, and Magic extraction tools. Replace the model and dimensions according to the task;
the example is not a universal resistor value or a circuit layout solution.
Run from the task workspace after `source ./eda_env.sh`:

```bash
mkdir -p work/precision-res-example
(
  cd work/precision-res-example
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
puts [info procs sky130::*res_high_po*_defaults]
puts [sky130::sky130_fd_pr__res_high_po_1p41_defaults]
drc off
load precision_res_example
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 R0 \
    w 1.41 l 42.36 m 1 nx 1 guard 1 doports 1
select top cell
save precision_res_example
gds write precision_res_example.gds
quit -noprompt
TCL
)
```

`_defaults` returns the native parameter dictionary; the query above needs no source-code
inspection. `magic::gencell` receives the generator, a nonempty instance name, and
parameter/value pairs. `drc off` disables Magic's interactive background checker while
drawing; use the independent DRC and LVS commands in `GUIDE.md` after generation.
The GDS can be imported into a gdsfactory design:

```python
import gdsfactory as gf
import sky130

sky130.PDK.activate()
resistor = gf.import_gds("work/precision-res-example/precision_res_example.gds")
print([(t.string, t.x, t.y)
       for t in resistor.get_labels((67, 5), recursive=True)])
layout = gf.Component("precision_res_import_example")
ref = layout.add_ref(resistor)
ref.dmove((10, 10))
```

The printed coordinates are in the imported component's coordinate system, before the
instance move. GDS preserves geometry, hierarchy, and labels; this import does not create
gdsfactory `Port` objects. Locate actual contacts from the geometry and labels, applying
the instance transform when routing.

| Native label on LI `(67,5)` | SPICE terminal in the precision-resistor subcircuit |
|---|---|
| `R1` | `r0`, first resistor terminal |
| `R2` | `r1`, second resistor terminal |
| `B` | `b`, substrate/bulk terminal |

For example, `XR0 net_a net_b vss sky130_fd_pr__res_high_po_1p41 l=42.36`
connects `R1` to `net_a`, `R2` to `net_b`, and `B` to `vss`. Flattened extraction may
prefix these labels with the instance name, such as `R0.R1`. This example was extracted
as `sky130_fd_pr__res_high_po_1p41 l=42.36`; no replacement model or modified PDK is needed.
Preserve the required bulk connection and rerun checks after placement and routing.

## MOS capacitors and varactors

The installed Python package provides MIM factories and fixed VPP capacitor cells, but no
`cap_var`, `cap_mos`, `cap_nfet`, or `cap_pfet` layout factory in `sky130.pcells` or
`sky130.PDK.cells`. Query the registry before assuming a model name is a Python function.

The installed Magic technology does provide native Tcl generator procedures for
`sky130_fd_pr__cap_var_lvt`, `sky130_fd_pr__cap_var_hvt`, and `sky130_fd_pr__cap_var`.
Their `_draw` procedures take a `parameters` dictionary; `_defaults`, `_convert`, and
`_check` procedures expose the native parameter handling. Query them offline:

```bash
magic -dnull -noconsole \
  -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
puts [info procs sky130::*cap_var*_defaults]
puts [info args sky130::sky130_fd_pr__cap_var_lvt_draw]
puts [sky130::sky130_fd_pr__cap_var_lvt_defaults]
quit -noprompt
TCL
```

LVT/HVT defaults include `w=1.0`, `l=.18`, `nf=1`, `m=1`, and `guard=1`;
the ordinary `cap_var` default length is `.50`. Other contact/coverage options are shown
by `_defaults`; their names and behavior belong to the Magic interface, not the Python
MOS factory. The LVT drawing procedure uses Magic types `var`, `nnd`, `nsc`, `poly`, `pc`,
`nwell`, and `psub`. It does not publish Python `Port` objects or inherit the four-MOS
port names. The default dictionaries do not request `doports`; inspect generated labels
and physical contacts before defining task ports.

The ngspice model tree contains `sky130_fd_pr__cap_var_lvt` and `...__cap_var_hvt` with
SPICE terminal order `c0 c1 b` and parameters `w`, `l`, `vm`; these logical terminals are
not automatically layout labels. Their model files are under
`/opt/analog-layout/pdks/sky130/sky130A/libs.ref/sky130_fd_pr/spice/` and are included by
`libs.tech/ngspice/all.spice`. They are not in the installed combined continuous model
view. Use the task's declared model view and physical device; a Magic generator or model
file alone does not establish an approved substitution or LVS match.

## Parameters, coordinates, and contact APIs

The four MOS factories use the same parameter names. The standard NMOS signature is shown below; all length parameters are in µm:

```python
sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=0.42, gate_length=0.15, sd_width=0.28,
    nf=1, guard_ring=True, dnwell=False, end_cap=0.13, mult=1,
)
```

Standard PMOS and LVT NMOS use the same defaults as above; LVT PMOS has a default `gate_length` of `.35`.
`guard_ring=True` creates a P+ substrate contact ring for NMOS and an N+ well contact ring for PMOS.
Connect the body according to the netlist. These dimensions are function defaults; use the dimensions specified in the task netlist.
`ref.ports` returns metadata after the instance transformation. The upstream MOS geometry
rounds polygon vertices to a 5 nm grid, while its four port widths are passed directly
from `gate_width`. An arbitrary requested width can therefore differ from the drawn
diffusion width or fail port construction. With the installed 1 nm DBU, kfactory requires
the port width in DBUs to be even. This check alone does not enforce the 5 nm manufacturing
grid. A port's `dwidth` is neither the M1 contact-pad width nor a recommended routing width.

For these centered MOS geometries, a full width on a 10 nm grid puts both half-width
edges on the 5 nm grid. Use the native gdsfactory API to calculate a representable width:

```python
import gdsfactory as gf
import sky130

width_total_um, nf = 8.0, 4
width_per_finger_um = gf.snap.snap_to_grid(width_total_um / nf, nm=10)
print(width_per_finger_um, width_per_finger_um * nf)  # 2.0, 8.0
device = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=width_per_finger_um, gate_length=0.5, nf=nf,
)
```

This makes the width explicit; it does not authorize changing a task's fixed dimensions.
For example, rounding `8/3` to `2.67` µm would produce a total width of `8.01` µm,
not `8` µm. That arithmetic must not be presented as an exact implementation.
When equal finger widths are not representable on the grid, the layout may use
parallel on-grid fingers with the same model, length, total width,
and D/G/S/B connectivity. For a total width of `8` µm, on-grid widths
`2.66 + 2.67 + 2.67` µm preserve the total width. This is a physical partition of
the fixed device, not a change to its reference netlist or electrical dimensions.
The generated layout must still meet DRC, LVS, and the post-layout electrical requirements.
Check the resulting geometry and extracted dimensions against the task and LVS requirements.
In the installed gdsfactory, an explicit `nm` overrides `grid_factor`, so
`snap_to_grid2x(value, nm=5)` is not a substitute for `snap_to_grid(value, nm=10)`.
The default cell decorator's port snapping runs after construction and does not repair
an invalid width passed to a port constructor.

The following cut-generation APIs are available directly from `sky130.pcells`:

```python
contact_array(width=0.29, height=0.29, contact_layer=(66, 44),
              contact_size=(0.17, 0.17), contact_spacing=(0.17, 0.17),
              enclosure=(0.06, 0.06))
licon_array(width=0.29, height=0.29)
mcon_array(width=0.29, height=0.29)
via_generator(width=1, length=1, via_size=(0.17, 0.17),
              via_layer=(66, 44), via_enclosure=(0.06, 0.06),
              via_spacing=(0.17, 0.17))
```

- `contact_array` returns only cut rectangles. It does not create the conductors above or below them, implants, wells, or ports.
  `width/height` defines an imaginary bounding region for placing the cuts. The array is centered at
  `(width/2, height/2)`, not at the coordinate origin. `contact_spacing` is the distance between cut edges;
  the array pitch is the cut size plus that spacing. If the region cannot fit one cut, the function returns an empty component.
- `licon_array` is a version of this interface with fixed parameters: LICON `(66,44)`, cut size `.17×.17`,
  cut spacing `.17`, and placement margin `.06`. This does not mean that every poly/LI enclosure rule requires only `.06`.
- `mcon_array` uses MCON `(67,44)`, cut size `.17×.17`, cut spacing `.19`,
  and placement margins `(x=.03, y=.06)`. LI and M1 conductors must already exist or be drawn separately.
- `via_generator` also draws only cuts. `width/length` determines the row and column counts; the array starts at the origin
  and is not automatically centered. The implementation creates at least one row and one column, so a returned array does not establish that a small input window is valid.
  Inspect `ref.dbbox()` before positioning an instance, or use `ref.dcenter=(x,y)` to align the actual array center.
  The default layer is LICON. For M1–M2 vias, explicitly set the VIA layer, dimensions, spacing, and enclosure parameters.

These functions' `enclosure` parameters control cut placement only; they do not draw enclosing metal.
Overlapping two metal layers without the correct cut layer does not connect them.
The installed library also provides `from sky130.pcells.vias import via_m1_m2`, with signature
`via_m1_m2(width=0.5, length=0.5)`. It draws M1/VIA/M2
and provides `e1/e2` ports. It is not exported from the top-level `sky130.pcells` namespace, and its geometry still requires DRC for any parameter choice.
Use Python's `help(sky130.pcells.contact_array)` to inspect the API.
Reading the implementation is optional; the limits of the returned geometry are described here.

## Common layers and connections

The following are attributes of `sky130.LAYER`; pairs in parentheses are GDS `(layer, datatype)` values.
Use `add_label` to place conductor labels on the corresponding label layer and inside the physical conductor.
Text does not establish a physical connection; do not use label layers to draw conductors.

| Purpose | Drawing attribute / GDS layer | Label attribute / GDS layer |
|---|---|---|
| N-well | `nwelldrawing` `(64,20)` | `nwelllabel` `(64,5)` |
| Device diffusion | `diffdrawing` `(65,20)` | `difflabel` `(65,6)` |
| Body/well contact region | `tapdrawing` `(65,44)` | `taplabel` `(65,5)` |
| Poly | `polydrawing` `(66,20)` | `polylabel` `(66,5)` |
| Poly/diff/tap → LI | `licon1drawing` `(66,44)` | — |
| LI | `li1drawing` `(67,20)` | `li1label` `(67,5)` |
| LI → M1 | `mcondrawing` `(67,44)` | — |
| M1 | `met1drawing` `(68,20)` | `met1label` `(68,5)` |
| M1 → M2 | `viadrawing` `(68,44)` | — |
| M2 | `met2drawing` `(69,20)` | `met2label` `(69,5)` |
| M2 → M3 | `via2drawing` `(69,44)` | — |
| M3 | `met3drawing` `(70,20)` | `met3label` `(70,5)` |
| M3 → M4 | `via3drawing` `(70,44)` | — |
| M4 | `met4drawing` `(71,20)` | `met4label` `(71,5)` |
| M4 → M5 | `via4drawing` `(71,44)` | — |
| M5 | `met5drawing` `(72,20)` | `met5label` `(72,5)` |
| MIM plate markers | `capm` `(89,44)`; `cap2m` `(97,44)` | — |
| Resistor markers | `polyres` `(66,13)`; `diffres` `(65,13)`; `rpmdrawing` `(86,20)` | — |
| BJT identification | `npndrawing` `(82,20)`; `pnpdrawing` `(82,44)` | — |

These attributes correspond to the installed `sky130.LAYER`.
Place top-level LVS/PEX ports on the LI/metal conductors used in the task, with labels on the corresponding label layers.
Listing a label attribute here does not mean every extractor recognizes it as a top-level port.

## Basic rules in the installed DRC deck

The following reference covers ordinary low-voltage analog periphery regions. **It is not a complete set of design rules and does not replace DRC.**
Width, spacing, and enclosure are in µm; area is in µm². The installed deck uses the AL backend.
Core regions, precision resistors, MIM, special devices, seals, and other structures have additional conditional rules; the values below do not apply universally.

Local reference: `/opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc`,
release `2025.11.17_01.10`. Line numbers below refer to this installed file.

| Object | Common rules for ordinary regions | Installed deck location / reported rule name |
|---|---|---|
| Grid | Vertices must lie on a `.005` (5 nm) grid; check again after floating-point calculations, rotations, or mirroring | L1675 onward, `*_OFFGRID` |
| N-well | Minimum width `.84`; spacing between separate polygons `1.27`; whether wells can merge also depends on their body nets | L331, `MR_nwell.WID.1/SP.1` |
| Diff/tap | Minimum width `.15` in periphery regions; combined diff/tap spacing `.27` | L425–465, `difftap.1_a`, `MR_diff.WID.2`, `difftap.3` |
| Poly | Minimum width `.15`; ordinary periphery spacing `.21`; these rules do not authorize changing the netlist L | L515–524, `MR_poly.WID.2/SP.1` |
| LICON | Ordinary cuts excluding bars and precision-resistor cuts: `.17×.17`, spacing `.17`; a cut must not bridge poly and diff/tap | L805–836, L952, `MR_licon.SP.1/WID.1`, `licon.1/17` |
| LI | Width/spacing `.17/.17` outside core regions; minimum area `.0561`; LICON enclosure also has an adjacent-edge requirement of `.08` | L1070–1090, `li.1/3/5/6` |
| MCON | Ordinary cuts `.17×.17`, spacing `.19`; cuts must be covered by LI | L1119–1151, `MR_mcon.WID.1/LEN.1/SP.1/CON.10` |
| M1 | Ordinary width/spacing `.14/.14`, minimum area `.083`; spacing associated with 3 µm-wide metal is `.28`; MCON enclosure is at least `.03`, with an adjacent-edge requirement of `.06` | L1157–1235, `MR_met1.WID.1/SP.1/AR.1/ENC.1`, `MRW_met1.SP.2`, `m1.5` |
| VIA (M1→M2) | Ordinary cuts `.15×.15`, spacing `.17`; M1 and M2 enclosure is at least `.055`, with an additional adjacent-edge requirement of `.085` for each layer | L1256–1306, L1343–1363, `via.1a/2/5a`, `MR_via1.ENC.1`, `m2.4/5` |
| M2 | Ordinary width/spacing `.14/.14`, minimum area `.0676`; spacing associated with 3 µm-wide metal is `.28` | L1314–1331, `MR_met2.WID.1/AR.1`, `m2.2`, `MRW_met2.SP.2` |

An "adjacent-edge requirement" means that, at each cut corner, at least one of the two adjacent enclosure edges must meet the larger value.
For rectangular landing pads, a common way to satisfy this is to increase enclosure on a pair of opposite sides, not on an arbitrary pair of adjacent sides.
For example, M1 must enclose MCON by at least `.03` on all four sides and also meet the `.06` requirement above.
A landing pad can satisfy cut enclosure and still violate minimum metal area. A PCell's isolated contacts may need surrounding routing to meet area rules.
`floating_met=true` also checks for floating metal: M1 must touch MCON/VIA, M2 must touch VIA/VIA2, and so on.
