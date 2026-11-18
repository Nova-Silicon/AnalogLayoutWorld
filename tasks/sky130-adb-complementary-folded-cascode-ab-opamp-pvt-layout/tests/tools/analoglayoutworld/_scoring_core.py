"""Pure additive scorer preserved from the benchmark's validated implementation.

Private arithmetic implementation: callers must supply a complete parameter
map. Public protocol selection and independent quality saturation live in
``analoglayoutworld.scoring``. This module never reads historical defaults or
runs EDA tools.
"""
from __future__ import annotations

from copy import deepcopy
import math


SCORING_VERSION = "layout-quality-linear-v1"
SCORING_CONFIG_SHA256 = "caller-supplied-parameters"
ALLOWED_GAMMAS = (1, 2, 3)
WEIGHT_NAMES = ("gds", "lvs", "drc", "area", "quality", "postsim")
QUALITY_NAMES = ("matching", "critical", "power")
PARAMETER_NAMES = frozenset(("weights", "q_max", "u_min", "u_target", "gamma",
                             "quality_weights", "quality_sat_level"))
MAGIC_POLICY_ID = "magic-netgen-quality-v1"
MAGIC_POLICY_TASKS = frozenset({
    "sky130-adb-buf-ppsf-bs-gain1-sfdr90-layout",
    "sky130-adb-fct-residue-amplifier-900msps-layout",
})


def finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def _validate(parameters: dict) -> dict:
    if set(parameters) != PARAMETER_NAMES:
        raise ValueError("Incomplete scoring parameters")
    values = deepcopy(parameters)
    for key, names in (("weights", WEIGHT_NAMES), ("quality_weights", QUALITY_NAMES)):
        group = values[key]
        if not isinstance(group, dict) or set(group) != set(names):
            raise ValueError(f"{key} must contain exactly {names}")
        if any(not finite_number(v) or v < 0 for v in group.values()):
            raise ValueError(f"{key} must contain finite nonnegative numbers")
        total = math.fsum(group.values())
        if total <= 0:
            raise ValueError(f"{key} must have positive total weight")
        if key == "weights" and not math.isclose(total, 1.0, rel_tol=0, abs_tol=1e-9):
            raise ValueError("The six score weights must sum to 1")
        values[key] = {name: float(group[name]) / total for name in names}
    for key in ("q_max", "u_min", "u_target", "quality_sat_level"):
        if not finite_number(values[key]):
            raise ValueError(f"{key} must be a finite number")
        values[key] = float(values[key])
    if values["q_max"] < 1:
        raise ValueError("q_max must be at least 1")
    if values["u_min"] < 0:
        raise ValueError("u_min must be nonnegative")
    if values["u_target"] <= 0:
        raise ValueError("u_target must be positive; targets above 1 are allowed")
    if not 0 < values["quality_sat_level"] <= 1:
        raise ValueError("quality_sat_level must be in (0, 1]")
    if not finite_number(values["gamma"]) or values["gamma"] not in ALLOWED_GAMMAS:
        raise ValueError(f"gamma must be one of {ALLOWED_GAMMAS}")
    values["gamma"] = int(values["gamma"])
    return values


def normalize_scoring_parameters(parameters: dict | None = None,
                                 task_name: str | None = None) -> dict:
    """Validate an explicit complete map, with no implicit task/default merge."""
    if task_name is not None and (not isinstance(task_name, str) or not task_name):
        raise ValueError("task_name must be a nonempty string or None")
    if not isinstance(parameters, dict):
        raise ValueError("A complete explicit scoring parameter map is required")
    return _validate(parameters)


