# SKY130 Layout Task Environment

[English](GUIDE.md) | [简体中文](GUIDE.zh-CN.md)

The English version is authoritative. The Chinese version is a translation.

The workspace provides the task input and software documentation. You are responsible
for placement, routing, scripting, and debugging.

## Activate the Environment and Read the Task

```bash
source ./eda_env.sh
```

- `task/circuit.spice`: the fixed circuit and device dimensions, also used as the simulation DUT.
- Task instructions: function, ports, implementation constraints, operating conditions,
  stimuli, measurement definitions, and electrical specifications. Harbor supplies these
  instructions as the task prompt; they need not be a file in the workspace.
- [DEVICE_API.md](DEVICE_API.md): parameters, ports, and common layers for the installed SKY130 devices
  and contacts, plus an index of basic rules in the fixed DRC deck.

Submit `submission/layout.gds` with the top-level name and ports specified by the fixed
netlist and task instructions. Save generation code in `submission/src/`. Keep temporary
scripts, extraction outputs, and simulation logs in `work/`.
Place and route as compactly as possible to improve area utilization while meeting the
task's electrical and process requirements. Self-check results are not official scores;
acceptance checks reread the submitted GDS.

## Software and PDK

| Capability | Installed interface or path |
|---|---|
| Python | `/opt/analog-layout/python/bin/python3.12` |
| Programmatic layout generation | `gdsfactory`, or direct use of `klayout.db` |
| SKY130 PCells | `/opt/analog-layout/pdks/sky130/python/sky130` |
| KLayout | `klayout`; supports batch operation and the Python database interface |
| DRC deck | `/opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc` |
| LVS deck | `/opt/analog-layout/pdks/sky130/klayout/sky130.lvs` |
| Magic | `magic` |
| Magic startup file | `/opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc` |
| ngspice | `ngspice` |
| Task-selected simulation model entry point | Run `printf '%s\n' "$ALB_MODEL_LIB"` after sourcing `eda_env.sh` |

See `/opt/analog-layout/runtime.json` for versions. Use the installed PDK; do not replace
it with another package of the same name. Python device entry points:

```python
import gdsfactory as gf
import sky130
sky130.PDK.activate()
# Device functions are in sky130.pcells; layers are in sky130.LAYER.
```

Common geometry API example (API syntax only, not a layout solution for this task):

```python
c = gf.Component("api_example")
mos = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True,
)
ref = c.add_ref(mos)
ref.drotate(90)       # Angle in degrees.
ref.dmove((10, 10))   # Coordinates in µm.
p = ref.ports["DRAIN"] # Transformed upstream port metadata; see DEVICE_API.md for limits.
print(p.dcenter, p.dwidth, p.orientation, p.layer)
# ports is a container indexed by name; iteration yields Port objects directly.
for port in ref.ports:
    print(port.name, port.dcenter, port.dwidth, port.orientation, port.layer)
c.add_polygon([(0, 0), (2, 0), (2, 1), (0, 1)], layer=sky130.LAYER.met1drawing)
c.add_label("example_label", position=(1, 0.5), layer=sky130.LAYER.met1label)
c.write_gds("work/api_example.gds", with_metadata=False)
```

`add_ref` preserves hierarchy; moving an instance does not move the original PCell.
Call `mos.copy()` before modifying a library component to avoid changing a cached object.
Overlapping metal on different layers is not an electrical connection; use contacts or
vias as required by the PDK. In this version, `ref.ports` is not a Python `dict` and has
no `.items()` method. For a name-to-port mapping, use
`{port.name: port for port in ref.ports}`; there is no need to read the library implementation.
Multiple device terminals do not automatically form a circuit bus. GDS labels and
Python port metadata are also distinct.
The standard electrical routing API is available:
`gf.routing.route_single_electrical(c, port1, port2, layer=sky130.LAYER.met1drawing, width=0.5, cross_section="metal1")`.
It does not perform placement, obstacle avoidance, or process checks for the entire circuit.

Read component geometry with `get_polygons`. `layers` selects the layers to query;
`by="tuple"` returns a dictionary keyed by `(layer, datatype)`, with a list of polygons
for each layer. `merge=False` keeps the polygons separate.

```python
polygons_by_layer = c.get_polygons(
    merge=False, by="tuple", layers=[(68, 20)],
)
for polygon in polygons_by_layer.get((68, 20), []):
    print(polygon.bbox())
```

