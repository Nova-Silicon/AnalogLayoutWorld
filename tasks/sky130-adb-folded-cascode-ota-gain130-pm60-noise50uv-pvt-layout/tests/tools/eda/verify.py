"""Fixed SKY130 checks. Each invocation requires a new output directory.

Area is the axis-aligned bounding box of recursive manufacturing geometry, in
square micrometres. Text, pin/label layers and auxiliary boundaries are excluded.
The layer list is part of this verifier's policy, never supplied by the agent.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
import os
from pathlib import Path
import re
import shutil
import time
import xml.etree.ElementTree as ET

import klayout.db as kdb
from .area_extracted import AREA_DEFINITION, AREA_VERSION
from .pex import layout_port_name


MANUFACTURING_LAYERS = {
    "dnwell": (64, 18), "nwell": (64, 20), "pwell": (64, 44),
    "diff": (65, 20), "tap": (65, 44), "poly": (66, 20),
    "pwbm": (19, 44), "pwde": (124, 20), "hvtr": (18, 20),
    "hvtp": (78, 44), "ldntm": (11, 44), "hvi": (75, 20),
    "tunm": (80, 20), "lvtn": (125, 44), "hvntm": (125, 20),
    "nsdm": (93, 44), "psdm": (94, 20), "rpm": (86, 20),
    "urpm": (79, 20), "npc": (95, 20), "licon1": (66, 44),
    "li1": (67, 20), "mcon": (67, 44),
    **{f"met{i}": (67 + i, 20) for i in range(1, 6)},
    **{("via" if i == 1 else f"via{i}"): (67 + i, 44) for i in range(1, 5)},
    "capm": (89, 44), "cap2m": (97, 44), "pad": (76, 20),
    "nsm": (61, 20), "rdl": (74, 20), "rdlcon": (13, 0),
}


class DesignFailure(ValueError):
    """The submitted layout violates the input/geometry contract."""


def extracted_area_metrics(gds: Path, top: str, task: Path, total_area_um2: float,
                           lvs_result_path: Path | None = None) -> dict:
    """Measure only saved, matching LVS evidence; never invoke an EDA tool.

    A manufacturing bounding box remains useful when LVS fails. In that case
    no device correspondence is qualified and the device-area ratio is absent.
    The evaluator independently replays this read-only calculation before it
    accepts the area stage, rather than accepting an agent-authored numerator.
    """
    from .runtime import sha256

    if not math.isfinite(total_area_um2) or total_area_um2 <= 0:
        raise ValueError("Total manufacturing area must be positive and finite")
    base = {"area_version": AREA_VERSION, "area_utilization_definition": AREA_DEFINITION,
            "effective_area_um2": None, "extracted_area_um2": None,
            "raw_area_utilization": None, "area_utilization": None,
            "kind_totals_um2": None, "area_utilization_status": "not_applicable",
            "device_area": None, "device_area_evidence": None}
    if lvs_result_path is None:
        return {**base, "area_utilization_reason": "A successful matching LVS result is required"}
    lvs_result_path = Path(lvs_result_path)
    if lvs_result_path.is_symlink() or not lvs_result_path.is_file():
        raise ValueError("LVS area evidence must be a regular result file")
    lvs = json.loads(lvs_result_path.read_text())
    if (lvs.get("check") != "lvs" or lvs.get("status") != "passed"
            or lvs.get("top", "").casefold() != top.casefold()
            or lvs.get("input_sha256") != sha256(gds)):
        raise ValueError("Device-area evidence is not a successful LVS of the submitted GDS")
    constraints = json.loads((task / "constraints.json").read_text())
    backend = constraints.get("lvs_backend", "klayout")
    if lvs.get("backend", "klayout") != backend:
        raise ValueError("Device-area LVS backend differs from the trusted task")
    source = task / "circuit.spice"
    if backend == "klayout":
        from .area_extracted import extract_device_area
        detail = extract_device_area(lvs_result_path.parent / "report.lvsdb", top=top,
                                     lvs_result_path=lvs_result_path,
                                     source_netlist_path=source)
    elif backend == "magic_netgen":
        from .area_magic_extracted import extract_from_result
        detail = extract_from_result(lvs_result_path, top=top, source_netlist_path=source)
    else:
        raise ValueError(f"Unknown LVS area backend: {backend!r}")
    area = detail.get("area_um2")
    totals = detail.get("kind_totals_um2")
    if (detail.get("status") != "complete" or type(area) not in (int, float)
            or not math.isfinite(area) or area <= 0 or not isinstance(totals, dict)
            or any(type(value) not in (int, float) or not math.isfinite(value) or value < 0
                   for value in totals.values())
            or not math.isclose(math.fsum(totals.values()), area, rel_tol=1e-12, abs_tol=1e-8)):
        raise ValueError("Native device-area measurement is incomplete or inconsistent")
    ratio = area / total_area_um2
    if not math.isfinite(ratio) or ratio <= 0:
        raise ValueError("Native device-area ratio must be positive and finite")
    return {**base, "effective_area_um2": area, "extracted_area_um2": area,
            "raw_area_utilization": ratio, "area_utilization": ratio,
            "kind_totals_um2": totals, "area_utilization_status": "measured",
            "area_utilization_reason": None, "device_area": detail,
            "device_area_evidence": {"lvs_result_path": str(lvs_result_path),
                "lvs_result_sha256": sha256(lvs_result_path), "gds_sha256": sha256(gds),
                "source_netlist_sha256": sha256(source), "lvs_backend": backend}}




def geometry(gds: Path, top: str) -> dict:
    layout = kdb.Layout()
    try:
        layout.read(str(gds))
    except Exception as error:
        raise DesignFailure(f"Cannot read submitted GDS: {type(error).__name__}") from error
    tops = [cell.name for cell in layout.top_cells()]
    if top not in tops:
        raise DesignFailure(f"Required top-level cell {top!r} is missing")
    if not math.isfinite(layout.dbu) or layout.dbu <= 0:
        raise DesignFailure("Invalid GDS database unit")
    cell = layout.cell(top)
    bounds = kdb.Box()
    present = {}
    for name, layer in MANUFACTURING_LAYERS.items():
        index = layout.find_layer(*layer)
        if index is None:
            continue
        region = kdb.Region(cell.begin_shapes_rec(index))
        if not region.is_empty() and region.area() > 0:
            bounds += region.bbox()
            present[name] = list(layer)
    if bounds.empty() or not present:
        raise DesignFailure("Top cell has no nonempty manufacturing geometry")
    width, height = bounds.width() * layout.dbu, bounds.height() * layout.dbu
    area = width * height
    if not all(math.isfinite(value) and value > 0 for value in (width, height, area)):
        raise DesignFailure("Manufacturing geometry has invalid area")
    return {
        "top": top, "top_cells": tops, "dbu_um": layout.dbu,
        "bbox_um": [coordinate * layout.dbu for coordinate in
                    (bounds.left, bounds.bottom, bounds.right, bounds.top)],
        "width_um": width, "height_um": height, "area_um2": area,
        "area_definition": "recursive_manufacturing_geometry_bounding_box",
        "manufacturing_layers": {name: list(layer) for name, layer in MANUFACTURING_LAYERS.items()},
        "present_manufacturing_layers": present,
    }


def task_contract(task: Path, top: str) -> dict:
    contract = json.loads((task / "constraints.json").read_text())
    if not isinstance(contract, dict) or not isinstance(contract.get("top"), str):
        raise ValueError("constraints.json must specify top")
    if top != contract["top"]:
        raise DesignFailure("Requested top differs from the task's declared top")
    ports = contract.get("ports")
    if (not isinstance(ports, list) or not ports
            or any(not isinstance(port, str) or not port for port in ports)
            or len({port.casefold() for port in ports}) != len(ports)):
        raise ValueError("constraints.json must specify unique nonempty ports")
    substrate = contract.get("substrate", "vss")
    if not isinstance(substrate, str) or substrate.casefold() not in {p.casefold() for p in ports}:
        raise ValueError("Task substrate must be a declared port")
    text = (task / "circuit.spice").read_text()
    text = re.sub(r"\n\s*\+", " ", text)
    declarations = re.findall(r"^\s*\.subckt\s+(\S+)\s+([^\n]+)", text, re.I | re.M)
    matches = [pins.split() for name, pins in declarations if name.casefold() == top.casefold()]
    if len(matches) != 1 or [p.casefold() for p in matches[0]] != [p.casefold() for p in ports]:
        raise ValueError("Reference subcircuit declaration disagrees with task top/ordered ports")
    return {"top": top, "ports": ports, "substrate": substrate}


def require_fresh(path: Path, started_ns: int) -> None:
    if not path.is_file() or path.is_symlink() or path.stat().st_size == 0:
        raise RuntimeError(f"Missing or empty tool artifact: {path.name}")
    # New output directories prevent reuse; this also detects copied old artifacts.
    if path.stat().st_mtime_ns < started_ns - 1_000_000_000:
        raise RuntimeError(f"Stale tool artifact: {path.name}")


def drc_report(path: Path, top: str) -> dict:
    root = ET.parse(path).getroot()
    if (root.tag != "report-database" or root.findtext("top-cell") != top
            or root.find("items") is None or not root.findall(".//categories/category")):
        raise RuntimeError("DRC report is incomplete or belongs to a different top cell")
    items = root.findall("./items/item")
    return {"markers": len(items),
            "categories": dict(Counter(item.findtext("category", "") for item in items)),
            "matches": not items}


FLOATING_PORT_REASON = ("Reference top-subcircuit port net connects to no device or subcircuit "
                        "terminal; exempt from top-port pairing only (a layout label is accepted)")


def floating_reference_ports(reference: Path, contract: dict) -> dict:
    """Contract ports that are electrically floating in the trusted reference.

    Same rule as PEX and the post-layout adapter (eda.pex, eda.area_v2). If the
    reference cannot be parsed, nothing is exempt and the strict rule remains.
    """
    from .pex import reference_floating_ports

    return reference_floating_ports(Path(reference), contract["top"], contract["ports"])


def lvs_report(path: Path, top: str, ports: list[str], *,
               floating_ports: list[str] | tuple = ()) -> dict:
    """``floating_ports`` are contract ports with no reference connection.

    They are removed from the required pin set; a pin pair naming only such a
    port (present in the layout, the reference, or both) is accepted. Every
    other pin keeps the historical exact-pairing rule.
    """
    database = kdb.LayoutVsSchematic()
    database.read(str(path))
    entries = list(database.each_log_entry())
    # The submitted circuit is final: no future parent may complete its wiring.
    # KLayout's default top_level(false) reports unresolved implicit/explicit
    # connections as must-connect warnings; top_level(true) makes them errors.
    # Enforce that native constraint here without changing the upstream deck or
    # losing its comparison report to an early extraction exception.
    # https://www.klayout.de/doc/about/drc_ref_netter.html#top_level
    extraction_passed = not any(
        entry.severity == kdb.LogEntryData.Error or entry.category_name == "must-connect"
        for entry in entries
    )
    diagnostics = [{"severity": str(entry.severity), "category": entry.category_name,
                    "cell": entry.cell_name, "message": entry.message}
                   for entry in entries]
    xref = database.xref()
    if xref is None:
        raise RuntimeError("LVS report has no comparison cross-reference")
    pairs = list(xref.each_circuit_pair())
    if not pairs:
        raise RuntimeError("LVS report contains no compared circuits")
    circuits, top_pairs = [], []
    for pair in pairs:
        first, second = pair.first(), pair.second()
        circuits.append({"layout": first.name if first else None,
                         "reference": second.name if second else None,
                         "status": str(pair.status())})
        if first and second and first.name.casefold() == top.casefold() and second.name.casefold() == top.casefold():
            top_pairs.append(pair)
    top_pair = top_pairs[0] if len(top_pairs) == 1 else None
    if top_pair is None:
        reference_tops = [pair for pair in pairs if pair.second()
                          and pair.second().name.casefold() == top.casefold()]
        # A missing layout counterpart is a valid native mismatch, not a
        # corrupt report. Keep other missing/ambiguous comparisons as errors.
        if not (not top_pairs and len(reference_tops) == 1
                and reference_tops[0].first() is None
                and reference_tops[0].status() == kdb.NetlistCrossReference.Mismatch):
            raise RuntimeError("LVS report lacks one unambiguous requested top comparison")
    pin_pairs = [{"layout": pair.first().name() if pair.first() else None,
                  "reference": pair.second().name() if pair.second() else None,
                  "status": str(pair.status())}
                 for pair in xref.each_pin_pair(top_pair)] if top_pair is not None else []
    floating = {layout_port_name(port).casefold() for port in floating_ports}
    expected = {layout_port_name(port).casefold() for port in ports} - floating

    def floating_pair(pair):
        names = {pair[side].casefold() for side in ("layout", "reference") if pair[side] is not None}
        return len(names) == 1 and names <= floating

    checked = [pair for pair in pin_pairs if not floating_pair(pair)]
    ports_match = top_pair is not None and len(checked) == len(expected) and all(
        pair["layout"] is not None and pair["reference"] is not None
        and pair["layout"].casefold() == pair["reference"].casefold()
        and pair["status"] == "Match" for pair in checked
    ) and {pair["layout"].casefold() for pair in checked if pair["layout"] is not None} == expected
    counts = [sum(1 for circuit in netlist.each_circuit() for _ in circuit.each_device())
              for netlist in (xref.netlist_a(), xref.netlist_b())]
    report = {"circuits": circuits, "pin_pairs": pin_pairs,
              "layout_devices": counts[0], "reference_devices": counts[1],
              "top_ports_match": ports_match,
              "extraction_passed": extraction_passed, "extraction_diagnostics": diagnostics,
              "matches": extraction_passed and ports_match
                         and all(circuit["status"] == "Match" for circuit in circuits)
                         and all(count > 0 for count in counts)}
    if floating_ports:
        report.update(floating_reference_ports=list(floating_ports),
                      required_top_ports=[port for port in ports
                                          if layout_port_name(port).casefold() in expected],
                      accepted_floating_pin_pairs=[pair for pair in pin_pairs if floating_pair(pair)])
    return report


def _verify_one(mode: str, gds: Path, top: str, task: Path, out: Path, timeout: float = 180,
                *, lvs_result_path: Path | None = None, runtime_override: dict | None = None,
                deck_override: Path | None = None, deadline: float | None = None) -> dict:
    from .runtime import klayout_env, load_runtime, run_command, sha256, shared_output

    result = {"check": mode, "status": "error", "top": top, "out": str(out.resolve())}
    created = False
    try:
        out = shared_output(out)
        out.mkdir(parents=True, exist_ok=False)
        created = True
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        contract = task_contract(task, top)
        snapshot = out / "input.gds"
        if not gds.is_file():
            raise DesignFailure("Submitted GDS is missing")
        shutil.copyfile(gds, snapshot)
        shutil.copyfile(task / "constraints.json", out / "constraints.json")
        shutil.copyfile(task / "circuit.spice", out / "reference.spice")
        result.update(input_sha256=sha256(snapshot), reference_sha256=sha256(out / "reference.spice"),
                      constraints_sha256=sha256(out / "constraints.json"), contract=contract)
        result["geometry"] = geometry(snapshot, top)
        if mode == "area":
            result.update(extracted_area_metrics(snapshot, top, task,
                          result["geometry"]["area_um2"], lvs_result_path))
            result.update(status="measured", area_um2=result["geometry"]["area_um2"])
            return result
        runtime = runtime_override if runtime_override is not None else load_runtime()
        if mode == "lvs":
            backend = json.loads((out / "constraints.json").read_text()).get("lvs_backend", "klayout")
            if backend not in {"klayout", "magic_netgen"}:
                raise ValueError(f"Unknown LVS backend: {backend!r}")
            result["backend"] = backend
            if backend == "magic_netgen":
                from .magic_netgen import run_lvs

                run_lvs(snapshot, out / "reference.spice", contract, out, runtime, timeout, result)
                return result
            # Read the unmodified trusted copy, before any reference view rewrite.
            floating = floating_reference_ports(out / "reference.spice", contract)
            result["floating_reference_ports"] = [{"port": port, "reason": FLOATING_PORT_REASON}
                                                  for port in floating["ports"]]
            if "check_error" in floating:
                result["floating_reference_port_check_error"] = floating["check_error"]
        original_deck = deck_override if deck_override is not None else Path(runtime[f"{mode}_deck"])
        resistor_view = json.loads((out / "constraints.json").read_text()).get("lvs_resistor_geometry_view")
        if mode == "lvs" and resistor_view is not None:
            from .resistor_reference import QUALIFIED_VIEWS, resistor_reference_view
            from .reference import supported_model_primitives

            if resistor_view not in QUALIFIED_VIEWS:
                raise ValueError(f"Unknown LVS resistor geometry view: {resistor_view!r}")
            geometry_model = QUALIFIED_VIEWS[resistor_view][1]
            if supported_model_primitives(original_deck.read_text()).get(geometry_model) != "R":
                raise ValueError("Installed LVS reader does not support the required resistor family")
            original_reference = out / "reference.before-resistor.spice"
            (out / "reference.spice").rename(original_reference)
            reference, mappings = resistor_reference_view(original_reference.read_text(), resistor_view)
            if not mappings:
                raise ValueError("Declared resistor geometry view found no matching physical resistors")
            (out / "reference.spice").write_text(reference)
            result["resistor_geometry_reference"] = mappings
            result["reference_sha256"] = sha256(out / "reference.spice")
        normalization = json.loads((out / "constraints.json").read_text()).get("lvs_reference_normalization")
        if mode == "lvs" and normalization is not None:
            if normalization != "supported_model_instance_names_only":
                raise ValueError(f"Unknown LVS reference normalization: {normalization!r}")
            from .reference import write_normalized_reference

            original_reference = out / "reference.original.spice"
            (out / "reference.spice").rename(original_reference)
            result["reference_normalization"] = write_normalized_reference(
                original_reference, out / "reference.spice",
                out / "reference-name-map.json", original_deck,
            )
            result["original_reference_sha256"] = result["reference_sha256"]
            result["reference_sha256"] = sha256(out / "reference.spice")
        mim_view = json.loads((out / "constraints.json").read_text()).get("lvs_mim_geometry_view")
        if mode == "lvs" and mim_view is not None:
            from .mim_reference import write_mim_reference_view
            from .lvs_policy import is_qualified_deck_sha256

            if mim_view not in {"mim_m3_literal_um_mult1", "mim_geometry_literal_um"} or not is_qualified_deck_sha256(sha256(original_deck)):
                raise ValueError("MIM physical reference requires the qualified adapter and exact deck version")
            name_reference = out / "reference.before-mim.spice"
            (out / "reference.spice").rename(name_reference)
            result["mim_geometry_reference"] = write_mim_reference_view(
                name_reference, out / "reference.spice", out / "reference-mim-map.json",
            )
            result["reference_sha256"] = sha256(out / "reference.spice")
        bjt_view = json.loads((out / "constraints.json").read_text()).get("lvs_bjt_parallel_view")
        if mode == "lvs" and bjt_view is not None:
            from .bjt_reference import bjt_reference_view
            from .lvs_policy import is_qualified_deck_sha256

            if bjt_view != "pnp_0p68_integer_m" or not is_qualified_deck_sha256(sha256(original_deck)):
                raise ValueError("PNP parallel view requires the qualified model and rule version")
            original_reference = out / "reference.before-bjt.spice"
            (out / "reference.spice").rename(original_reference)
            reference, mappings = bjt_reference_view(original_reference.read_text())
            (out / "reference.spice").write_text(reference)
            result["bjt_parallel_reference"] = mappings
            result["reference_sha256"] = sha256(out / "reference.spice")
        deck = out / ("run.drc" if mode == "drc" else "run.lvs")
        source = original_deck.read_text()
        flags = {"input": str(snapshot), "top_cell": top, "thr": "2"}
        report = out / ("report.lyrdb" if mode == "drc" else "report.lvsdb")
        flags["report"] = str(report)
        if mode == "drc":
            flags.update(feol="true", beol="true", offgrid="true", floating_met="true",
                         sram_exclude="false", seal="false", info="false")
        elif mode == "lvs":
            from .lvs_policy import DUMMY_PURGE_DECK_SHA256, DUMMY_PURGE_FLAGS

            if sha256(original_deck) == DUMMY_PURGE_DECK_SHA256:
                flags.update(DUMMY_PURGE_FLAGS)
            # Keep native extraction diagnostics in the report for lvs_report()
            # to reject, instead of aborting before the report can be written.
            # https://www.klayout.de/doc/about/drc_ref_netter.html#ignore_extraction_errors
            source = "ignore_extraction_errors(true)\n" + source
            source += '''\n# Required external-port binding check, using KLayout's official API.
require "json"
alb_ports_valid = flag_missing_ports
File.write($ports_result, JSON.generate({completed: true, top_ports_valid: alb_ports_valid}))
exit(2) unless alb_ports_valid
'''
            flags.update(schematic=str(out / "reference.spice"),
                         target_netlist=str(out / "extracted.spice"), run_mode="deep",
                         convert_subckts="true", scale="true", schematic_simplify="true", spice_net_names="true",
                         spice_comments="true", verbose="true", lvs_sub=layout_port_name(contract["substrate"]),
                         ports_result=str(out / "ports.json"))
        else:
            raise ValueError(f"Unknown check: {mode}")
        deck.write_text(source)
        command = [str(runtime["klayout_bin"]), "-b", "-r", str(deck)]
        for key, value in flags.items():
            command.extend(["-rd", f"{key}={value}"])
        result.update(command=command, original_deck_sha256=sha256(original_deck),
                      effective_deck_sha256=sha256(deck), flags=flags)
        if deadline is not None:
            timeout = min(timeout, deadline - time.monotonic())
            if timeout <= 0:
                result["error_kind"] = "timeout"
                raise RuntimeError("LVS time budget exhausted before tool execution")
        started_ns = time.time_ns()
        execution = run_command(command, cwd=out, env=klayout_env(out), timeout=timeout)
        result["execution"] = execution
        if execution["status"] == "timeout":
            result["error_kind"] = "timeout"
        if execution["status"] != "completed":
            raise RuntimeError(f"KLayout execution {execution['status']}")
        if execution["returncode"] not in ({0} if mode == "drc" else {0, 1, 2}):
            raise RuntimeError(f"KLayout exited with code {execution['returncode']}")
        require_fresh(report, started_ns)
        details = drc_report(report, top) if mode == "drc" else lvs_report(
            report, top, contract["ports"],
            floating_ports=[row["port"] for row in result["floating_reference_ports"]])
        result.update(details=details, report=str(report), report_sha256=sha256(report))
        if mode == "lvs":
            require_fresh(out / "extracted.spice", started_ns)
            result["extracted_sha256"] = sha256(out / "extracted.spice")
            if execution["returncode"] == 0:
                require_fresh(out / "ports.json", started_ns)
                checked_ports = json.loads((out / "ports.json").read_text())
                if checked_ports != {"completed": True, "top_ports_valid": True}:
                    raise RuntimeError("LVS did not complete the mandatory top-port check")
        result["status"] = "passed" if details["matches"] and execution["returncode"] == 0 else "failed"
    except DesignFailure as error:
        result.update(status="failed", reason=str(error))
    except Exception as error:
        result.update(status="error", reason=f"{type(error).__name__}: {error}")
    finally:
        if created:
            (out / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def _retryable_lvs_mismatch(result: dict) -> bool:
    """A valid comparison mismatch may benefit from same-net cleanup.

    Input, extraction, missing-port and infrastructure errors are not dummy
    mismatches. Do not retry them or grant a new budget after a timeout.
    Native pin-pair statuses can themselves be Mismatch until extra devices
    are removed, so the alternative still performs its full independent check.
    """
    details = result.get("details", {})
    execution = result.get("execution", {})
    return (result.get("status") == "failed"
            and execution.get("status") == "completed"
            and execution.get("returncode") in (0, 1)
            and details.get("extraction_passed") is True
            and details.get("layout_devices", 0) > 0
            and details.get("reference_devices", 0) > 0)


def _verify_lvs_alternatives(gds: Path, top: str, task: Path, out: Path,
                             timeout: float, runtime: dict) -> dict:
    from .lvs_policy import POLICY_VERSION, dummy_purge_deck
    from .runtime import shared_output

    result = {"check": "lvs", "status": "error", "top": top, "out": str(out.resolve())}
    created = False
    attempts = []
    selected_path = None
    policy = {"version": POLICY_VERSION, "selected": None, "attempts": attempts}
    try:
        out = shared_output(out)
        out.mkdir(parents=True, exist_ok=False)
        created = True
        if not math.isfinite(timeout) or timeout <= 0:
            raise ValueError("timeout must be positive and finite")
        # Formal evaluation disables individual EDA caps in favour of its one
        # outer verifier budget. Preserve that behaviour across both attempts.
        deadline = (None if os.environ.get("ALB_VERIFIER_NO_TIMEOUT") == "1"
                    else time.monotonic() + timeout)
        (out / "attempts").mkdir()
        original = None
        for name, deck in (("original", Path(runtime["lvs_deck"])), ("same_net_v2", None)):
            if name == "same_net_v2":
                if not _retryable_lvs_mismatch(original):
                    policy["fallback"] = "not_needed" if original["status"] == "passed" else "not_a_comparison_mismatch"
                    break
                if deadline is not None and deadline <= time.monotonic():
                    policy["fallback"] = "shared_time_budget_exhausted"
                    result.update(status="error", error_kind="timeout",
                                  reason="LVS time budget exhausted before the reviewed alternative")
                    break
                deck = dummy_purge_deck()
            attempt_path = out / "attempts" / name
            current = _verify_one("lvs", gds, top, task, attempt_path, timeout,
                                  runtime_override=runtime, deck_override=deck, deadline=deadline)
            attempts.append({"name": name, "status": current["status"],
                "result": str(attempt_path / "result.json"),
                "deck_sha256": current.get("original_deck_sha256"),
                "report_sha256": current.get("report_sha256"),
                "error_kind": current.get("error_kind"), "reason": current.get("reason"),
                "execution": current.get("execution")})
            if original is not None and any(current.get(key) != original.get(key)
                    for key in ("input_sha256", "constraints_sha256", "reference_sha256", "contract")):
                raise RuntimeError("LVS alternatives did not compare identical trusted inputs")
            result = {**current, "out": str(out)}
            selected_path = attempt_path
            policy["selected"] = name
            if name == "original":
                original = current
            else:
                policy["fallback"] = "original_comparison_mismatch"
        # Preserve conventional artifact names for area and evaluate.py while
        # retaining each command's actual immutable working directory.
        for path in selected_path.iterdir():
            if path.name != "result.json" and path.is_file() and not path.is_symlink():
                shutil.copyfile(path, out / path.name)
        if result.get("report"):
            result["report"] = str(out / "report.lvsdb")
    except Exception as error:
        result.update(status="error", reason=f"{type(error).__name__}: {error}")
    finally:
        if created:
            result["lvs_policy"] = policy
            (out / "result.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def verify(mode: str, gds: Path, top: str, task: Path, out: Path, timeout: float = 180,
           *, lvs_result_path: Path | None = None) -> dict:
    """Keep one public interface; only the reviewed KLayout backend uses OR."""
    from .lvs_policy import ORIGINAL_DECK_SHA256
    from .runtime import load_runtime, sha256

    if mode == "lvs":
        try:
            backend = json.loads((task / "constraints.json").read_text()).get("lvs_backend", "klayout")
            runtime = load_runtime()
            qualified = backend == "klayout" and sha256(Path(runtime["lvs_deck"])) == ORIGINAL_DECK_SHA256
        except Exception:
            qualified = False  # The ordinary path reports the original input/runtime error.
        if qualified:
            return _verify_lvs_alternatives(gds, top, task, out, timeout, runtime)
    # Magic/Netgen, DRC/area and unreviewed development decks retain their
    # existing behaviour. Arbitrary decks never inherit the reviewed fallback.
    return _verify_one(mode, gds, top, task, out, timeout, lvs_result_path=lvs_result_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("check", choices=("drc", "lvs", "area"))
    parser.add_argument("--gds", type=Path, required=True)
    parser.add_argument("--top", required=True)
    parser.add_argument("--task", type=Path, required=True, help="Trusted task input directory")
    parser.add_argument("--out", type=Path, required=True, help="New output directory; existing paths are rejected")
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--lvs-result", type=Path,
                        help="Saved trusted LVS result for device area; without it only bbox is measured")
    args = parser.parse_args()
    result = verify(args.check, args.gds, args.top, args.task, args.out, args.timeout,
                    lvs_result_path=args.lvs_result)
    print(json.dumps(result, indent=2, allow_nan=False))
    return {"passed": 0, "measured": 0, "failed": 1, "error": 2}[result["status"]]


if __name__ == "__main__":
    raise SystemExit(main())