def assess_shape(area_report: dict | None, scoring_parameters: dict | None = None,
                 task_name: str | None = None) -> dict:
    parameters = normalize_scoring_parameters(scoring_parameters, task_name)
    geometry = (area_report or {}).get("geometry") or {}
    width, height = geometry.get("width_um"), geometry.get("height_um")
    valid = (finite_number(width) and finite_number(height) and width > 0 and height > 0)
    ratio = max(width, height) / min(width, height) if valid else None
    return {"geometry_valid": bool(valid), "shape_ratio": ratio,
            "shape_ok": bool(valid and ratio <= parameters["q_max"]),
            "scoring_parameters": parameters,
            "scoring_config_sha256": SCORING_CONFIG_SHA256}


def _unit_interval(value: object, label: str) -> float:
    if not finite_number(value) or not 0 <= value <= 1:
        raise ValueError(f"{label} must be a finite number in [0, 1]")
    return float(value)


def summarize_quality(report: dict | None, parameters: dict) -> dict:
    """Combine unsaturated program subitems without hiding measurement errors.

    ``subscores`` maps matching/critical/power to objects with ``status`` and
    ``value``. Only an explicit ``not_applicable`` status removes a weight.
    ``coupling_penalty`` is a similarly shaped fractional deduction. The
    collector must bind all measurements and applicability to trusted inputs.
    """
    report = report or {}
    rows = report.get("subscores") or {}
    if not isinstance(rows, dict):
        raise ValueError("Quality subscores must be an object")
    missing, applicable = [], []
    numerators = []
    observed_weight = 0.0
    details = {}
    for name, weight in parameters["quality_weights"].items():
        row = rows.get(name) or {}
        if not isinstance(row, dict):
            raise ValueError(f"Quality item {name} must be an object")
        status = row.get("status", "missing")
        if weight == 0:
            details[name] = {"status": "disabled", "weight": 0.0}
            continue
        if status == "not_applicable":
            if not row.get("reason"):
                raise ValueError(f"Quality item {name}: not_applicable requires a reason")
            details[name] = {"status": status, "reason": row["reason"], "weight": weight}
            continue
        applicable.append(weight)
        if status == "measured":
            value = _unit_interval(row.get("value"), f"quality.{name}")
            scaled = min(1.0, value / parameters["quality_sat_level"])
            numerators.append(weight * scaled)
            observed_weight += weight
            details[name] = {"status": status, "raw": value, "saturated": scaled,
                             "weight": weight}
        else:
            missing.append(name)
            details[name] = {"status": status, "weight": weight,
                             "reason": row.get("reason", "Measurement unavailable")}
    denominator = math.fsum(applicable)
    base = math.fsum(numerators) / denominator if denominator else None
    penalty_row = report.get("coupling_penalty") or {}
    if not isinstance(penalty_row, dict):
        raise ValueError("coupling_penalty must be an object")
    penalty_status = penalty_row.get("status", "missing")
    if penalty_status == "measured":
        penalty = _unit_interval(penalty_row.get("value"), "coupling_penalty")
    elif penalty_status == "not_applicable" and penalty_row.get("reason"):
        penalty = 0.0
    else:
        # The actual penalty may be anything in [0, 1]. No deduction evidence
        # cannot be treated as proof of zero coupling: use a lower bound.
        penalty = 1.0
        missing.append("coupling_penalty")
    if not denominator:
        missing.append("applicable_quality_items")
    return {"status": "complete" if not missing else "incomplete",
            "complete": not missing, "value": (base or 0.0) * (1.0 - penalty),
            "base": base, "coupling_penalty": penalty,
            "coverage": observed_weight / denominator if denominator else 0.0,
            "missing_items": missing, "subscores": details}


def _postsim_summary(cases: dict, simulation: dict, pex_success: bool) -> dict:
    fraction = _unit_interval(cases.get("pass_fraction", 0.0), "postsim pass_fraction")
    coverage = cases.get("coverage", cases.get("measurement_coverage"))
    if coverage is None:
        coverage = 1.0 if (cases.get("all_passed") is True or
                           simulation.get("status") in ("completed", "measurement_failed")) else 0.0
    coverage = _unit_interval(coverage, "postsim coverage")
    if fraction > coverage + 1e-12:
        raise ValueError("Post-simulation passed weight exceeds completed coverage")
    # Cases are the evaluator's rechecked fixed leaf-level manifest. Confirmed
    # earlier cases survive an overall timeout. An unusable PEX cannot supply
    # any electrical credit, even if a caller passes unrelated old scalars.
    return {"pass_fraction": fraction if pex_success else 0.0,
            "reported_pass_fraction": fraction, "coverage": coverage if pex_success else 0.0,
            "complete": bool(pex_success and coverage == 1.0),
            "all_passed": bool(pex_success and coverage == 1.0 and fraction == 1.0)}


