"""Measure saved SKY130 LVS recognition geometry without running extraction.

MOS: channel W*L plus extractor-apportioned source/drain diffusion AS+AD.
R/C: extractor A (preserved by series/parallel combination).
BJT: C/B/E recognition regions, unioned within each physical abstract and
summed over primary and combined abstracts. Substrate is excluded.

This is an electrical recognition-area sum, not manufacturing-mask union,
cell bounding boxes, or a complete PCell footprint. Different devices may
overlap. Source m/nf are never applied again to extracted geometry.

Semantics reviewed against KLayout v0.30.12 dbNetlistDeviceExtractorClasses.cc
and dbNetlistDeviceClasses.cc. Only the reviewed SKY130 decks are supported.
The optional same-net purge does not relax original-source area coverage.
"""

from __future__ import annotations

from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

from .area_v2 import reference_area
from .lvs_policy import (
    DUMMY_PURGE_DECK_SHA256, ORIGINAL_DECK_SHA256,
    is_qualified_deck_sha256, validate_dummy_flags,
)


AREA_VERSION = "extracted-device-area-v1"
# Retain the original public constant for existing evidence consumers.
SKY130_DECK_SHA256 = ORIGINAL_DECK_SHA256
AREA_DEFINITION = "sum_of_extracted_electrical_device_recognition_regions"
_MIM_ALIASES = {
    "sky130_fd_pr__cap_mim_m3_1": "sky130_fd_pr__model__cap_mim",
    "sky130_fd_pr__cap_mim_m3_2": "sky130_fd_pr__model__cap_mim_m4",
}


class ExtractedAreaError(ValueError):
    """Saved evidence is insufficient or inconsistent; no partial area is valid."""


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _require(condition, message):
    if not condition:
        raise ExtractedAreaError(message)


def _positive(value, label, *, zero=False):
    _require(math.isfinite(value) and (value >= 0 if zero else value > 0),
             f"Invalid {label}: {value}")
    return value


def _canonical_model(model, width_um=None):
    name = model.casefold()
    if name in _MIM_ALIASES:
        return _MIM_ALIASES[name]
    if name in {"sky130_fd_pr__res_high_po", "sky130_fd_pr__res_xhigh_po"}:
        _require(width_um is not None, f"Unresolved width-dependent model {model}")
        widths = {0.35: "0p35", 0.69: "0p69", 1.41: "1p41", 2.85: "2p85", 5.73: "5p73"}
        width = next((w for w in widths if math.isclose(width_um, w, abs_tol=1e-10)), None)
        _require(width is not None, f"Unsupported precision-resistor width {width_um}")
        return name + "_" + widths[width]
    return name


def _parameters(device):
    return {p.name: float(device.parameter(p.id()))
            for p in device.device_class().parameter_definitions()}


def _kind(device):
    # Exact native classes, not a guess based on a model-name prefix.
    name = type(device.device_class()).__name__
    mapping = {"DeviceClassMOS3Transistor": "MOS", "DeviceClassMOS4Transistor": "MOS",
               "DeviceClassResistor": "R", "DeviceClassResistorWithBulk": "R",
               "DeviceClassCapacitor": "C", "DeviceClassCapacitorWithBulk": "C",
               "DeviceClassBJT3Transistor": "BJT", "DeviceClassBJT4Transistor": "BJT"}
    _require(name in mapping, f"Unsupported extracted device class {name}")
    return mapping[name]


def _parameter_area(kind, parameters, length_scale):
    """Native merged parameters already include physical multiplicity."""
    area_scale = length_scale * length_scale
    required = {"MOS": ("W", "L", "AS", "AD"), "R": ("A",), "C": ("A",)}[kind]
    _require(all(p in parameters for p in required), f"Missing {kind} parameters: {required}")
    for name in required:
        _positive(parameters[name], f"{kind}.{name}", zero=name in {"AS", "AD"})
    if kind == "MOS":
        return {"channel_um2": parameters["W"] * parameters["L"] / area_scale,
                "source_diffusion_um2": parameters["AS"] / area_scale,
                "drain_diffusion_um2": parameters["AD"] / area_scale}
    return {"body_um2" if kind == "R" else "plate_overlap_um2": parameters["A"] / area_scale}


