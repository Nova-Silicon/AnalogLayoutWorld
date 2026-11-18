"""Read physical area terms from an existing, qualified Magic LVS extraction.

No extraction or simulation is performed.  This deliberately supports the
flat ``ext2spice scale off / merge none`` format used by our trusted verifier:
one native MOS, MIM or poly-resistor statement per physical extracted device.
It does not interpret user SPICE, infer undocumented units, or apply source m.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re

VERSION = "gds-native-device-area-v1"
_MOS = frozenset({
    "sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8",
    "sky130_fd_pr__nfet_01v8_lvt", "sky130_fd_pr__pfet_01v8_lvt",
    "sky130_fd_pr__nfet_05v0_nvt",
})
_MIM = frozenset({"sky130_fd_pr__cap_mim_m3_1", "sky130_fd_pr__cap_mim_m3_2"})
_RES = frozenset({"sky130_fd_pr__res_generic_po"})
_MODELS = _MOS | _MIM | _RES
_NUMBER = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:e[+-]?\d+)?)([a-z]*)", re.I)
_SCALE = {"": 1., "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
          "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_REQUIRED_COMMANDS = (
    "extract style {ngspice()}", "ext2spice lvs", "ext2spice format ngspice",
    "ext2spice scale off", "ext2spice merge none", "ext2spice hierarchy off",
    "ext2spice subcircuit top on", "ext2spice short none", "ext2spice extresist off",
    "ext2spice rthresh infinite", "ext2spice cthresh infinite",
)


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _object(path):
    value = json.loads(Path(path).read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Expected an object: {path}")
    return value


def _lines(text):
    current, number = "", 0
    for n, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if not current:
                raise ValueError(f"Orphan continuation at line {n}")
            current += " " + line[1:].strip()
        else:
            if current:
                yield number, current
            current, number = line, n
    if current:
        yield number, current


def _number(text, label, *, zero=False):
    match = _NUMBER.fullmatch(text)
    if match is None or match[2].casefold() not in _SCALE:
        raise ValueError(f"Unsupported native numeric value for {label}: {text!r}")
    # Scale-off output is already in micrometres / square micrometres.
    # SPICE engineering suffixes abbreviate that value, e.g. L=5.68465k is
    # 5684.65 um, not 5.68465 kilometres and not an SI-to-um conversion.
    value = float(match[1]) * _SCALE[match[2].casefold()]
    if not math.isfinite(value) or value < 0 or (not zero and value == 0):
        raise ValueError(f"Invalid native value for {label}: {text!r}")
    return value


def _qualify_script(path):
    lines = [" ".join(s.strip().split()) for s in Path(path).read_text().splitlines()
             if s.strip() and not s.lstrip().startswith("#")]
    for required in _REQUIRED_COMMANDS:
        prefix = required.rsplit(" ", 1)[0] + " "
        matching = [s for s in lines if s == required] if len(required.split()) == 2 else [
            s for s in lines if s.startswith(prefix)]
        if matching != [required]:
            raise ValueError(f"Magic extraction configuration is not qualified: {required}")
    outputs = [s for s in lines if s.startswith("ext2spice -o ")]
    if (len(outputs) != 1 or len(outputs[0].split()) != 4
            or outputs[0].split()[2] != "extracted.spice"):
        raise ValueError("Magic extraction has no unique native extracted.spice output")


def measure_extracted_area(extracted_path, *, extraction_script,
                           expected_top=None, allowed_models=None):
    """Return complete native area terms or fail rather than skip a device.

    MOS: W*L + AS + AD; MIM: W*L dielectric plate; qualified poly resistor:
    W*L resistive body.  Each physical statement contributes once.  External
    callers must authenticate this evidence against the selected GDS result;
    ``extract_from_result`` provides that archived-verifier binding.
    """
    extracted_path, extraction_script = Path(extracted_path), Path(extraction_script)
    _qualify_script(extraction_script)
    text = extracted_path.read_text()
    if not text.startswith("* NGSPICE file created from ") or "technology: sky130A" not in text.splitlines()[0]:
        raise ValueError("Not a native SKY130 Magic extraction")
    allowed = {s.casefold() for s in allowed_models} if allowed_models is not None else None
    rows, names, top, ports, ended = [], set(), None, None, False
    for number, line in _lines(text):
        tokens = line.split()
        head = tokens[0].casefold()
        if head == ".subckt":
            if top is not None or len(tokens) < 3 or any("=" in x for x in tokens):
                raise ValueError("Magic area requires exactly one flat nonparameterized top")
            top, ports = tokens[1], tokens[2:]
            if expected_top is not None and top.casefold() != expected_top.casefold():
                raise ValueError("Extracted top differs from its trusted verifier record")
            continue
        if head == ".ends":
            if (top is None or ended or len(tokens) > 2
                    or (len(tokens) > 1 and tokens[1].casefold() != top.casefold())):
                raise ValueError("Malformed extracted top terminator")
            ended = True
            continue
        if top is None or ended or head.startswith(".") or not head.startswith("x"):
            raise ValueError(f"Unsupported native statement at line {number}: {head}")
        if head in names:
            raise ValueError(f"Duplicate extracted device: {tokens[0]}")
        names.add(head)
        cut = next((i for i, token in enumerate(tokens) if "=" in token), len(tokens))
        if cut < 4:
            raise ValueError(f"Missing native model/terminals: line {number}")
        model, nodes = tokens[cut - 1].casefold(), tokens[1:cut - 1]
        if model not in _MODELS or (allowed is not None and model not in allowed):
            raise ValueError(f"Unsupported/unapproved native model: {model}")
        params = {}
        for token in tokens[cut:]:
            if token.count("=") != 1:
                raise ValueError(f"Unsupported native parameter syntax: {token}")
            key, value = token.split("=")
            key = key.casefold()
            if key in params:
                raise ValueError(f"Duplicate native parameter: {key}")
            params[key] = value
        kind = "MOS" if model in _MOS else "C" if model in _MIM else "R"
        required = {"w", "l", "as", "ad"} if kind == "MOS" else {"w", "l"}
        permitted = required | ({"ps", "pd"} if kind == "MOS" else set())
        if set(params) - permitted or not required <= set(params):
            raise ValueError(f"Incomplete or unqualified {kind} geometry parameters: {tokens[0]}")
        if len(nodes) != (4 if kind == "MOS" else 2):
            raise ValueError(f"Unexpected {kind} terminal count: {tokens[0]}")
        native = {key: _number(value, f"{tokens[0]}.{key}", zero=key in {"as", "ad", "ps", "pd"})
                  for key, value in params.items()}
        terms = {"channel_um2": native["w"] * native["l"],
                 "source_um2": native["as"], "drain_um2": native["ad"]} if kind == "MOS" else {
                     "plate_um2" if kind == "C" else "body_um2": native["w"] * native["l"]}
        area = math.fsum(terms.values())
        if not math.isfinite(area) or area <= 0:
            raise ValueError("Native device area is not finite and positive")
        rows.append({"instance": tokens[0], "source_line": number, "model": model,
                     "kind": kind, "native_parameters": native, "area_terms_um2": terms,
                     "area_um2": area, "counted_once": True})
    if top is None or not ended or not rows:
        raise ValueError("Incomplete or empty extracted top")
    models = Counter(row["model"] for row in rows)
    totals = {name: math.fsum(row["area_um2"] for row in rows if row["kind"] == kind)
              for name, kind in (("mos", "MOS"), ("resistor", "R"),
                                 ("capacitor", "C"), ("bjt", "BJT"))}
    area = math.fsum(totals.values())
    return {"schema": "alb-magic-extracted-device-area-v1", "status": "complete",
            "reference_area_version": VERSION, "device_area_um2": area, "area_um2": area,
            "kind_totals_um2": totals, "device_rows": rows, "top": top, "ports": ports,
            "models": dict(models), "coverage": {"complete": True, "physical_devices": len(rows),
                "devices_accounted": len(rows), "unsupported_devices": 0, "missing_parameters": 0},
            "unit_evidence": {"backend": "magic_ngspice_ext2spice", "scale": "off",
                "merge": "none", "hierarchy": "off", "length_unit": "um", "area_unit": "um2",
                "multiplicity": "one contribution per physical native statement; no extra m/nf multiplier",
                "engineering_suffixes": "standard SPICE multiplier of already-native um/um2 value"},
            "evidence": {"extracted_path": str(extracted_path), "extracted_sha256": _sha(extracted_path),
                "extraction_script_path": str(extraction_script), "extraction_script_sha256": _sha(extraction_script)}}


def extract_from_result(lvs_result_path, *, top, source_netlist_path):
    """Bind native fields to a successful, already saved Magic/Netgen result."""
    path, source = Path(lvs_result_path), Path(source_netlist_path)
    result = _object(path)
    extraction, execution, details = (result.get(k) or {} for k in ("extraction", "magic_execution", "details"))
    netgen = result.get("netgen_execution") or {}
    native = result.get("extracted_netlist") or {}
    if (result.get("check") != "lvs" or result.get("status") != "passed"
            or result.get("backend") != "magic_netgen"
            or result.get("top", "").casefold() != top.casefold()
            or result.get("reference_sha256") != _sha(source)
            or extraction.get("style") != "ngspice()" or extraction.get("merge") != "none"
            or extraction.get("geometry") != "flattened GDS without properties"
            or execution.get("status") != "completed" or execution.get("returncode") != 0
            or netgen.get("status") != "completed" or netgen.get("returncode") != 0
            or details.get("matches") is not True or details.get("top_ports_match") is not True
            or details.get("final_unique_match") is not True or details.get("comparison_errors")
            or not native.get("top") or native.get("subcircuits") != [native.get("top")]):
        raise ValueError("Magic area evidence is not bound to a complete trusted LVS match")
    command = result.get("magic_command") or []
    if not command or Path(command[-1]).name != "extract.tcl":
        raise ValueError("Unexpected archived Magic script command")
    directory = path.parent / "magic"
    script, extracted, log = directory / "extract.tcl", directory / "extracted.spice", directory / "command.log"
    if "ALB_LVS_EXTRACTION_COMPLETE" not in log.read_text() or "ALB_LVS_EXTRACTION_ERROR" in log.read_text():
        raise ValueError("Native extraction did not report complete execution")
    if _sha(path.parent / "input.gds") != result.get("input_sha256"):
        raise ValueError("Magic extraction source GDS differs from its verifier result")
    if (path.parent / "extracted.spice").is_file() and _sha(extracted) != _sha(path.parent / "extracted.spice"):
        raise ValueError("Archived Magic and public LVS netlist copies differ")
    allowed = native.get("reachable_models")
    value = measure_extracted_area(extracted, extraction_script=script,
                                   expected_top=native["top"], allowed_models=allowed)
    if (value["models"] != native.get("models") or value["ports"] != native.get("ports")
            or Counter(value["ports"]) != Counter((result.get("contract") or {}).get("ports", []))):
        raise ValueError("Native area rows/ports do not cover the trusted extracted netlist")
    value["evidence"].update(lvs_result_path=str(path), lvs_result_sha256=_sha(path),
        source_netlist_path=str(source), source_netlist_sha256=_sha(source),
        gds_sha256=result["input_sha256"], extracted_top=native["top"], source_top=top)
    return value
