"""Magic GDS extraction for the qualified SKY130 ``ngspice()`` runtime.

Circuit top/ports are generic; the extraction style and unit convention are
specific to this installed process integration, not arbitrary PDKs.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import re
import shutil

try:
    from . import rc_reduce
    from .runtime import load_runtime, magic_env, run_command, sha256, shared_output
except ImportError:
    import rc_reduce
    from runtime import load_runtime, magic_env, run_command, sha256, shared_output

PORTS = ["vss", "ibias", "vdd", "vinn", "vinp", "vout"]
LIMITATION = (
    "Provisional extraction: the current Magic RC configuration retains coupling "
    "capacitance while also allocating related capacitance to distributed substrate "
    "capacitance. Qualification is unresolved; results are not certified signoff. "
    "C-only is an approximation and cannot replace RC evaluation."
)
IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z")
# Magic writes extracted.spice; it is kept unchanged as RAW_NETLIST and
# extracted.spice becomes the reduced netlist read by post-layout simulation.
RAW_NETLIST = "extracted.raw.spice"
# Nodes above degree 3 are eliminated only when the step does not increase
# the total number of resistor and capacitor elements.
RC_REDUCTION = {"tau_s": rc_reduce.DEFAULT_TAU_S, "max_degree": 8}
RC_REDUCTION_LIMITATION = (
    "Post-layout simulation reads extracted.spice, a TICER star-mesh reduction of Magic's "
    "complete netlist (extracted.raw.spice): resistances are merged (series/parallel/"
    "star-mesh), never shorted; DC node voltages and net-to-net/ground capacitance are "
    "preserved; only internal nodes with C/G <= tau_s are eliminated, so the within-net "
    "RC distribution is first-order accurate below 1/(2*pi*tau_s)."
)


def environment_failure_lines(log: str, rcfile: Path) -> list[str]:
    """Recognize explicit loader/PDK setup failures, not arbitrary design errors.

    Magic can continue after a failed startup file or unknown extraction style,
    so these messages are fatal even if the process later exits successfully.
    The technology/style messages match the installed Magic source diagnostics.
    """
    patterns = (
        r"error while loading shared libraries|version [^\n]+ not found|cannot execute binary file",
        r"(?:Failed to load|Error loading|Cannot load) technology\b|Error in loading technology file",
        r"Could not find file ['\"][^\n]+\.tech['\"] in any of these directories",
        r'"ngspice\(\)" is not one of the extraction styles Magic knows',
        r'Extraction style "ngspice\(\)" is ambiguous',
        rf'(?:Error parsing (?:user )?|Bad local startup file )"{re.escape(str(rcfile))}"',
    )
    return [line for line in log.splitlines()
            if any(re.search(pattern, line, re.I) for pattern in patterns)]


def number(token: str) -> float:
    match = re.fullmatch(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(meg|[afpnumkgt]?)", token, re.I)
    if not match:
        raise ValueError(f"Unsupported numeric value: {token!r}")
    value = float(match[1]) * {"": 1, "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9,
                             "u": 1e-6, "m": 1e-3, "k": 1e3, "meg": 1e6,
                             "g": 1e9, "t": 1e12}[match[2].lower()]
    if not math.isfinite(value):
        raise ValueError("Non-finite netlist value")
    return value


def logical_lines(path: Path) -> list[str]:
    """Read continuation lines without executing SPICE expressions or directives."""
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not lines:
                raise ValueError("Orphan SPICE continuation")
            lines[-1] += " " + line[1:]
        else:
            lines.append(line)
    return lines


def inspect_netlist(path: Path, ports: list[str], top: str | None = None) -> dict:
    """Inspect a device-only SPICE library, including hierarchical PDK devices.

    This is a structural check, not a SPICE implementation or LVS substitute.
    Model parameters/expressions remain untouched. Executable/include directives
    are rejected in extracted DUT files; the trusted bench supplies PDK models.
    """
    cells, current, stack = {}, None, []
    counts = {"mos": 0, "resistors": 0, "capacitors": 0}
    device_counts, models = {}, {}
    capacitance, geometry_fields = 0.0, 0
    instances = []
    for line in logical_lines(path):
        words = line.split()
        name = words[0].lower()
        if name == ".subckt":
            if len(words) < 3:
                raise ValueError("Invalid .subckt declaration")
            cell_name = words[1]
            cell_key = ((current["key"] + "/") if current else "") + cell_name.lower()
            if cell_key in cells or not IDENTIFIER.fullmatch(cell_name):
                raise ValueError("Duplicate or invalid subcircuit name")
            pins = []
            for word in words[2:]:
                if "=" in word or word.lower() == "params:":
                    break
                pins.append(word)
            if len({p.lower() for p in pins}) != len(pins):
                raise ValueError("Duplicate top-level pins")
            stack.append(current)
            current = {"name": cell_name, "key": cell_key, "ports": pins,
                       "instances": set(), "devices": [], "parent": current}
            cells[cell_key] = current
            continue
        if name == ".ends":
            if current is None or len(words) > 2 or (len(words) == 2 and words[1].lower() != current["name"].lower()):
                raise ValueError("Missing or mismatched .ends")
            current = stack.pop()
            continue
        if current is None:
            raise ValueError("Expected device statements inside .subckt")
        if name == ".param":
            continue  # Parameters belong to the netlist, never Python-evaluated.
        if name.startswith(".") or name[0] not in "xmqdrclkvibefgh":
            raise ValueError(f"Unsupported device-netlist statement: {words[0]}")
        if name in current["instances"]:
            raise ValueError(f"Duplicate component: {name}")
        current["instances"].add(name)
        prefix = name[0]
        if len(words) < (3 if prefix == "k" else 4):
            raise ValueError(f"Incomplete component: {name}")
        device_counts[prefix] = device_counts.get(prefix, 0) + 1
        if prefix in "rc" and len(words) == 4:
            value = number(words[3])
            if value < 0:
                raise ValueError(f"Invalid passive value: {name}")
            if words[1].lower() == words[2].lower():
                raise ValueError(f"Self-connected passive: {name}")
            counts["resistors" if prefix == "r" else "capacitors"] += 1
            if prefix == "c":
                capacitance += value
        if prefix == "x":
            end = next((i for i, word in enumerate(words) if "=" in word or word.lower() == "params:"), len(words))
            model = words[end - 1]
            instances.append((current["name"], model))
        elif prefix == "m":
            model = words[5] if len(words) >= 6 else ""
        elif prefix in "qd":
            model = next((word for word in reversed(words) if "=" not in word), "")
        else:
            model = ""
        if model:
            models[model] = models.get(model, 0) + 1
            current["devices"].append((prefix, model.casefold()))
        if prefix == "m" or (prefix == "x" and re.search(r"__(?:n|p)fet_", model, re.I)):
            counts["mos"] += 1
            params = dict(re.findall(r"\b([a-z]+)\s*=\s*([^\s]+)", line, re.I))
            geometry_fields += all(key in params for key in ("ad", "as", "pd", "ps"))
    if current is not None or not cells or not device_counts:
        raise ValueError("Unterminated or empty device netlist")
    if top is None:
        referenced = {model.lower() for _, model in instances if model.lower() in cells}
        roots = {key for key, cell in cells.items() if cell["parent"] is None} - referenced
        if len(roots) != 1:
            raise ValueError("Ambiguous top; specify the extracted top explicitly")
        top = next(iter(roots))
    if top.lower() not in cells:
        raise ValueError(f"Missing extracted top: {top}")
    selected = cells[top.lower()]
    if set(port_keys(selected["ports"])) != set(port_keys(ports)) or len(selected["ports"]) != len(ports):
        raise ValueError(f"Top-level pin contract differs: {selected['ports']}")
    if not math.isfinite(capacitance):
        raise ValueError("Non-finite capacitance total")

    def resolve_cell(scope, model):
        while scope is not None:
            key = scope["key"] + "/" + model
            if key in cells:
                return cells[key]
            scope = scope["parent"]
        return cells.get(model)

    reachable_models, visited, active = set(), set(), set()

    def visit(cell):
        key = cell["key"]
        if key in active:
            raise ValueError("Recursive subcircuit hierarchy")
        if key in visited:
            return
        active.add(key)
        for prefix, model in cell["devices"]:
            child = resolve_cell(cell, model) if prefix == "x" else None
            if child is not None:
                visit(child)
            else:
                reachable_models.add(model)
        active.remove(key)
        visited.add(key)

    visit(selected)
    return {"top": selected["name"], "ports": selected["ports"], "counts": counts,
            "device_counts": device_counts, "models": models, "subcircuits": list(cells),
            "reachable_models": sorted(reachable_models),
            "capacitance_f": capacitance, "mos_with_ad_as_pd_ps": geometry_fields,
            "count_scope": "statements in library; not flattened electrical multiplicity",
            "parasitic_classification": "not inferred from component names/counts"}


FLOATING_PORT_REASON = ("Reference top-subcircuit port net connects to no device or subcircuit "
                        "terminal; it may be absent from the extracted top. All other ports remain required.")


def declared_subckt_pins(path: Path) -> dict[str, list[str]]:
    """Declared pins of every subcircuit, keyed by lower-case name (no validation)."""
    declared = {}
    for line in logical_lines(path):
        words = line.split()
        if words[0].lower() == ".subckt" and len(words) > 1:
            pins = []
            for word in words[2:]:
                if "=" in word or word.lower() == "params:":
                    break
                pins.append(word)
            declared[words[1].lower()] = pins
    return declared


def reference_floating_ports(reference: Path | None, top: str, ports: list[str]) -> dict:
    """Contract ports with no device connection in the trusted reference.

    The rule is eda.area_v2.floating_ports, shared by LVS, PEX and the
    post-layout adapter. Without a parsable reference nothing is exempt.
    """
    if reference is None:
        return {"ports": []}
    try:
        from .area_v2 import floating_ports
    except ImportError:
        from area_v2 import floating_ports
    try:
        names = {name.casefold() for name in floating_ports(Path(reference).read_text(), top)}
    except (OSError, ValueError) as error:
        return {"ports": [], "check_error": f"{type(error).__name__}: {error}"}
    return {"ports": [port for port in ports if port.casefold() in names]}


def required_extracted_ports(ports: list[str], floating: list[str],
                             declared: list[str] | None) -> tuple[list[str], list[str]]:
    """Return (required ports, absent floating ports) for an extracted top.

    Only a floating reference port may be absent. Without an identified top
    the full contract remains required, retaining the historical error.
    """
    present = None if declared is None else set(port_keys(declared))
    absent = [port for port in floating if present is not None and port_keys([port])[0] not in present]
    return [port for port in ports if port not in absent], absent


def reduce_for_simulation(raw: Path, reduced: Path, raw_info: dict,
                          ports: list[str], top: str) -> tuple[dict, dict]:
    """Write the post-layout simulation netlist from Magic's complete netlist.

    The reduced netlist must keep the inspected top, pin order, device models
    and non-R/C statements. Any reducer failure falls back to an exact copy of
    the complete netlist, which is always a correct (only slower) input.
    """
    try:
        stats = rc_reduce.reduce_file(raw, reduced, **RC_REDUCTION)
        info = inspect_netlist(reduced, ports, top)
        devices = lambda item: {k: v for k, v in item["device_counts"].items() if k not in "rc"}
        for key in ("top", "ports", "models", "reachable_models", "subcircuits"):
            if info[key] != raw_info[key]:
                raise ValueError(f"RC reduction changed the netlist {key}")
        if devices(info) != devices(raw_info) or info["counts"]["mos"] != raw_info["counts"]["mos"]:
            raise ValueError("RC reduction changed non-parasitic statements")
        stats["status"] = "reduced"
    except Exception as exc:  # deliberately broad: the complete netlist stays usable
        shutil.copyfile(raw, reduced)
        info = inspect_netlist(reduced, ports, top)
        stats = {"status": "fallback_complete_netlist", "error": f"{type(exc).__name__}: {exc}",
                 "algorithm": rc_reduce.ALGORITHM, "parameters": dict(RC_REDUCTION),
                 "input_path": str(raw), "input_sha256": sha256(raw),
                 "output_path": str(reduced), "output_sha256": sha256(reduced)}
    return stats, info


def reference_model_aliases(reference: Path, resistor_view: str | None) -> dict[str, str]:
    """Reuse the task's existing qualified physical-resistor geometry checks."""
    if resistor_view is None:
        return {}
    try:
        from .resistor_reference import resistor_reference_view
    except ImportError:
        from resistor_reference import resistor_reference_view
    text = reference.read_text()
    # The original high-poly task bundle has the single-view API. Its default
    # is also retained by the later multi-view module; neither needs replacing.
    if resistor_view == "high_po_0p35_literal_um":
        _, mappings = resistor_reference_view(text)
    else:
        _, mappings = resistor_reference_view(text, resistor_view)
    return {item["source_model"].casefold(): item["geometry_model"].casefold() for item in mappings}


