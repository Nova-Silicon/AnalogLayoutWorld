"""Native SKY130 Magic extraction and Netgen comparison for selected tasks.

The task supplies only the trusted reference and ordered interface. Installed
upstream process files decide device extraction and comparison. No submission
SPICE, cell property, black-box declaration, or pin-order property is trusted.
"""
from __future__ import annotations

from collections import Counter
import json
import os
from pathlib import Path
import re
import time

import klayout.db as kdb

from .pex import (
    IDENTIFIER, environment_failure_lines, inspect_netlist, layout_port_name,
    port_keys, validate_ports,
)


EXTRACT_TCL = """# Inputs arrive as literal environment variables, not Tcl source.
if {[catch {
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
    extract no capacitance
    extract no resistance
    extract no coupling
    extract no adjust
    extract all
    ext2spice lvs
    ext2spice format ngspice
    ext2spice scale off
    ext2spice merge none
    ext2spice hierarchy off
    ext2spice subcircuit top on
    ext2spice global off
    ext2spice short none
    ext2spice extresist off
    ext2spice rthresh infinite
    ext2spice cthresh infinite
    ext2spice -o extracted.spice $::env(LAYOUT_FLAT_TOP).ext
} problem]} {
    puts stderr "ALB_LVS_EXTRACTION_ERROR: $problem"
} else {
    puts "ALB_LVS_EXTRACTION_COMPLETE"
}
quit -noprompt
"""

COMPARE_TCL = """# Native Netgen interface; Tcl lists preserve paths literally.
if {[catch {
    lvs [list $::env(LVS_LAYOUT) $::env(LVS_LAYOUT_TOP)] \\
        [list $::env(LVS_REFERENCE) $::env(LVS_REFERENCE_TOP)] \\
        $::env(LVS_SETUP) report.out -json
} problem]} {
    puts stderr "ALB_NETGEN_ERROR: $problem"
} else {
    puts "ALB_NETGEN_COMPLETE"
}
quit
"""


def geometry_only_gds(source: Path, destination: Path, top: str) -> None:
    """Flatten geometry/text into a fresh database without submitted properties.

    Cell names and GDS properties may otherwise be interpreted as device macros
    or simulator directives by downstream importers. Layer numbers, coordinates,
    paths and labels are preserved; no device layout is repaired or synthesized.
    """
    original = kdb.Layout()
    original.read(str(source))
    cell = original.cell(top)
    if cell is None:
        raise ValueError("Requested extraction top is absent")
    cell.flatten(-1, True)
    clean = kdb.Layout()
    clean.dbu = original.dbu
    flat = clean.create_cell(top)
    for index in original.layer_indices():
        target = clean.layer(original.get_info(index))
        for shape in cell.shapes(index).each():
            flat.shapes(target).insert(shape).clear_properties()
    clean.write(str(destination))


def _pair(value, description: str) -> list:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError(f"Netgen {description} must contain both compared circuits")
    return value


def _pins(value) -> tuple[list[str], list[str]]:
    sides = _pair(value, "pins")
    if any(not isinstance(pins, list) or not pins
           or any(not isinstance(pin, str) or not pin for pin in pins) for pins in sides):
        raise ValueError("Netgen pin comparison is missing or malformed")
    return sides[0], sides[1]


def _devices(value) -> Counter:
    if not isinstance(value, list):
        raise ValueError("Netgen device summary must be a list")
    counts = Counter()
    for entry in value:
        if (not isinstance(entry, list) or len(entry) != 2
                or not isinstance(entry[0], str) or not entry[0]
                or type(entry[1]) is not int or entry[1] < 0):
            raise ValueError("Netgen device count is missing or malformed")
        counts[entry[0].casefold()] += entry[1]
    return counts