def _unit_evidence(lvsdb_path, result_path, deck_path, result):
    _require(result.get("check") == "lvs" and result.get("status") == "passed",
             "A passed saved KLayout LVS result is required")
    _require(result.get("details", {}).get("matches") is True,
             "Saved LVS result does not establish a matching circuit")
    _require(result.get("report_sha256") == _sha(lvsdb_path), "LVSdb hash differs from saved result")
    original_deck_sha256 = result.get("original_deck_sha256")
    _require(is_qualified_deck_sha256(original_deck_sha256),
             "Unreviewed extraction deck: units and device semantics must be reviewed")
    _require(result.get("effective_deck_sha256") == _sha(deck_path),
             "Effective extraction deck hash differs from saved result")
    flags = result.get("flags", {})
    _require(flags.get("scale") == "true", "Only the reviewed scale=true invocation is supported")
    command = result.get("command", [])
    if original_deck_sha256 == DUMMY_PURGE_DECK_SHA256:
        try:
            validate_dummy_flags(flags, command)
        except ValueError as error:
            raise ExtractedAreaError(f"Unreviewed dummy-purge invocation: {error}") from error
    _require([command[i + 1] for i in range(len(command) - 1)
              if command[i] == "-rd" and command[i + 1].startswith("scale=")] == ["scale=true"],
             "Saved command does not agree with scale=true")
    # Inspect the executed deck, not the post-read database.device_scaling
    # property (which resets to 1 on deserialization).
    code = "\n".join(line.split("#", 1)[0] for line in deck_path.read_text().splitlines())
    calls = re.findall(r"\bdevice_scaling\s*\(\s*([^)]*)\)", code)
    _require(calls == ["1000000"], "Unexpected device_scaling calls in executed deck")
    _require(re.search(r'if\s+\$scale\s*==\s*"true"\s+device_scaling\(1000000\)', code),
             "Cannot establish the executed device_scaling branch")
    return {"length_parameter_units_per_um": 1e6, "area_parameter_units_per_um2": 1e12,
            "scale_flag": "true", "scale_source": "saved command and executed deck branch",
            "original_deck_sha256": original_deck_sha256,
            "effective_deck_path": str(deck_path), "effective_deck_sha256": _sha(deck_path),
            "lvs_result_path": str(result_path), "lvs_result_sha256": _sha(result_path),
            "lvsdb_path": str(lvsdb_path), "lvsdb_sha256": _sha(lvsdb_path)}


def _abstract_terminal_regions(database, abstract, device_class):
    """Query native clusters through public Net/Circuit/LayoutToNetlist APIs.

    A temporary net is a query handle for a saved cell-index/cluster-id pair;
    it is never inserted into or used to alter the saved database netlist.
    Layer numbers are enumerated, never interpreted as terminal identities.
    """
    import klayout.db as kdb

    query_netlist = kdb.Netlist()
    circuit = kdb.Circuit()
    circuit.name = "abstract_query"
    circuit.cell_index = abstract.cell_index()
    query_netlist.add(circuit)
    terms = {term.name: term.id() for term in device_class.terminal_definitions()}
    _require({"C", "B", "E"} <= terms.keys(), "BJT class lacks C/B/E terminal definitions")
    regions, layers = {}, {}
    for name in ("C", "B", "E"):
        cluster = abstract.cluster_id_for_terminal(terms[name])
        _require(cluster > 0, f"BJT abstract has no {name} terminal cluster")
        net = circuit.create_net(name)
        net.cluster_id = cluster
        region, terminal_layers = kdb.Region(), []
        for index in database.layer_indexes():
            part = database.shapes_of_net(net, database.layer_by_index(index), False)
            if not part.is_empty():
                region += part
                terminal_layers.append({"index": index, "name": database.layer_name(index)})
        region.merge()
        _require(not region.is_empty(), f"Empty BJT {name} recognition region")
        regions[name], layers[name] = region, terminal_layers
    return regions, layers