The returned `klayout.db.Polygon` coordinates and bounding boxes use database units;
multiply coordinate values by `c.kcl.dbu` to convert them to µm.
Use `help(c.get_polygons)` to inspect the installed interface.

Before routing, consult the parameter, coordinate, and contact interface documentation
and the basic DRC rule index in [DEVICE_API.md](DEVICE_API.md). A cut-generation function does not
necessarily create metal above and below the cut. Meeting minimum width does not ensure
compliance with minimum area, contact enclosure, or floating-metal rules.
The listed 5 nm grid and common LI/M1/M2 and contact/via values include locations in the
fixed deck. The installed deck defines the complete process conditions.

## Offline Reference Documentation (Optional)

For fuller or advanced usage, consult these local official references as needed.
The following paths are relative to `/opt/analog-layout/`:

| Reference | Local files |
|---|---|
| Magic 8.3 command reference | `tools/magic/lib/magic/doc/html/commands.html`; plain-text copies of GDS/flatten/extraction commands in `tools/magic/lib/magic/doc/text/` |
| ngspice 46 manual | `tools/ngspice/share/doc/ngspice/ngspice-46-manual.txt`; the adjacent `.pdf` retains the original figures and formula formatting |
| SKY130 process, layers and devices | `pdks/sky130/docs/skywater-pdk/rules.rst`; detailed entry points are listed in [DEVICE_API.md](DEVICE_API.md) |

KLayout includes a built-in manual; gdsfactory and `klayout.db` provide native API documentation.
This documentation can be consulted offline with Python's `help()` or `pydoc` as needed
to look up class, function, and method parameters, return values, and usage.

## Native KLayout Commands

Replace `TOP` and `SUBSTRATE` below with the values specified by the fixed netlist and
task instructions, and choose your output paths. Use a fresh directory for each check
and retain the original reports. Run these commands from the workspace root. Use absolute
file paths so the deck does not interpret relative report paths from the GDS directory.

```bash
mkdir -p work/drc-01
klayout -b -r /opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc \
  -rd input="$PWD/submission/layout.gds" -rd top_cell=TOP \
  -rd report="$PWD/work/drc-01/report.lyrdb" -rd thr=2 \
  -rd feol=true -rd beol=true -rd offgrid=true -rd floating_met=true \
  -rd sram_exclude=false -rd seal=false -rd info=false

mkdir -p work/lvs-01
schematic="$PWD/task/circuit.spice"
if [ -f "$PWD/task/lvs_reference.spice" ]; then
  schematic="$PWD/task/lvs_reference.spice"
fi
klayout -b -r /opt/analog-layout/pdks/sky130/klayout/sky130.lvs \
  -rd input="$PWD/submission/layout.gds" -rd top_cell=TOP \
  -rd schematic="$schematic" \
  -rd report="$PWD/work/lvs-01/report.lvsdb" -rd target_netlist="$PWD/work/lvs-01/extracted.spice" \
  -rd run_mode=deep -rd convert_subckts=true -rd scale=true -rd schematic_simplify=true \
  -rd spice_net_names=true -rd spice_comments=true -rd verbose=true \
  -rd lvs_sub=SUBSTRATE -rd thr=2
```

The command uses `task/lvs_reference.spice` when supplied, otherwise
`task/circuit.spice`. A separate LVS reference represents the same fixed devices
in the installed reader's syntax, including MIM area/perimeter when required.
It is not a simulation model; simulate `circuit.spice` or the extracted netlist.

Inspect the DRC report for violations. For LVS, inspect connectivity, device parameters,
and top-level pin matching. A completed process or an existing report file does not
establish a pass. Reports can be opened in KLayout.
If KLayout reports `Netlists match`, still check that the extracted top-level pins
match the task interface and review any extraction warnings.

## Native Magic Parasitic Extraction

The following is the **SKY130 `ngspice()` extraction procedure for this image**,
not a universal procedure for every PDK. Before running it, read the fixed netlist and
task instructions for the top-level name, port order, and substrate connection requirements.
The GDS must already contain text labels for these ports on the correct conductors.
Defining `port` metadata only in Python objects does not create GDS labels.