def netgen_report(path: Path, transcript: Path, layout_top: str,
                  reference_top: str, ports: list[str]) -> dict:
    """Require a complete top comparison, including properties and every port.

    Netgen can exit zero and print 'Circuits match uniquely' despite property
    errors. Its JSON omits ``properties`` when there are none, but structural
    top fields are mandatory. Primitive-model rows may contain only ``pins``.
    """
    rows = json.loads(path.read_text())
    if not isinstance(rows, list) or not rows or any(not isinstance(row, dict) or not row for row in rows):
        raise ValueError("Netgen report contains no valid comparisons")
    expected = [layout_top.casefold(), reference_top.casefold()]
    tops = [row for row in rows if isinstance(row.get("name"), list)
            and [str(name).casefold() for name in row["name"]] == expected]
    if len(tops) != 1:
        raise ValueError("Netgen report lacks one unambiguous requested top comparison")
    top = tops[0]
    errors = []
    for index, row in enumerate(rows):
        for key in ("badnets", "badelements", "properties"):
            if key in row:
                if not isinstance(row[key], list):
                    raise ValueError(f"Netgen {key} field is malformed")
                if row[key]:
                    errors.append({"comparison": index, "kind": key, "details": row[key]})
        if "pins" in row:
            left, right = _pins(row["pins"])
            if port_keys(left) != port_keys(right):
                errors.append({"comparison": index, "kind": "pins", "details": row["pins"]})
        if row is not top and "name" in row:
            # This backend extracts a flattened circuit. An unexpected named
            # child cannot silently stand in for unverified hierarchical logic.
            raise ValueError("Unexpected hierarchical circuit in flat LVS report")
        if row is not top and "pins" not in row:
            raise ValueError("Incomplete primitive comparison in Netgen report")
    for key in ("devices", "nets", "badnets", "badelements", "pins"):
        if key not in top:
            raise ValueError(f"Netgen top comparison is missing {key}")
    devices = [_devices(side) for side in _pair(top["devices"], "devices")]
    nets = _pair(top["nets"], "nets")
    if any(type(count) is not int or count <= 0 for count in nets):
        raise ValueError("Netgen net counts must be positive integers")
    first, second = _pins(top["pins"])
    expected_pins = set(port_keys(ports))
    ports_match = (len(first) == len(second) == len(ports)
                   and port_keys(first) == port_keys(second)
                   and set(port_keys(first)) == expected_pins)
    text = transcript.read_text(errors="replace")
    final_matches = bool(re.search(r"^Final result:\s*Circuits match uniquely\.\s*$", text, re.M))
    textual_errors = bool(re.search(
        r"Property errors were found|following cells had property errors|"
        r"following subcells failed to match", text, re.I))
    matches = (not errors and not textual_errors and final_matches and ports_match
               and nets[0] == nets[1] and devices[0] == devices[1]
               and all(sum(side.values()) > 0 for side in devices))
    return {"matches": matches, "top_ports_match": ports_match,
            "layout_devices": sum(devices[0].values()),
            "reference_devices": sum(devices[1].values()), "nets": nets,
            "device_counts": [dict(side) for side in devices],
            "pin_pairs": top["pins"], "comparison_errors": errors,
            "final_unique_match": final_matches, "textual_property_or_subcell_error": textual_errors}