def _bjt_area(database, device, cache):
    import klayout.db as kdb

    primary = device.device_abstract
    _require(primary is not None, "BJT is missing its primary physical abstract")
    abstracts = [(primary, device.trans, "primary")]
    abstracts += [(ref.device_abstract, device.trans * ref.trans, "combined")
                  for ref in device.each_combined_abstract()]
    rows = []
    dbu = database.internal_layout().dbu
    for index, (abstract, transform, origin) in enumerate(abstracts):
        _require(abstract is not None, "BJT combined physical abstract is missing")
        key = (abstract.cell_index(), tuple((t.id(), abstract.cluster_id_for_terminal(t.id()))
                                           for t in device.device_class().terminal_definitions()))
        if key not in cache:
            regions, layers = _abstract_terminal_regions(database, abstract, device.device_class())
            union = kdb.Region()
            for region in regions.values():
                union += region
            cache[key] = {"area_um2": union.merged().area() * dbu * dbu,
                          "terminal_area_um2": {n: r.area() * dbu * dbu for n, r in regions.items()},
                          "terminal_layers": layers}
        local = cache[key]
        mag2 = transform.mag ** 2
        rows.append({"index": index, "origin": origin, "abstract_cell_index": abstract.cell_index(),
                     "transform": str(transform), "area_um2": local["area_um2"] * mag2,
                     "terminal_area_um2": {n: a * mag2 for n, a in local["terminal_area_um2"].items()},
                     "terminal_layers": local["terminal_layers"]})
    return math.fsum(row["area_um2"] for row in rows), rows


def _walk(circuit, prefix="", ancestors=(), mag2=1.0, device_map=None):
    _require(circuit.name not in ancestors, "Recursive extracted circuit hierarchy")
    devices = device_map[circuit.name] if device_map is not None else circuit.each_device()
    for ordinal, device in enumerate(devices):
        yield prefix, ordinal, device, mag2
    for ordinal, sub in enumerate(circuit.each_subcircuit()):
        yield from _walk(sub.circuit_ref(), prefix + (sub.name or str(ordinal)) + "/",
                         ancestors + (circuit.name,), mag2 * sub.trans.mag ** 2, device_map)


def _source_inventory(rows):
    totals = defaultdict(float)
    for row in rows:
        model = _canonical_model(row["model"], row["w_um"])
        # Count BJT emitters; model geometry determines each emitter size.
        value = row["m"] if row["kind"] == "BJT" else row["effective_area_um2"]
        totals[(row["kind"], model)] += value
    return totals


def _schematic_inventory(circuit, scale):
    totals = defaultdict(float)
    for _, _, device, mag2 in _walk(circuit):
        kind, p = _kind(device), _parameters(device)
        model = _canonical_model(device.device_class().name, p.get("W", 0) / scale)
        if kind == "BJT":
            value = p["NE"]
        elif kind == "C":
            value = p["A"] / scale ** 2
        else:
            width_um = p["W"] / scale
            if kind == "R" and width_um == 0:
                # Fixed-width SKY130 resistor primitives encode W in the model
                # name; their schematic DeviceClass W parameter stays zero.
                match = re.fullmatch(r"sky130_fd_pr__res_(?:x?high)_po_(0p35|0p69|1p41|2p85|5p73)", model)
                _require(match is not None, f"Missing schematic width for {model}")
                width_um = float(match[1].replace("p", "."))
            value = width_um * p["L"] / scale
        totals[(kind, model)] += value * mag2
    return totals


