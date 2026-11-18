"""Collect engineering facts independently of scoring weights and gates."""
from __future__ import annotations

import hashlib
import json
import math
from numbers import Real
from pathlib import Path
import time

VERSION = "layout-engineering-facts-v3"
PACKAGE = Path(__file__).resolve().parent
SOURCE = "AnalogLayoutWorld engineering quality verifier"
MAGIC_POLICY_ID = "magic-netgen-quality-v1"
MAGIC_POLICY_TASKS = frozenset({
    "sky130-adb-buf-ppsf-bs-gain1-sfdr90-layout",
    "sky130-adb-fct-residue-amplifier-900msps-layout",
})


class EvidenceError(ValueError):
    """The frozen inputs do not establish the claimed layout identity."""


class GeometryUnavailable(ValueError):
    """Valid evidence lacks a qualified geometry cross-reference adapter."""


def _sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _read_object(path):
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise EvidenceError(f"Expected a JSON object: {Path(path).name}")
    return value


def _datum(status, value=None, reason=None, **extra):
    result = {"status": status, "value": value, **extra}
    if reason:
        result["reason"] = reason
    return result


def _measured(value, **extra):
    # Physical measurements may be NumPy real scalars. Accept the real-number
    # interface, while keeping booleans, strings, arrays and complex values out.
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError("Quality measurement must be finite and in [0,1]")
    try:
        normalized = float(value)
    except (OverflowError, TypeError, ValueError):
        raise ValueError("Quality measurement must be finite and in [0,1]") from None
    if not math.isfinite(normalized) or not 0 <= value <= 1:
        raise ValueError("Quality measurement must be finite and in [0,1]")
    return _datum("measured", normalized, **extra)