def _magic_policy_credit(report: dict, stages: dict, task_name: str | None) -> bool:
    """Recognize the fixed two-task Magic/Netgen quality policy."""
    # PPSF/FCT use a backend without the quality/morphology collector. After trusted
    # LVS, retain quality=1 and the morphology exemption; shape/area still apply.
    policy = report.get("policy_credit")
    quality_stage = stages.get("quality") or {}
    lvs_stage = stages.get("lvs") or {}
    return bool(task_name in MAGIC_POLICY_TASKS
                and report.get("status") == "policy_credit"
                and isinstance(policy, dict)
                and policy.get("id") == MAGIC_POLICY_ID
                and policy.get("task_name") == task_name
                and policy.get("backend") == "magic_netgen"
                and lvs_stage.get("status") == "passed"
                and (lvs_stage.get("tool_result") or {}).get("backend") == "magic_netgen"
                and (quality_stage.get("invocation") or {}).get("function") == "eda.quality.collect")


def score_submission(*, submission_present: bool, stages: dict, cases: dict,
                     profile: str, evaluation_error: bool = False,
                     scoring_version: str = SCORING_VERSION,
                     scoring_parameters: dict | None = None,
                     task_name: str | None = None, quality: dict | None = None) -> dict:
    """Return the additive score and completeness of its supporting evidence.

    Quality may be passed directly or as ``stages['quality']['tool_result']``.
    Its ``meaningless`` member is ``{'status': 'measured', 'value': bool}``.
    A missing morphology verdict withholds all contingent bonuses until the
    gate is known, rather than silently treating the layout as meaningful.
    """
    if scoring_version != SCORING_VERSION:
        raise ValueError(f"Unknown scoring version: {scoring_version!r}")
    parameters = normalize_scoring_parameters(scoring_parameters, task_name)
    weights = parameters["weights"]
    present = bool(submission_present)
    lvs = present and stages.get("lvs", {}).get("status") == "passed"
    drc = present and stages.get("drc", {}).get("status") == "passed"
    pex_success = stages.get("pex", {}).get("status") == "completed"
    area = stages.get("area") or {}
    area_report = area.get("tool_result") or {}
    shape = assess_shape(area_report, parameters, task_name)
    measured = area.get("status") == "measured"
    raw = area_report.get("raw_area_utilization", area_report.get("area_utilization"))
    area_valid = bool(measured and shape["geometry_valid"] and finite_number(raw) and raw >= 0)
    raw = float(raw) if area_valid else None
    low_fill = raw < parameters["u_min"] if raw is not None else None
    quality_report = quality if quality is not None else (
        (stages.get("quality") or {}).get("tool_result") or {})
    policy_credit = _magic_policy_credit(quality_report, stages, task_name)
    quality_result = ({"status": "policy_credit", "complete": True, "value": 1.0,
                       "base": None, "coupling_penalty": None, "coverage": 0.0,
                       "missing_items": [], "subscores": {}, "measured": False,
                       "policy_credit": deepcopy(quality_report["policy_credit"])}
                      if policy_credit else summarize_quality(quality_report, parameters))
    morphology = quality_report.get("meaningless") or {}
    if not isinstance(morphology, dict):
        raise ValueError("meaningless must be a measured verdict object")
    morphology_exempt = policy_credit and morphology.get("status") == "not_applicable_backend"
    morphology_known = bool(morphology_exempt or (
        morphology.get("status") == "measured" and type(morphology.get("value")) is bool))
    meaningless = False if morphology_exempt else morphology["value"] if morphology_known else None
    shape_known = bool(measured and shape["geometry_valid"])
    blocked = bool((shape_known and not shape["shape_ok"]) or low_fill is True or meaningless is True)
    gate_known = bool(blocked or (shape_known and area_valid and morphology_known))
    bonuses_eligible = bool(present and lvs and gate_known and not blocked)
    area_completion = min(1.0, raw / parameters["u_target"]) ** parameters["gamma"] if area_valid else 0.0
    postsim = _postsim_summary(cases, stages.get("postsim") or {}, pex_success)
    components = {name: 0.0 for name in WEIGHT_NAMES}
    components["gds"] = weights["gds"] if present else 0.0
    if lvs:
        components["lvs"] = weights["lvs"]
        components["drc"] = weights["drc"] if drc else 0.0
    if bonuses_eligible:
        components.update(area=weights["area"] * area_completion,
                          quality=weights["quality"] * quality_result["value"],
                          postsim=weights["postsim"] * postsim["pass_fraction"])
    pending = []
    if present and stages.get("lvs", {}).get("status") not in ("passed", "failed"):
        pending.append("lvs")
    if lvs:
        if weights["drc"] > 0 and stages.get("drc", {}).get("status") not in ("passed", "failed"):
            pending.append("drc")
        if not gate_known:
            pending.append("layout_gate")
        elif not blocked:
            if weights["area"] > 0 and not area_valid:
                pending.append("area")
            if weights["quality"] > 0 and not quality_result["complete"]:
                pending.append("quality")
            if weights["postsim"] > 0 and not postsim["complete"]:
                pending.append("postsim")
    invalid = []
    if evaluation_error:
        invalid.append("Evaluation input/configuration integrity error; see diagnostics")
    if profile != "full":
        invalid.append("A diagnostic profile cannot produce a full-task benchmark score")
    valid = not invalid
    complete = bool(valid and not pending)
    score = round(math.fsum(components.values()), 12) if valid else None
    inputs = {"submission_present": present, "geometry_valid": bool(measured and shape["geometry_valid"]),
              "shape_ratio": shape["shape_ratio"], "shape_ok": bool(shape_known and shape["shape_ok"]),
              "raw_area_ratio": raw, "low_fill": low_fill, "meaningless": meaningless,
              "layout_gate_known": gate_known, "layout_gate_blocked": blocked,
              "lvs_pass": bool(lvs), "drc_pass": bool(drc), "pex_success": pex_success,
              "postsim_case_fraction": postsim["pass_fraction"],
              "postsim_coverage": postsim["coverage"], "postsim_all_passed": postsim["all_passed"],
              "quality_rate": quality_result["value"], "quality_complete": quality_result["complete"],
              "quality_policy_credit": policy_credit, "morphology_policy_exempt": morphology_exempt}
    return {"scoring_version": SCORING_VERSION, "scoring_config_sha256": SCORING_CONFIG_SHA256,
            "scoring_parameters": parameters, "scoring_inputs": inputs,
            "score": score, "score_valid": valid, "score_complete": complete,
            "score_is_lower_bound": bool(valid and pending), "score_pending_reasons": pending,
            "score_invalid_reasons": invalid, "score_components": components,
            "score_weights": deepcopy(weights), "shape_ratio": shape["shape_ratio"],
            "shape_ok": inputs["shape_ok"], "raw_area_ratio": raw,
            "quality_summary": quality_result, "postsim_summary": postsim,
            "bonuses_eligible": bonuses_eligible, "area_eligible": bonuses_eligible and area_valid,
            "electrical_eligible": bool(present and lvs and pex_success),
            "design_passed": bool(valid and complete and bonuses_eligible and drc and postsim["all_passed"]),
            "diagnostics": {**inputs, "area_completion": area_completion,
                            "score_pending_reasons": list(pending)}}