Create a fresh output directory, `work/pex-01/`, in the workspace and save the following
as `work/pex-01/extract.tcl`. Replace `TOP` and `PORT_1 PORT_2 ...`; these are placeholders,
not a particular task's circuit name or ports. Run the script from `work/pex-01/`, so the
input GDS path is relative to that directory. An absolute path may also be used.

```tcl
set gds_file [file normalize ../../submission/layout.gds]
set top TOP
set ordered_ports {PORT_1 PORT_2 PORT_3}
set flat_top ${top}_pex

drc off
gds readonly true
gds rescale false
gds read $gds_file
load $top
select top cell
# Create a flattened copy in memory with a name distinct from every existing cell.
flatten $flat_top
load $flat_top
select top cell
expand

# Set port attributes on existing physical labels of the same name; add no labels or connections.
set index 1
foreach pin $ordered_ports {
    if {[port $pin exists]} {
        port $pin index $index
    } else {
        port $pin make $index
    }
    incr index
}

extract style {ngspice()}
extract do local
extract no corners
extract no resistance
extract do capacitance
extract do coupling
extract do adjust
extresist threshold 0
extresist minres 1
extresist mindelay 0
extresist simplify on
extresist extout on
extresist silent off
extract do resistance
extract all

ext2spice default
ext2spice format ngspice
ext2spice scale off
ext2spice merge none
ext2spice hierarchy off
ext2spice subcircuit top on
ext2spice global off
ext2spice short none
ext2spice rthresh infinite
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o extracted.spice ${flat_top}.ext
# Optionally save a Magic copy here for inspection; do not write back to the input GDS.
save $flat_top
puts "PEX_COMPLETE rc"
quit -noprompt
```

Run this step independently:

```bash
mkdir -p work/pex-01
# Save work/pex-01/extract.tcl as shown above before running:
(
  cd work/pex-01
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc \
    extract.tcl > magic.log 2>&1
)
```

Outputs include `magic.log`, the flattened cell's `.ext` / `.res.ext` files,
`extracted.spice`, and an optional `.mag` file. `threshold` and `minres` are in milliohms;
`mindelay` is in picoseconds. In this version, `extract all` after `extract do resistance`
performs RC extraction. There is no need to run the older `ext2sim` command or call
`extresist all` again.

At a minimum, check the following outputs:

- The port count, names, and order in `.subckt TOP_pex ...` must match the task.
  Wire the actual simulation according to this declaration.
- Check MOS/BJT/R/C model names and device dimensions, and verify that substrate and well
  terminals come from physical contacts and connections. `ext2spice global off` does not
  connect all body terminals to ground. Do not repair missing GDS connections by editing
  the extracted netlist.
- Check the log for technology-file loading failures, unknown extraction styles, missing
  labels, port errors, and extraction warnings. Magic may continue after errors; neither
  its exit code nor `PEX_COMPLETE` alone establishes valid extraction.
- A `.res.ext` file is one indication of distributed resistance extraction. If the original
  circuit already contains resistors, `R...` statements alone do not establish that
  parasitic resistance was extracted.

**Units:** With this image's SKY130 `ngspice()` and `ext2spice scale off`, measured output
uses **µm** for PDK subcircuit `w/l` numbers, such as `w=8 l=1`; area numbers such as
`ad/as` are in µm². Here, `off` does not convert every number to SI meters. Native parasitic
`R` values are in Ω, and `C` values are in F or use explicit SPICE suffixes. For example,
`C1 n1 n2 2.5f` is 2.5 fF. Do not multiply these values by `1e-6` again.

Keep `ext2spice short none` in RC mode. Do not blindly set `short resistor` to preserve
two ports on the same net: a 0 Ω alias can bypass actual wire resistance. If an output
omits a port on the same net, first inspect the labels, ports, and resistor network.
For C-only diagnostics, replace `extract do resistance` with `extract no resistance`
and `ext2spice extresist on` with `ext2spice extresist off`. In that mode,
`short resistor` can represent ideal ports on the same net. C-only diagnostics do not
qualify as post-layout simulation with interconnect resistance.

This command sequence matches the procedure tested in this image. Extraction results
still require checks against DRC/LVS and circuit behavior; the procedure does not certify
physical accuracy for every device or layout.

## Native ngspice Simulation

Start with `task/testbench/README.md` and the supplied native `.spi` files. They
provide task-specific stimuli and loads at representative conditions, using this
task's qualified model and initialization. The README lists the correct command
and waveform outputs for each analysis; some require `-r analysis.raw`.
The complete electrical requirements remain in the task instruction.