def _clean(value):
    if isinstance(value, dict):
        return {str(k): _clean(v) for k, v in value.items() if not str(k).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        return _clean(value.item())
    if isinstance(value, float) and not math.isfinite(value):
        return None
    return value


def _write(out_dir, result):
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    target = out / "result.json"
    temporary = out / "result.json.new"
    temporary.write_text(json.dumps(_clean(result), ensure_ascii=False,
                                    indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(target)
    return _clean(result)


def _tool_hash():
    h = hashlib.sha256()
    for path in sorted(PACKAGE.glob("*.py")):
        h.update(path.name.encode() + b"\0" + path.read_bytes() + b"\0")
    return h.hexdigest()


def _magic_policy(name, lvs, task):
    """Apply the fixed quality credit for the two Magic/Netgen tasks."""
    constraints = _read_object(task / "constraints.json")
    if (name not in MAGIC_POLICY_TASKS or lvs.get("backend") != "magic_netgen"
            or constraints.get("lvs_backend") != "magic_netgen"):
        return None
    reason = ("This task receives the fixed Magic/Netgen quality credit because the backend "
              "does not measure device/net cross-reference geometry. The area and aspect-ratio "
              "criteria and all other verification stages still apply.")
    return {"status": "policy_credit",
            "policy_credit": {"id": MAGIC_POLICY_ID, "task_name": name, "backend": "magic_netgen"},
            "reason": reason,
            "subscores": {k: _datum("policy_credit", 1.0, reason=reason)
                          for k in ("matching", "critical", "power")},
            "raw_subscores": {k: None for k in ("matching", "critical", "power")},
            "coupling_penalty": _datum("policy_credit", 0.0, reason=reason),
            "meaningless": _datum("not_applicable_backend", reason=reason),
            "coverage": {"status": "policy_credit", "geometry_measured": False,
                         "expected_components": 5, "completed_components": 0, "fraction": 0.0}}


def _task_name(task_path, explicit):
    if explicit is not None:
        name = explicit
    elif task_path.parent.name == "tests":
        name = task_path.parent.parent.name
    else:
        raise ValueError("task_name is required for a frozen task directory")
    if not isinstance(name, str) or not name.startswith("sky130-") or Path(name).name != name:
        raise ValueError("Invalid trusted task_name")
    return name


def _bind_inputs(gds, result_path, task_path, annotation_path):
    lvs = _read_object(result_path)
    if lvs.get("check") != "lvs" or lvs.get("status") != "passed" or lvs.get("details", {}).get("matches") is not True:
        raise EvidenceError("A completed passed LVS result is required")
    if _sha(gds) != lvs.get("input_sha256"):
        raise EvidenceError("GDS differs from the passed LVS input")
    files = {"gds": gds, "lvs_result": result_path,
             "source_netlist": task_path / "circuit.spice",
             "constraints": task_path / "constraints.json", "annotation": annotation_path,
             "reference": result_path.parent / "reference.spice"}
    if _sha(files["constraints"]) != lvs.get("constraints_sha256"):
        raise EvidenceError("Task constraints differ from the passed LVS inputs")
    if _sha(files["reference"]) != lvs.get("reference_sha256"):
        raise EvidenceError("Compared reference differs from the passed LVS inputs")
    if lvs.get("backend", "klayout") == "klayout":
        files["lvsdb"] = result_path.parent / "report.lvsdb"
        if _sha(files["lvsdb"]) != lvs.get("report_sha256"):
            raise EvidenceError("LVS database differs from the passed LVS report")
        for name in ("run.lvs", "reference-name-map.json", "reference-mim-map.json"):
            path = result_path.parent / name
            if path.exists():
                files[name] = path
    return lvs, files, {name: _sha(path) for name, path in files.items()}


def _validate_annotation(annotation, task_name):
    if annotation.get("task") != task_name:
        raise EvidenceError("Quality annotation belongs to another task")
    groups = annotation.get("matched_groups", [])
    if not isinstance(groups, list):
        raise ValueError("matched_groups must be a list")
    for group in groups:
        if not isinstance(group, dict) or not isinstance(group.get("devices"), list) or len(group["devices"]) < 2:
            raise ValueError("Every matching annotation requires at least two device names")
        weight = group.get("weight", 1)
        if type(weight) not in (int, float) or not math.isfinite(weight) or weight <= 0:
            raise ValueError("Matching-group weight must be positive and finite")
    nets = annotation.get("nets", {})
    if not isinstance(nets, dict):
        raise ValueError("nets must be an object")
    for key, values in nets.items():
        if not isinstance(values, list):
            raise ValueError(f"nets.{key} must be a list")
        for value in values:
            names = value if key == "diff_pairs" else [value]
            if not isinstance(names, list) or (key == "diff_pairs" and len(names) != 2) or not all(isinstance(n, str) and n for n in names):
                raise ValueError(f"Invalid names in nets.{key}")


def _preflight_names(model, annotation):
    issues = {key: [] for key in ("matching", "critical", "coupling", "power")}
    for group in annotation.get("matched_groups", []):
        _, problems = model.resolve_group(group["devices"])
        issues["matching"].extend(p for p in problems if ": note: " not in p)
    nets = annotation.get("nets", {})
    for category, fields in (("critical", ("critical", "diff_pairs")),
                             ("coupling", ("aggressors", "victims")),
                             ("power", ("power", "ground"))):
        for field in fields:
            values = nets.get(field) or []
            names = [n for pair in values for n in pair] if field == "diff_pairs" else values
            for name in names:
                key, how = model.resolve_net(name)
                if key is None:
                    issues[category].append(f"{name}: {how}")
    for name in annotation.get("power_devices", []):
        devices, how = model.resolve_device(name)
        if len(devices) != 1:
            issues["power"].append(f"{name}: {how}; expected one mapped logical device")
    return issues


def _summarize_measurements(model, annotation, *, matching_fn, coupling_fn, power_fn):
    """Keep failed expected items out of neither numerator nor denominator."""
    issues = _preflight_names(model, annotation)
    nets = annotation.get("nets", {})
    applicable = {"matching": bool(annotation.get("matched_groups")),
                  "critical": bool(nets.get("critical") or nets.get("diff_pairs")),
                  "power": bool(nets.get("power") or nets.get("ground") or annotation.get("power_devices")),
                  "coupling": bool(nets.get("aggressors") and nets.get("victims"))}
    raw = {}
    sub = {}
    for name, fn in (("matching", matching_fn), ("critical", coupling_fn), ("power", power_fn)):
        if not applicable[name]:
            sub[name] = _datum("not_applicable", reason="No requirement annotated for this task")
            continue
        if issues[name]:
            sub[name] = _datum("error", reason="; ".join(issues[name]))
            continue
        try:
            result = raw["coupling" if name == "critical" else name] = fn(model, annotation)
            if name == "critical":
                scores = []
                for key, required in (("routing", bool(nets.get("critical"))),
                                      ("diff_pairs", bool(nets.get("diff_pairs")))):
                    if required:
                        part = result.get(key, {})
                        if part.get("status") != "measured" or part.get("score") is None:
                            raise ValueError(f"Required {key} could not be measured")
                        rows = part.get("nets", part.get("pairs", []))
                        if any(row.get("score") is None for row in rows):
                            raise ValueError(f"Required {key} has unmeasured members")
                        scores.append(part["score"])
                sub[name] = _measured(sum(scores) / len(scores))
            else:
                if result.get("status") != "measured":
                    raise ValueError(result.get("reason", "Required measurement unavailable"))
                if name == "matching" and any(g.get("status") != "measured" for g in result.get("groups", [])):
                    raise ValueError("At least one required matching group was not measured")
                if name == "power" and result.get("problems"):
                    raise ValueError("; ".join(result["problems"]))
                if name == "power":
                    rows = result.get("conventions", {}).values()
                    if any(row.get("score") is None for row in rows):
                        raise ValueError("At least one required supply geometry was not measured")
                    currents = annotation.get("currents_a") or {}
                    rails = [str(n).lower() for key in ("power", "ground") for n in nets.get(key, [])]
                    current_map = {str(k).lower(): v for k, v in currents.items()}
                    significant = bool(annotation.get("power_devices")) or any(
                        (current_map.get(n) or 0) >= 1e-3 for n in rails)
                    if significant and result.get("subscores", {}).get("current") is None:
                        raise ValueError("Required significant-current measurement unavailable; conventions alone cannot replace it")
                sub[name] = _measured(result.get("score"))
        except Exception as error:
            sub[name] = _datum("error", reason=f"{type(error).__name__}: {error}")
    if not applicable["coupling"]:
        penalty = _datum("not_applicable", reason="No aggressor/victim pair annotated")
    elif issues["coupling"]:
        penalty = _datum("error", reason="; ".join(issues["coupling"]))
    else:
        try:
            c = raw.get("coupling")
            if c is None:
                c = raw["coupling"] = coupling_fn(model, annotation)
            result = c.get("coupling", {})
            if result.get("status") != "measured":
                raise ValueError("Required coupling estimate unavailable")
            penalty = _measured(result.get("penalty"), source="geometric_estimate")
        except Exception as error:
            penalty = _datum("error", reason=f"{type(error).__name__}: {error}")
    return sub, penalty, raw


def collect(gds_path, lvs_result_path, task_path, out_dir, *, task_name=None, area_report=None):
    """Read authenticated existing evidence and write ``out_dir/result.json``.

    The two designated Magic/Netgen tasks receive labeled policy
    credit. Other missing geometry stays incomplete rather than being waived.
    """
    started = time.monotonic()
    result = {"schema_version": 1, "version": VERSION, "status": "error",
              "subscores": {k: _datum("missing", reason="Collection not completed")
                            for k in ("matching", "critical", "power")},
              "coupling_penalty": _datum("missing", reason="Collection not completed"),
              "meaningless": _datum("missing", reason="Morphology not measured"),
              "limitations": ["Engineering proxy measurements, not manufacturing signoff.",
                              "Coupling uses a GDS-bound geometric estimate, not a named PEX matrix."],
              "source": SOURCE, "integrity_error": False}
    files, hashes = {}, {}
    try:
        gds, lp, task = Path(gds_path), Path(lvs_result_path), Path(task_path)
        name = _task_name(task, task_name)
        annotation_path = PACKAGE / "annotations" / f"{name}.json"
        annotation = _read_object(annotation_path)
        _validate_annotation(annotation, name)
        lvs, files, hashes = _bind_inputs(gds, lp, task, annotation_path)
        result["task"] = name
        result["provenance"] = {"inputs": hashes, "tool_sha256": _tool_hash(), "version": VERSION,
                                "backend": lvs.get("backend", "klayout")}
        if lvs.get("backend", "klayout") != "klayout":
            credit = _magic_policy(name, lvs, task)
            if credit is None:
                raise GeometryUnavailable("Passed backend has no qualified device/net geometry cross-reference")
            result.update(credit)
        else:
            # Reuse the original-source coverage and native-unit qualification.
            # This validates evidence only: it performs no extraction or simulation.
            from ..area_extracted import extract_device_area
            qualification = extract_device_area(files["lvsdb"], top=lvs["top"], lvs_result_path=lp,
                                                source_netlist_path=task / "circuit.spice")
            result["source_coverage"] = qualification["coverage"]
            from .model import GeometryModel
            from .matching import score_matching
            from .coupling import score_coupling
            from .power import score_power
            from .meaningless import features, judge
            model = GeometryModel(gds, files["lvsdb"], task, name, lvs.get("geometry") or {}).load()
            sub, penalty, details = _summarize_measurements(model, annotation, matching_fn=score_matching,
                                                          coupling_fn=score_coupling, power_fn=score_power)
            result.update(subscores=sub, raw_subscores={k: v["value"] for k, v in sub.items()},
                          coupling_penalty=penalty, measurements=details, layout=model.summary())
            try:
                facts = features(model, None, annotation, details.get("matching"))
                facts.pop("fill_ratio", None)
                raw_u = (area_report or {}).get("raw_area_utilization", (area_report or {}).get("area_utilization"))
                facts["raw_effective_area_ratio"] = raw_u
                verdict = judge(facts)
                result["meaningless"] = _datum("measured", verdict["meaningless"], features=facts,
                                               rule=verdict["rule"], hits=verdict["hits"], thresholds=verdict["thresholds"])
            except Exception as error:
                result["meaningless"] = _datum("error", reason=f"{type(error).__name__}: {error}")
            data = [*sub.values(), penalty, result["meaningless"]]
            completed = sum(d["status"] in ("measured", "not_applicable") for d in data)
            result["coverage"] = {"expected_components": len(data), "completed_components": completed,
                                  "fraction": completed / len(data)}
            result["status"] = "completed" if completed == len(data) else "partial"
    except GeometryUnavailable as error:
        result.update(status="partial", reason=str(error))
    except EvidenceError as error:
        result.update(reason=f"{type(error).__name__}: {error}", integrity_error=True)
    except Exception as error:
        result.update(reason=f"{type(error).__name__}: {error}")
    finally:
        if files and hashes:
            try:
                if any(_sha(path) != hashes[name] for name, path in files.items()):
                    result.update(status="error", integrity_error=True, reason="Input changed during quality collection")
            except OSError as error:
                result.update(status="error", integrity_error=True, reason=f"Input disappeared: {error}")
        result["seconds"] = round(time.monotonic() - started, 3)
    return _write(out_dir, result)