def model_presence(reference: dict, extracted: dict, *, aliases: dict | None = None) -> dict:
    """Catch missing PDK device types, without equating fingers with instances.

    This is not another LVS: it cannot establish connectivity, dimensions or
    electrical multiplicity. Numeric R/C parasitics and metal resistors are not
    distinguishable by model names. Only an already qualified task-declared
    resistor geometry view may normalize a model name.
    """
    required = {model for model in reference["reachable_models"]
                if model.startswith("sky130_fd_pr__")}
    aliases = aliases or {}
    required = {aliases.get(model, model) for model in required}
    present = set(extracted["reachable_models"])
    return {"required_models": sorted(required), "extracted_models": sorted(present),
            "missing_models": sorted(required - present),
            "scope": "Top-reachable named PDK devices; not connectivity, dimensions, multiplicity or numeric R/C coverage."}


def load_task(task: Path) -> dict:
    """Read the task's declared top/ports, without imposing circuit-specific specs."""
    constraints = json.loads((task / "constraints.json").read_text())
    top, ports = constraints.get("top"), constraints.get("ports")
    if not isinstance(top, str) or not IDENTIFIER.fullmatch(top):
        raise ValueError("Task must declare a valid top")
    validate_ports(ports)
    return {**constraints, "reference": task / "circuit.spice"}


