"""Score trusted verifier observations under the fixed paper-v1 protocol."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from . import _scoring_core as _core


SCORING_VERSION = "analoglayoutworld-paper-v1"
QUALITY_NAMES = _core.QUALITY_NAMES
WEIGHT_NAMES = _core.WEIGHT_NAMES
finite_number = _core.finite_number
_PARAMETER_NAMES = frozenset({"weights", "quality_weights", "quality_saturation",
                              "gamma", "q_max", "u_min", "u_target"})
_CONFIG_PATH = Path(__file__).with_name("data") / "paper-v1.json"


def _normalize_parameters(parameters: dict) -> dict:
    if not isinstance(parameters, dict) or set(parameters) != _PARAMETER_NAMES:
        raise ValueError("A complete paper-v1 task parameter map is required")
    levels = parameters["quality_saturation"]
    if (not isinstance(levels, dict) or set(levels) != set(QUALITY_NAMES)
            or any(not finite_number(value) or not 0 < value <= 1
                   for value in levels.values())):
        raise ValueError("Exactly matching/critical/power saturation levels in (0, 1] are required")
    values = _core.normalize_scoring_parameters(
        {**{key: value for key, value in parameters.items() if key != "quality_saturation"},
         "quality_sat_level": 1.0})
    values.pop("quality_sat_level")
    return {**values, "quality_saturation": {name: float(levels[name]) for name in QUALITY_NAMES}}


def _load_protocol() -> tuple[dict, str]:
    raw = _CONFIG_PATH.read_bytes()
    config = json.loads(raw)
    if (not isinstance(config, dict)
            or set(config) != {"schema_version", "protocol_id", "task_ids", "task_parameters"}
            or config["schema_version"] != 1
            or config["protocol_id"] != SCORING_VERSION):
        raise ValueError("Invalid paper-v1 protocol identity or schema")
    tasks, parameters = config["task_ids"], config["task_parameters"]
    if (not isinstance(tasks, list) or len(tasks) != 40
            or any(not isinstance(task, str) or not task for task in tasks)
            or len(set(tasks)) != len(tasks)
            or not isinstance(parameters, dict) or set(tasks) != set(parameters)):
        raise ValueError("The paper-v1 protocol requires exactly 40 unique task IDs")
    for task, values in parameters.items():
        normalized = _normalize_parameters(values)
        if normalized["gamma"] != 2:
            raise ValueError(f"Paper-v1 requires area exponent two: {task}")
        expected = dict(zip(WEIGHT_NAMES, (0.1, 0.1, 0.1, 0.2, 0.1, 0.4)))
        if normalized["weights"] != expected:
            raise ValueError(f"Paper-v1 requires the fixed six global weights: {task}")
    return config, hashlib.sha256(raw).hexdigest()


_PROTOCOL, SCORING_CONFIG_SHA256 = _load_protocol()
TASK_IDS = tuple(_PROTOCOL["task_ids"])


def task_parameters(task_id: str) -> dict:
    """Return a fresh copy of the fixed parameters for one released task."""
    if not isinstance(task_id, str) or task_id not in _PROTOCOL["task_parameters"]:
        raise ValueError("Unknown paper-v1 task ID")
    return _normalize_parameters(_PROTOCOL["task_parameters"][task_id])


def normalize_scoring_parameters(parameters: dict | None = None,
                                 task_name: str | None = None) -> dict:
    """Select and validate the fixed parameters for one task."""
    expected = task_parameters(task_name)
    if parameters is not None and _normalize_parameters(parameters) != expected:
        raise ValueError("Parameters differ from the fixed paper-v1 task protocol")
    return expected


def _core_parameters(parameters: dict) -> dict:
    return {**{key: deepcopy(value) for key, value in parameters.items()
               if key != "quality_saturation"}, "quality_sat_level": 1.0}


def assess_shape(area_report: dict | None, scoring_parameters: dict | None = None,
                 task_name: str | None = None) -> dict:
    """Apply the same fixed shape criterion used by the final score."""
    parameters = normalize_scoring_parameters(scoring_parameters, task_name)
    result = _core.assess_shape(area_report, _core_parameters(parameters), task_name)
    result.update(scoring_parameters=parameters, scoring_config_sha256=SCORING_CONFIG_SHA256)
    return result


def score_submission(*, submission_present: bool, stages: dict, cases: dict,
                     profile: str, evaluation_error: bool = False,
                     scoring_version: str = SCORING_VERSION,
                     scoring_parameters: dict | None = None,
                     task_name: str | None = None, quality: dict | None = None) -> dict:
    """Score trusted evaluator observations under the fixed paper-v1 protocol.

    Inputs are not mutated. Missing evidence remains a lower bound, and existing
    backend-specific policy credit requires the same authenticated invocation
    and passed LVS evidence as the original implementation.
    """
    if scoring_version != SCORING_VERSION:
        raise ValueError("Unknown scoring protocol")
    parameters = normalize_scoring_parameters(scoring_parameters, task_name)
    if not isinstance(stages, dict) or not isinstance(cases, dict):
        raise ValueError("stages and cases must be trusted observation objects")
    facts = {"submission_present": submission_present, "stages": deepcopy(stages),
             "cases": deepcopy(cases), "profile": profile,
             "evaluation_error": evaluation_error, "task_name": task_name,
             "scoring_parameters": _core_parameters(parameters)}
    if quality is not None:
        facts["quality"] = deepcopy(quality)
    report = (facts["quality"] if quality is not None else
              ((facts["stages"].get("quality") or {}).get("tool_result") or {}))
    if not isinstance(report, dict):
        raise ValueError("Quality report must be an object")
    raw = {}
    if not _core._magic_policy_credit(report, facts["stages"], task_name):
        rows = report.get("subscores") or {}
        if not isinstance(rows, dict):
            raise ValueError("Quality subscores must be an object")
        for name in QUALITY_NAMES:
            row = rows.get(name) or {}
            if not isinstance(row, dict):
                raise ValueError(f"Quality item {name} must be an object")
            if parameters["quality_weights"][name] and row.get("status") == "measured":
                value = row.get("value")
                if not finite_number(value) or not 0 <= value <= 1:
                    raise ValueError(f"quality.{name} must be a finite number in [0, 1]")
                raw[name] = value
                row["value"] = min(1.0, value / parameters["quality_saturation"][name])
    result = _core.score_submission(**facts)
    for name, value in raw.items():
        row = result["quality_summary"]["subscores"].get(name)
        if row is not None and row.get("status") == "measured":
            row["raw"] = value
    result.update(scoring_version=SCORING_VERSION,
                  scoring_config_sha256=SCORING_CONFIG_SHA256,
                  scoring_parameters=parameters)
    return result