def extract_device_area(lvsdb_path: Path, *, top: str, lvs_result_path: Path,
                        source_netlist_path: Path | None = None,
                        deck_path: Path | None = None) -> dict:
    """Read existing evidence and return a complete, auditable device-area sum.

    Raises ExtractedAreaError for unsupported or incomplete evidence. It never
    returns a partial result with status=complete and never runs an EDA tool.
    """
    import klayout.db as kdb

    lvsdb_path, result_path = Path(lvsdb_path), Path(lvs_result_path)
    deck_path = Path(deck_path) if deck_path else result_path.parent / "run.lvs"
    result = json.loads(result_path.read_text())
    unit = _unit_evidence(lvsdb_path, result_path, deck_path, result)
    _require(result.get("top", "").casefold() == top.casefold(), "Saved result top differs")
    reference_path = result_path.parent / "reference.spice"
    _require(_sha(reference_path) == result.get("reference_sha256"), "Compared reference hash differs")
    if source_netlist_path is None:
        candidates = [result_path.parent / name for name in
                      ("reference.original.spice", "reference.before-resistor.spice",
                       "reference.before-mim.spice", "reference.before-bjt.spice", "reference.spice")]
        source_netlist_path = next(p for p in candidates if p.is_file())
    source_netlist_path = Path(source_netlist_path)
    source_sha = _sha(source_netlist_path)
    expected_source_sha = result.get("original_reference_sha256", result.get("reference_sha256"))
    archived_sources = [p for p in result_path.parent.glob("reference*.spice")
                        if _sha(p) == source_sha]
    _require(source_sha == expected_source_sha or archived_sources,
             "Source netlist does not match an archived LVS reference view")
    source = reference_area(source_netlist_path.read_text(), top)
    source_rows = source["effective_area_devices"]

    database = kdb.LayoutVsSchematic()
    database.read(str(lvsdb_path))
    _require(not any(e.severity == kdb.LogEntryData.Error or e.category_name == "must-connect"
                     for e in database.each_log_entry()), "LVSdb contains extraction errors")
    xref = database.xref()
    _require(xref is not None, "LVSdb has no comparison cross-reference")
    circuit_pairs = list(xref.each_circuit_pair())
    _require(circuit_pairs and all(p.first() and p.second() and str(p.status()) == "Match"
                                  for p in circuit_pairs), "LVS cross-reference has unmatched circuits")
    top_pairs = [p for p in circuit_pairs if p.first().name.casefold() == top.casefold()
                 and p.second().name.casefold() == top.casefold()]
    _require(len(top_pairs) == 1, "LVS cross-reference lacks an unambiguous top")
    pair_map, device_map = {}, {}
    for pair in circuit_pairs:
        pairs = list(xref.each_device_pair(pair))
        _require(all(p.first() and p.second() and str(p.status()) == "Match" for p in pairs),
                 "LVS cross-reference has unmatched/ignored devices")
        layout_devices = list(pair.first().each_device())
        schematic_devices = list(pair.second().each_device())
        _require(len(pairs) == len(layout_devices) == len(schematic_devices),
                 "LVS cross-reference does not cover every compared device")
        pair_map[pair.first().name] = {p.first().id(): p.second() for p in pairs}
        # The const Circuit.each_device binding returns copies with id=0 and
        # no circuit owner. Xref DevicePair.first() is the native identified
        # device and retains its physical abstract and owner.
        device_map[pair.first().name] = [p.first() for p in pairs]
        _require(len(pair_map[pair.first().name]) == len(pairs), "Nonunique LVS device IDs")

    scale = unit["length_parameter_units_per_um"]
    expected, represented = _source_inventory(source_rows), _schematic_inventory(top_pairs[0].second(), scale)
    # B can remove source-declared devices as well as layout-only additions.
    # A matching reduced circuit therefore does not, on its own, establish a
    # complete area numerator. Keep the full source invariant and fail closed.
    coverage_note = ("; same-net purging is not an exemption from full original-source area coverage"
                     if result["original_deck_sha256"] == DUMMY_PURGE_DECK_SHA256 else "")
    _require(expected.keys() == represented.keys(),
             "Original source device models are missing from LVS" + coverage_note)
    inventory = []
    for key, value in sorted(expected.items()):
        actual = represented[key]
        _require(math.isclose(value, actual, rel_tol=1e-9, abs_tol=1e-8),
                 f"Original source coverage mismatch {key}: source={value}, LVS schematic={actual}"
                 + coverage_note)
        inventory.append({"kind": key[0], "model": key[1], "source_value": value,
                          "compared_schematic_value": actual,
                          "invariant": "emitter_count" if key[0] == "BJT" else "core_area_um2"})

    rows, cache = [], {}
    allowed = set(expected)
    for path, ordinal, device, hierarchy_mag2 in _walk(top_pairs[0].first(), device_map=device_map):
        kind, params = _kind(device), _parameters(device)
        model = _canonical_model(device.device_class().name, params.get("W", 0) / scale)
        _require((kind, model) in allowed, f"Extracted device absent from original source: {model}")
        _require(device.device_abstract is not None, "Extracted device is missing physical geometry")
        count = 1 + sum(1 for _ in device.each_combined_abstract())
        reference_device = pair_map[device.circuit().name][device.id()]
        row = {"circuit_path": path, "circuit": device.circuit().name,
               "ordinal": ordinal, "layout_device_id": device.id(),
               "reference_device_id": reference_device.id(), "reference_instance": reference_device.name,
               "kind": kind, "model": model, "device_class": type(device.device_class()).__name__,
               "parameters_stored": params, "physical_abstract_count": count,
               "hierarchy_area_factor": hierarchy_mag2,
               "origin": "saved_klayout_lvsdb"}
        if kind == "BJT":
            area, physical = _bjt_area(database, device, cache)
            row.update(area_basis="per_physical_abstract_union_C_B_E_excluding_substrate",
                       physical_abstracts=physical, area_components_um2={"recognition_union_um2": area})
            # One abstract is one extractor-created emitter, including combined
            # abstracts; NE is independently accumulated by the native combiner.
            _require(math.isclose(params["NE"], count, abs_tol=1e-9), "BJT NE/abstract count differs")
        else:
            components = _parameter_area(kind, params, scale)
            area = math.fsum(components.values())
            row.update(area_basis="W*L+AS+AD" if kind == "MOS" else "native_A",
                       area_components_um2=components)
        row["area_um2"] = _positive(area * hierarchy_mag2, "extracted device area")
        rows.append(row)
    _require(rows, "No reachable extracted devices")
    totals = {kind: math.fsum(r["area_um2"] for r in rows if r["kind"] == kind)
              for kind in ("MOS", "R", "C", "BJT")}
    public_kinds = {"MOS": "mos", "R": "resistor", "C": "capacitor", "BJT": "bjt"}
    return {"status": "complete", "name": AREA_VERSION, "area_version": AREA_VERSION,
            "area_definition": AREA_DEFINITION, "area_um2": math.fsum(totals.values()),
            "kind_totals_um2": {public_kinds[k]: v for k, v in totals.items()}, "device_rows": rows,
            "coverage": {"status": "complete", "source_netlist_sha256": source_sha,
                         "matching_archived_reference_paths": [str(p) for p in archived_sources],
                         "source_device_rows": len(source_rows),
                         "source_kind_counts": dict(Counter(r["kind"] for r in source_rows)),
                         "logical_device_count": len(rows),
                         "logical_kind_counts": dict(Counter(r["kind"] for r in rows)),
                         "physical_abstract_count": sum(r["physical_abstract_count"] for r in rows),
                         "physical_kind_counts": {k: sum(r["physical_abstract_count"] for r in rows
                                                         if r["kind"] == k) for k in totals},
                         "matched_source_inventory": inventory,
                         "method": "all_native_xref_devices_plus_original_source_model_area_invariants"},
            "unit_evidence": dict(unit, internal_layout_dbu_um=database.internal_layout().dbu),
            "limitations": ["Electrical recognition area, not complete manufacturing footprint.",
                            "Areas of different physical devices may overlap; no cross-device union."]}