def layout_port_name(token: str) -> str:
    """KLayout reader's qualified angle-bus decoding, not ngspice node rewriting.

    Ngspice distinguishes the escaped and unescaped spellings. Keep original
    task tokens in simulation and adapt only the layout/PEX boundary.
    """
    return token.replace(r"\<", "<").replace(r"\>", ">")


def port_keys(ports: list[str]) -> list[str]:
    return [layout_port_name(p).casefold() for p in ports]


def validate_ports(ports: list[str]) -> None:
    # These are literal SPICE/GDS node tokens, not Python identifiers. No Tcl
    # evaluation is used; newline transport below preserves backslashes.
    # Reject SPICE separators, whitespace/control characters and quoting.
    if (not isinstance(ports, list) or not ports
            or any(not isinstance(p, str) or not p
                   or any(not (33 <= ord(c) <= 126) or c in "\"'();={}," for c in p)
                   or p.startswith(("*", ".", "+")) for p in ports)):
        raise ValueError("Ports must be non-empty literal SPICE node tokens")
    if len(set(port_keys(ports))) != len(ports):
        raise ValueError("Duplicate requested ports")


def prepare_magic_input(source: Path, top_name: str, destination: Path) -> dict:
    """Flatten a private GDS copy before Magic interprets process layers.

    GDS may put a transistor and its well in different cells. Magic's later
    flatten cannot undo a wrong per-cell interpretation during GDS import.
    Preserve child label scopes, as Magic's own flatten does: two instances'
    local S/D labels must not become an electrical connection by name.
    The collision-free namespace also identifies child pin labels whose port
    properties must be demoted after Magic imports the flattened geometry.
    Geometry, layer numbers and top-level label spelling remain unchanged.
    """
    import klayout.db as kdb

    layout = kdb.Layout()
    layout.read(str(source))
    top = layout.cell(top_name)
    if top is None:
        raise ValueError(f"Missing GDS top cell: {top_name}")
    layers = list(layout.layer_indexes())
    def geometry_on(layer):
        iterator = top.begin_shapes_rec(layer)
        iterator.shape_flags = kdb.Shapes.SBoxes | kdb.Shapes.SPolygons | kdb.Shapes.SPaths
        # Materialize before editing: an iterator-backed Region otherwise
        # observes the subsequent flatten too. Text boxes are not geometry.
        return kdb.Region(iterator).flatten()

    geometry = {layer: geometry_on(layer) for layer in layers}
    names = {shape.text.string for cell in layout.each_cell() for layer in layers
             for shape in cell.shapes(layer).each() if shape.is_text()}
    prefix = "__alb_pex_"
    while any(name.casefold().startswith(prefix.casefold()) for name in names):
        prefix = "_" + prefix
    labels, top_labels = [], set()
    renamed, next_instance = 0, 0

    def visit(cell, transform, scope):
        nonlocal renamed, next_instance
        for layer in layers:
            for shape in cell.shapes(layer).each():
                if not shape.is_text():
                    continue
                text = shape.text.transformed(transform)
                if scope is not None and text.string:
                    text.string = f"{prefix}{scope}." + text.string
                    renamed += 1
                elif scope is None:
                    top_labels.add(text.string)
                labels.append((layer, text, shape.prop_id))
        for instance in cell.each_inst():
            for local in instance.cell_inst.each_cplx_trans():
                instance_id = next_instance
                next_instance += 1
                visit(instance.cell, transform * local, instance_id)

    visit(top, kdb.ICplxTrans(), None)
    top.flatten(True)
    for layer, original in geometry.items():
        if not (original ^ geometry_on(layer)).is_empty():
            raise ValueError(f"GDS flatten changes geometry on layer {layout.get_info(layer)}; refusing extraction")
    for layer in layers:
        for shape in [s for s in top.shapes(layer).each() if s.is_text()]:
            shape.delete()
    for layer, text, properties in labels:
        shape = top.shapes(layer).insert(text)
        if properties:
            shape.prop_id = properties
    options = kdb.SaveLayoutOptions()
    options.select_cell(top.cell_index())
    layout.write(str(destination), options)
    return {"path": str(destination), "method": "GDS geometry flattened before Magic import; child labels scoped per instance",
            "geometry_check": "All input layers have zero polygon XOR after flattening",
            "label_count": len(labels), "renamed_child_labels": renamed,
            "top_labels": sorted(top_labels), "namespace_prefix": prefix}