def run_lvs(gds: Path, reference: Path, contract: dict, out: Path,
            runtime: dict, timeout: float, result: dict) -> None:
    """Populate the verifier result; honor its optional unlimited-tool policy."""
    from .runtime import magic_env, run_command
    from .verify import require_fresh

    started = time.monotonic()
    no_timeout = os.environ.get("ALB_VERIFIER_NO_TIMEOUT") == "1"
    top, ports = contract["top"], contract["ports"]
    if not IDENTIFIER.fullmatch(top):
        raise ValueError("Magic LVS requires a literal valid top name")
    validate_ports(ports)
    for key in ("netgen_bin", "netgen_setup", "magic_bin", "magic_rcfile"):
        if not runtime.get(key) or not Path(runtime[key]).is_file():
            raise ValueError(f"Missing installed Magic/Netgen runtime file: {key}")
    result.update(backend="magic_netgen", extraction={
        "style": "ngspice()", "geometry": "flattened GDS without properties",
        "reference": "unmodified task circuit.spice", "merge": "none",
        "substrate": "native process extraction; no automatic bulk reconnection",
    })
    clean_gds = out / "geometry.gds"
    geometry_only_gds(gds, clean_gds, top)
    flat_top = top + "_lvs"
    magic_dir, netgen_dir = out / "magic", out / "netgen"
    magic_dir.mkdir()
    netgen_dir.mkdir()
    script = magic_dir / "extract.tcl"
    script.write_text(EXTRACT_TCL)
    rcfile = Path(runtime["magic_rcfile"])
    env = dict(magic_env(out), LAYOUT_GDS=str(clean_gds), LAYOUT_TOP=top,
               LAYOUT_FLAT_TOP=flat_top, LAYOUT_PORTS="\n".join(layout_port_name(p) for p in ports),
               PDK_ROOT=str(rcfile.parents[3]))
    command = [str(runtime["magic_bin"]), "-dnull", "-noconsole", "-rcfile", str(rcfile), str(script)]
    result["magic_command"] = command
    remaining = timeout if no_timeout else timeout - (time.monotonic() - started)
    if remaining <= 0:
        result["error_kind"] = "timeout"
        raise RuntimeError("LVS budget exhausted during GDS preparation")
    started_ns = time.time_ns()
    execution = run_command(command, cwd=magic_dir, env=env, timeout=remaining)
    result["magic_execution"] = execution
    log = (magic_dir / "command.log").read_text(errors="replace")
    failures = environment_failure_lines(log, rcfile)
    if failures:
        raise RuntimeError("Magic process setup failed: " + "; ".join(failures))
    if execution["status"] != "completed" or execution["returncode"] != 0:
        result["error_kind"] = "timeout" if execution["status"] == "timeout" else "execution_error"
        raise RuntimeError(f"Magic execution {execution['status']}, exit {execution['returncode']}")
    if "ALB_LVS_EXTRACTION_COMPLETE" not in log:
        result["error_kind"] = "execution_error"
        raise RuntimeError("Magic LVS extraction completion marker missing")
    extracted = magic_dir / "extracted.spice"
    require_fresh(extracted, started_ns)
    try:
        result["extracted_netlist"] = inspect_netlist(extracted, ports, flat_top)
        if port_keys(result["extracted_netlist"]["ports"]) != port_keys(ports):
            raise ValueError("Magic did not preserve the task's ordered top ports")
    except ValueError as error:
        result.update(status="failed", reason=str(error), error_kind="design_error")
        return
    (out / "extracted.spice").write_bytes(extracted.read_bytes())
    script = netgen_dir / "compare.tcl"
    script.write_text(COMPARE_TCL)
    env.update(LVS_LAYOUT=str(extracted), LVS_LAYOUT_TOP=flat_top,
               LVS_REFERENCE=str(reference), LVS_REFERENCE_TOP=top,
               LVS_SETUP=str(runtime["netgen_setup"]))
    command = [str(runtime["netgen_bin"]), "-batch", "source", str(script)]
    result["netgen_command"] = command
    remaining = timeout if no_timeout else timeout - (time.monotonic() - started)
    if remaining <= 0:
        result["error_kind"] = "timeout"
        raise RuntimeError("LVS budget exhausted before Netgen comparison")
    started_ns = time.time_ns()
    execution = run_command(command, cwd=netgen_dir, env=env, timeout=remaining)
    result["netgen_execution"] = execution
    if execution["status"] != "completed" or execution["returncode"] != 0:
        result["error_kind"] = "timeout" if execution["status"] == "timeout" else "execution_error"
        raise RuntimeError(f"Netgen execution {execution['status']}, exit {execution['returncode']}")
    log = (netgen_dir / "command.log").read_text(errors="replace")
    if "ALB_NETGEN_COMPLETE" not in log:
        raise RuntimeError("Netgen comparison completion marker missing")
    if re.search(r"errors reading the setup file|Cannot read the setup file|"
                 r"Setup file .+ does not exist|No setup file specified|Error .+:\d+ \(ignoring\)", log, re.I):
        raise RuntimeError("Netgen did not load its upstream process setup successfully")
    for filename in ("report.json", "report.out"):
        require_fresh(netgen_dir / filename, started_ns)
    details = netgen_report(netgen_dir / "report.json", netgen_dir / "report.out",
                            flat_top, top, ports)
    result.update(details=details, report=str(netgen_dir / "report.json"),
                  status="passed" if details["matches"] else "failed")