Simulation requires three parts: the model library, the DUT netlist, and a testbench that
supplies power, stimuli, loads, and measurements. Use `task/circuit.spice` as the
pre-layout DUT and a freshly extracted `extracted.spice` as the post-layout DUT.
If a task separately provides `task/lvs_reference.spice`, use it only for LVS comparison,
not as the simulation DUT.

Create a fresh directory for each simulation. `eda_env.sh` sets the task's qualified
model path (`ALB_MODEL_LIB`) and ngspice initialization (`ALB_NGSPICE_INIT`). Save that
initialization in the run directory:

```bash
mkdir -p work/sim-01
printf '%s\n' "${ALB_NGSPICE_INIT:?Source eda_env.sh first}" > work/sim-01/.spiceinit
```

Compatibility mode affects model interpretation. `set ngbehavior=hsa` is not a
universal requirement for every SKY130 model view: use the initialization selected
for this task, consistently for pre-layout and post-layout simulation. Do not add
`-n`, which skips initialization. Save your own `testbench.cir` in the same directory,
then run:

```bash
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.cir
)
```

Relative `.include` and waveform output paths are resolved from the run directory;
use absolute paths if in doubt. Select the process corner with `.lib "MODEL_PATH" tt`
and set temperature with `.temp`. Use the model view and process corners specified by
the task instructions. Do not silently interchange continuous/binned views or R/C corners,
or change all operating conditions to TT.
Read the absolute model path with `printf '%s\n' "$ALB_MODEL_LIB"` and replace
`MODEL_PATH` in the example below with that path. ngspice does not expand shell
environment variables inside this `.lib` string.

The following demonstrates native syntax only. **Assume** the extracted declaration
for a four-port inverter is `.subckt DEMO_pex vss vdd vin vout`. This is not a universal
testbench or scoring criterion. Write the ports, biases, supplies, clocks, loads, and
measurements required by this task's instructions.

```spice
* Syntax example only: four-port inverter at TT/1.8V/27C.
.lib "MODEL_PATH" tt
.include "../pex-01/extracted.spice"
.option scale=1e-6
.options reltol=2e-4 abstol=1e-12 vntol=1e-6
.temp 27

VSS vss 0 0
VDD vdd vss 1.8
VIN vin vss PULSE(0 1.8 2n 100p 100p 5n 10n)
* Wire nodes in the actual .subckt declaration's order; the final name is the actual subcircuit name.
XDUT vss vdd vin vout DEMO_pex
CLOAD vout vss 20f

.control
set noaskquit
set wr_singlescale
set wr_vecnames
tran 10p 24n 0 20p
meas tran tphl_s TRIG v(vin) VAL=0.9 RISE=2 TARG v(vout) VAL=0.9 FALL=2
meas tran tplh_s TRIG v(vin) VAL=0.9 FALL=2 TARG v(vout) VAL=0.9 RISE=2
wrdata waveform.tsv v(vin) v(vout) i(VDD)
write waveform.raw all
quit
.endc
.end
```

The example's `.option scale=1e-6` corresponds to the µm dimensions described above.
Do not also multiply the PDK `w/l` numbers by `1e-6`. This option does not require
rewriting native parasitic R/C values. Check the model and DUT dimension units when
writing your testbench, and do not apply scaling twice.

`XDUT` matches ports by position, not automatically by name. If the testbench uses the
original top-level name `TOP` but extraction produces `TOP_pex`, change the DUT instance's
final subcircuit name and arrange its nodes in the actual port order, or write a thin
`.subckt` adapter that adjusts only the name and port order. Do not modify circuit
connectivity, stimuli, loads, tolerances, or specifications to manufacture a pass.
Keep external fixtures such as bias sources and output loads.

`simulation.log` contains run and `meas` output; `waveform.tsv` / `.raw` contain waveforms.
For this example, confirm that the log contains finite numerical results for
`tphl_s = ...` and `tplh_s = ...`, and that the waveforms contain the required transitions.
Missing crossings, nonconvergence, missing measurements, or missing models cannot count
as meeting a specification.

Use or extend the supplied native testbenches for the conditions in the task
instructions. You may write programs to sweep operating conditions, measure
waveforms, or parse results. The inverter example above only explains the
ngspice interface; the task instructions define the required stimuli and metrics.