TCL = """# Input GDS and installed PDK are read-only; extraction uses an in-memory copy.
drc off
gds readonly true
gds rescale false
gds read $::env(LAYOUT_GDS)
load $::env(LAYOUT_TOP)
select top cell
flatten $::env(LAYOUT_FLAT_TOP)
load $::env(LAYOUT_FLAT_TOP)
select top cell
expand
# GDS pin-marker layers can make scoped child labels into top-level ports on
# import.  Keep their labels and geometry, but restore their internal scope.
# This is Magic's own top-label enumeration idiom (tcltk/readspice.tcl).
set alb_child_prefix $::env(LAYOUT_CHILD_PORT_PREFIX)
if {$alb_child_prefix eq {}} {
    error {Empty child label namespace}
}
select top cell
unexpand
select area labels
expand
set alb_top_labels [lindex [what -list] 1]
select clear
set alb_child_ports_demoted 0
foreach alb_label_entry $alb_top_labels {
    set alb_label_name [lindex $alb_label_entry 0]
    if {[string first $alb_child_prefix $alb_label_name] == 0} {
        # Names are Tcl data, never evaluated. Several labels may share a name
        # or index, so remove by name until no matching port remains.
        while {[port $alb_label_name exists] eq {1}} {
            port $alb_label_name remove
            incr alb_child_ports_demoted
        }
    }
}
select top cell
puts "ALB_CHILD_PORTS_DEMOTED $alb_child_ports_demoted"
set i 1
foreach pin [split $::env(LAYOUT_PORTS) "\\n"] {
    if {[port $pin exists]} {
        port $pin index $i
    } else {
        port $pin make $i
    }
    incr i
}
extract style {ngspice()}
extract do local
extract no corners
extract no resistance
extract do capacitance
extract do coupling
extract do adjust
if {$::env(PEX_MODE) eq "rc"} {
    extresist threshold 0
    extresist minres 1
    extresist mindelay 0
    extresist simplify on
    extresist extout on
    extresist silent off
    extract do resistance
}
extract all
ext2spice default
ext2spice format ngspice
ext2spice scale off
ext2spice merge none
ext2spice hierarchy off
ext2spice subcircuit top on
ext2spice global off
if {$::env(PEX_MODE) eq "c"} {
    ext2spice short resistor
} else {
    ext2spice short none
}
ext2spice rthresh infinite
ext2spice cthresh 0
if {$::env(PEX_MODE) eq "rc"} {
    ext2spice extresist on
} else {
    ext2spice extresist off
}
ext2spice -o extracted.spice $::env(LAYOUT_FLAT_TOP).ext
save $::env(LAYOUT_FLAT_TOP)
puts "PEX_COMPLETE $::env(PEX_MODE)"
quit -noprompt
"""


def extract(gds: Path, top: str, task: Path | None, out: Path, mode: str, timeout: float,
            *, ports: list[str] | None = None, substrate: str | None = None,
            reference: Path | None = None) -> dict:
    out = shared_output(out)
    if mode not in {"c", "rc"} or not IDENTIFIER.fullmatch(top):
        raise ValueError("Invalid extraction mode or top")
    contract = load_task(task) if task is not None else {"top": top, "ports": ports, "substrate": substrate}
    if top != contract["top"]:
        raise ValueError("GDS top differs from the task top")
    validate_ports(contract["ports"])
    if contract.get("substrate") is not None and str(contract["substrate"]).lower() not in {p.lower() for p in contract["ports"]} | {"0"}:
        raise ValueError("Declared substrate must be a top port or node 0")
    runtime = load_runtime()
    rcfile = Path(runtime["magic_rcfile"])
    flat_top = top + "_pex"
    prepared = prepare_magic_input(gds, top, out / "magic_input.gds")
    reference = reference or contract.get("reference")
    floating = reference_floating_ports(reference, top, contract["ports"])
    native_ports, unlabeled_floating = [], []
    for pin in contract["ports"]:
        matches = [label for label in prepared["top_labels"] if port_keys([label]) == port_keys([pin])]
        if len(matches) > 1:
            raise ValueError(f"Ambiguous case-insensitive top label: {pin}")
        if not matches and pin in floating["ports"]:
            # Magic's `port <name> exists` aborts the script for a missing
            # label. Only an unlabeled floating reference port is not requested.
            unlabeled_floating.append(pin)
            continue
        # SPICE/LVS ports are case-insensitive, Magic's label lookup is not.
        native_ports.append(matches[0] if matches else layout_port_name(pin))
    script = out / "extract.tcl"
    script.write_text(TCL)
    env = dict(magic_env(out), LAYOUT_GDS=prepared["path"], LAYOUT_TOP=top, LAYOUT_FLAT_TOP=flat_top,
               LAYOUT_PORTS="\n".join(native_ports),
               LAYOUT_CHILD_PORT_PREFIX=prepared["namespace_prefix"], PEX_MODE=mode,
               PDK_ROOT=str(rcfile.parents[3]), TMPDIR=str(out / "tmp"),
               XDG_CACHE_HOME=str(out / "cache"), PYTHONDONTWRITEBYTECODE="1")
    command = [str(runtime["magic_bin"]), "-dnull", "-noconsole", "-rcfile", str(rcfile), str(script)]
    result = {"status": "tool_error", "mode": mode, "input_gds": str(gds), "input_preparation": prepared,
              "top": top, "ports": contract["ports"], "substrate": contract.get("substrate"),
              "substrate_policy": "GDS labels and process extraction rules; no automatic bulk reconnection",
              "geometry_units": {"pdk_device_length": "um", "pdk_device_area": "um2", "native_resistance": "ohm", "native_capacitance": "F", "basis": "qualified SKY130 ngspice() extraction style with ext2spice scale off"},
              "extraction_qualification": "provisional",
              "limitations": [LIMITATION, "Structural checks do not replace DRC or LVS.", RC_REDUCTION_LIMITATION],
              "settings": {"style": "ngspice()", "cthresh_fF": 0, "merge": "none", "scale": "off",
                           "threshold_milliohm": 0, "minres_milliohm": 1, "mindelay_ps": 0,
                           "simplify": True, "geometric_corners": False,
                           "child_port_policy": "Scoped child labels remain internal; original top-level ports are preserved",
                           "shorted_ports": "zero_ohm_resistor" if mode == "c" else "none_to_preserve_wire_resistance",
                           "rc_reduction": {"algorithm": rc_reduce.ALGORITHM, **RC_REDUCTION,
                                            "growth_guard_above_degree": rc_reduce.GUARD_FREE_DEGREE,
                                            "simulation_netlist": "extracted.spice",
                                            "complete_netlist": RAW_NETLIST}}}
    result["command"] = {"argv": command, **run_command(command, cwd=out, env=env, timeout=timeout)}
    log = Path(result["command"]["log_path"]).read_text(errors="replace")
    result["warnings"] = [line for line in log.splitlines() if re.search(r"warning|error|orphan|not a port|not found|ambiguous", line, re.I)]
    environment_errors = environment_failure_lines(log, rcfile)
    if environment_errors:
        result.update(error="Magic runtime or process setup failed", error_kind="environment_error",
                      environment_error_evidence=environment_errors)
        return result
    if result["command"]["status"] != "completed" or result["command"]["returncode"] != 0:
        result.update(error="Magic did not complete successfully", error_kind="timeout" if result["command"]["status"] == "timeout" else "execution_error")
        return result
    if f"PEX_COMPLETE {mode}" not in log:
        result.update(error="Extraction completion marker missing", error_kind="execution_error")
        return result
    demoted = re.findall(r"^ALB_CHILD_PORTS_DEMOTED (\d+)\s*$", log, re.M)
    if len(demoted) != 1:
        result.update(error="Child-port normalization did not complete", error_kind="execution_error")
        return result
    result["input_preparation"]["demoted_child_ports"] = int(demoted[0])
    extracted = out / "extracted.spice"
    if not extracted.is_file() or not extracted.stat().st_size:
        result.update(error="New extracted netlist missing or empty", error_kind="execution_error")
        return result
    raw = out / RAW_NETLIST
    try:
        extracted.replace(raw)
        result["raw_netlist_path"] = str(raw)
        required, absent = required_extracted_ports(
            contract["ports"], floating["ports"], declared_subckt_pins(raw).get(flat_top.lower()))
        if floating["ports"] or "check_error" in floating:
            result["floating_reference_ports"] = {
                "ports": floating["ports"], "not_requested_from_magic": unlabeled_floating,
                "absent_from_extracted_top": absent,
                "required_ports": required, "reason": FLOATING_PORT_REASON,
                **({"check_error": floating["check_error"]} if "check_error" in floating else {})}
        result["raw_netlist"] = inspect_netlist(raw, required, flat_top)
        if port_keys(result["raw_netlist"]["ports"]) != port_keys(required):
            raise ValueError("Magic did not preserve requested pin order")
        result["rc_reduction"], result["netlist"] = reduce_for_simulation(
            raw, extracted, result["raw_netlist"], required, flat_top)
        if result["rc_reduction"]["status"] != "reduced":
            result["warnings"].append("RC reduction failed; post-layout simulation uses the complete netlist: "
                                      + result["rc_reduction"]["error"])
        res_file = out / (flat_top + ".res.ext")
        res_records = 0
        if res_file.is_file():
            res_records = sum(line.startswith("resist ") for line in res_file.read_text().splitlines())
        if mode == "rc" and not res_records:
            result["warnings"].append("No distributed resistance records were emitted; requested RC mode alone does not prove resistance coverage.")
        result["parasitic_evidence"] = {
            "requested_mode": mode, "resistance_network_file": str(res_file) if res_file.is_file() else None,
            "resistance_network_records": res_records,
            "complete_netlist": str(raw), "simulation_netlist": str(extracted),
            "interpretation": "Magic resistance-network evidence; native R/C counts alone do not distinguish design devices from parasitics. Zero parasitics may be legitimate for small geometry.",
        }
        if reference is not None:
            # The trusted reference declares every contract port, floating or not.
            result["reference_netlist"] = inspect_netlist(Path(reference), contract["ports"], top)
            aliases = reference_model_aliases(Path(reference), contract.get("lvs_resistor_geometry_view"))
            result["model_presence_check"] = model_presence(
                result["reference_netlist"], result["netlist"], aliases=aliases)
            missing = result["model_presence_check"]["missing_models"]
            if missing:
                raise ValueError("Extracted netlist is missing reference PDK models: " + ", ".join(missing))
        result.update(status="completed", netlist_path=str(extracted), netlist_sha256=sha256(extracted))
    except (ValueError, OSError) as exc:
        result.update(status="tool_error", error=str(exc), error_kind="invalid_extracted_netlist")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gds", type=Path, required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--task", type=Path, help="Optional task directory containing constraints.json")
    parser.add_argument("--ports", nargs="+", help="Ordered top ports when --task is omitted")
    parser.add_argument("--substrate", help="Declared substrate net (no automatic reconnection)")
    parser.add_argument("--reference", type=Path, help="Optional device-only reference for diagnostics")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--mode", choices=("rc", "c"), default="rc")
    parser.add_argument("--timeout", type=float, default=180)
    args = parser.parse_args(argv)
    out = args.out.resolve()
    created = False
    try:
        if not math.isfinite(args.timeout) or args.timeout <= 0:
            raise ValueError("Timeout must be positive and finite")
        out = shared_output(out)
        out.mkdir(parents=True, exist_ok=False)
        created = True
        result = extract(args.gds.resolve(strict=True), args.top, args.task.resolve(strict=True) if args.task else None, out, args.mode, args.timeout,
                         ports=args.ports, substrate=args.substrate, reference=args.reference)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result = {"status": "tool_error", "error": str(exc), "extraction_qualification": "provisional", "limitations": [LIMITATION]}
    if created:
        (out / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, allow_nan=False))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
