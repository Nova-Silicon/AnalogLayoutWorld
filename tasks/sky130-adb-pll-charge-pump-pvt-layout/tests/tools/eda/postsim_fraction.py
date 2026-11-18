"""Fixed-denominator post-layout pass fractions from trusted analysis plans.

Source-suite ``score_group`` wrappers are presentation and all-pass diagnostics,
not the fraction's denominator. Each configured source analysis earns credit
only if all its required predicates pass. Cross-analysis constraints remain in
force and are attributed to their dependencies (or conservatively to the
affected group). No model, simulator, or submission code is executed here.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path

from . import postsim, suite_runner


def _finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def _limits(limits):
    if not isinstance(limits, dict) or not limits:
        raise ValueError("A scored analysis needs nonempty required measurements")
    for name, bounds in limits.items():
        if (not isinstance(name, str) or not name or not isinstance(bounds, dict)
                or not ({"min", "max"} & set(bounds))):
            raise ValueError("Invalid required measurement declaration")
        for key in ("min", "max"):
            if key in bounds and not _finite(bounds[key]):
                raise ValueError(f"Invalid bound: {name}/{key}")
        if "min" in bounds and "max" in bounds and bounds["min"] > bounds["max"]:
            raise ValueError(f"Reversed bounds: {name}")
    return deepcopy(limits)


def _context(task: Path, profile: str):
    task = Path(task)
    if profile not in ("full", "tt"):
        raise ValueError("Unsupported post-simulation profile")
    settings = postsim.measurement_settings(task)
    selected = postsim.selected_case_ids(settings, reference=False)
    if "suite" in settings:
        adapter = suite_runner.load_adapter(task, settings)
        source = adapter.plan()
        suite_runner.validate_plan(source)
        plan = suite_runner.evaluation_plan(source, selected)
        suite_runner.selected_reducer(adapter, plan)
        if profile == "tt":
            plan = [case for case in plan if case.get("profile") == "tt"]
        # Match suite_runner.simulate: profile filtering is diagnostic, while
        # selected_case_ids determines the actual evaluation/qualification split.
        entries = {case["id"]: {"kind": "source_analysis", "score_group": case["score_group"]}
                   for case in plan}
        context = {"kind": "source", "plan": plan, "adapter": adapter,
                   "all_ids": {case["id"] for case in source}}
    else:
        declared = postsim.load_cases(task)
        plan = suite_runner.evaluation_plan(declared, selected)
        plan = postsim.select_cases(plan, profile)
        entries = {case["id"]: {"kind": "declared_analysis",
                   "score_group": case.get("score_group", case["id"]),
                   "required_measurements": _limits(case["required_measurements"])}
                   for case in plan}
        context = {"kind": "declared", "plan": plan,
                   "all_ids": {case["id"] for case in declared}}
    if not entries:
        raise ValueError("The requested profile has no required scoring items")
    return context, entries


def manifest(task: Path, profile: str = "full") -> dict:
    """Return the immutable scoring-item map, independent of observed results.

    Qualification-only analyses are excluded by the trusted selection.
    """
    return _context(task, profile)[1]


def _unknown(reason, status="missing"):
    return {"status": status, "passed": False, "complete": False,
            "reason": reason, "checks": [], "failed_checks": []}


def _measured(limits: dict, record: dict | None) -> dict:
    if record is None:
        return _unknown("Required analysis was not returned")
    if not isinstance(record, dict) or not isinstance(record.get("measurements", {}), dict):
        return _unknown("Malformed analysis measurements", "invalid")
    rows = record.get("measurements", {})
    missing, checks = [], []
    for name, bounds in limits.items():
        row = rows.get(name)
        value = row.get("value") if isinstance(row, dict) else None
        if not isinstance(row, dict) or row.get("status") != "measured" or not _finite(value):
            missing.append(name)
            continue
        passed = (("min" not in bounds or value >= bounds["min"])
                  and ("max" not in bounds or value <= bounds["max"]))
        checks.append({"name": name, "passed": bool(passed), "value": value, "limits": bounds})
    command = record.get("command") or {}
    successful_exit = "returncode" not in command or command["returncode"] == 0
    execution_complete = (record.get("status") in ("passed", "failed")
                          and not record.get("error_kind") and not record.get("processor_error")
                          and successful_exit)
    complete = bool(not missing and execution_complete)
    failed = [check["name"] for check in checks if not check["passed"]]
    passed = complete and not failed
    return {"status": "passed" if passed else "failed" if complete else "incomplete",
            "passed": bool(passed), "complete": complete, "checks": checks,
            "failed_checks": failed, "missing_measurements": missing,
            "error_kind": record.get("error_kind"),
            "reason": None if complete else "Required measurements or successful analysis completion missing"}


def _check_rows(value, group=None):
    """Flatten native reducer diagnostics while retaining any group binding."""
    if isinstance(value, list):
        for item in value:
            yield from _check_rows(item, group)
    elif isinstance(value, dict):
        group = value.get("score_group", group)
        if "name" in value and "passed" in value:
            yield value, group
        elif "checks" in value:
            yield from _check_rows(value["checks"], group)


def _attribute_reductions(aggregate, analyses, entries):
    constraints = []
    reductions = list(_check_rows(aggregate.get("suite_reductions", [])))
    for group, result in aggregate.get("group_results", {}).items():
        members = [key for key in result.get("required_case_ids", []) if key in analyses]
        checks = list(_check_rows(result.get("suite_checks", []), group))
        for check, binding in reductions:
            deps = check.get("depends_on")
            if (binding == group or (isinstance(deps, list) and set(deps) & set(members))
                    or (binding is None and not deps and result.get("passed") is False)):
                checks.append((check, binding))
        failed_checks = [(check, binding) for check, binding in checks if check.get("passed") is False]
        # Some historical reducers only set group.passed/suite_failure. Preserve
        # this constraint without turning an ordinary 6/7 analysis result into
        # 0/7 merely because its wrapper group failed.
        if (result.get("passed") is False and not failed_checks and members
                and (result.get("suite_failure") or all(analyses[key]["passed"] for key in members))):
            failed_checks = [({"name": "suite_group_constraint", "passed": False,
                              "message": result.get("suite_failure", "Additional suite constraint failed")}, group)]
        seen = set()
        for check, _ in failed_checks:
            key = (check.get("name"), tuple(check.get("depends_on") or []))
            if key in seen:
                continue
            seen.add(key)
            deps = check.get("depends_on")
            affected = [ident for ident in (deps if isinstance(deps, list) else members)
                        if ident in analyses and ident in members]
            if not affected:
                affected = list(members)
            inputs_complete = all(analyses[ident]["complete"] for ident in affected)
            for ident in affected:
                analysis = analyses[ident]
                # A known individual predicate failure stays a failure even
                # when another input needed by a joint constraint is missing.
                if not analysis["passed"]:
                    continue
                analysis.update(passed=False, complete=inputs_complete,
                                status="failed" if inputs_complete else "incomplete")
                analysis["failed_checks"].append(check.get("name", "suite_constraint"))
                analysis.setdefault("suite_constraints", []).append(deepcopy(check))
            constraints.append({"score_group": group, "name": check.get("name"),
                                "passed": False, "status": "failed" if inputs_complete else "incomplete",
                                "affected_case_ids": affected, "check": deepcopy(check)})
    return constraints


def _source_results(context, entries, report):
    evidence = report.get("source_evidence") or {}
    if not isinstance(evidence, dict) or not isinstance(evidence.get("case_results", {}), dict):
        raise ValueError("source_evidence.case_results must be an object")
    observed = evidence.get("case_results", {})
    unexpected = set(observed) - context["all_ids"]
    if unexpected:
        raise ValueError(f"Unexpected source analysis IDs: {sorted(unexpected)}")
    records = []
    for case in context["plan"]:
        item = observed.get(case["id"])
        if item is None:
            continue
        if not isinstance(item, dict):
            raise ValueError(f"Malformed source analysis: {case['id']}")
        row, error = item.get("row"), item.get("error")
        try:
            json.dumps(row, allow_nan=False)
        except (ValueError, TypeError) as exc:
            row, error = None, f"Nonfinite or invalid source measurements: {exc}"
        if row is None and not error:
            error = "Required source measurements missing"
        records.append({"case_id": case["id"], "case": case, "row": row,
                        "error": error, "run": {"returncode": 0 if not error else 1}})
    # Re-run trusted predicates and cross-analysis reductions. Stored passed
    # flags and stored predicate booleans never establish credit on their own.
    aggregate = suite_runner.aggregate(context["adapter"], records, plan=context["plan"])
    integrity = list(evidence.get("integrity_errors") or []) + list(aggregate.get("integrity_errors") or [])
    analyses = {}
    for ident in entries:
        item = aggregate["case_results"][ident]
        checks = item.get("checks") or []
        complete = bool(item.get("error") is None and checks and not integrity)
        passed = bool(complete and all(check["passed"] for check in checks))
        analyses[ident] = {"status": "passed" if passed else "failed" if complete else "missing" if ident not in observed else "incomplete",
                           "passed": passed, "complete": complete,
                           "reason": item.get("error") or ("Suite integrity failure" if integrity else None),
                           "checks": deepcopy(checks),
                           "failed_checks": [check["name"] for check in checks if not check["passed"]]}
    constraints = _attribute_reductions(aggregate, analyses, entries) if not integrity else []
    return analyses, {"integrity_errors": integrity, "group_constraints": constraints,
                      "group_results": aggregate.get("group_results", {}),
                      "unassessed_requirements": aggregate.get("unassessed_requirements", []),
                      "source_evidence_rechecked": True}


def _recover_declared(case, entry, report):
    """Recover one analysis from older grouped output if raw rows were omitted."""
    group = case.get("score_group", case["id"])
    grouped = (report.get("case_results") or {}).get(group)
    if not isinstance(grouped, dict):
        return None
    values = grouped.get("measurements") or {}
    rows = {name: values.get(postsim.metric_key(case, name), {})
            for name in entry["required_measurements"]}
    complete = all(isinstance(row, dict) and row.get("status") == "measured"
                   and _finite(row.get("value")) for row in rows.values())
    return {"status": "passed" if complete else "incomplete", "measurements": rows}


def summarize(task: Path, report: dict | None, profile: str = "full") -> dict:
    """Recheck a fixed manifest and retain failed/unknown items in its denominator.

    ``report`` may be the last atomic checkpoint before a verifier timeout.
    Finished analyses retain their credit; unreturned ones remain unknown.
    """
    context, entries = _context(Path(task), profile)
    if report is None:
        report = {}
    if not isinstance(report, dict):
        raise ValueError("Post-simulation report must be an object")
    diagnostics = {"integrity_errors": [], "group_constraints": []}
    if context["kind"] == "source":
        analyses, diagnostics = _source_results(context, entries, report)
    else:
        raw = report.get("raw_case_results") or {}
        if not isinstance(raw, dict):
            raise ValueError("raw_case_results must be an object")
        unexpected = set(raw) - context["all_ids"]
        if unexpected:
            raise ValueError(f"Unexpected analysis IDs: {sorted(unexpected)}")
        analyses = {case["id"]: _measured(entries[case["id"]]["required_measurements"],
                    raw.get(case["id"]) if case["id"] in raw else
                    _recover_declared(case, entries[case["id"]], report))
                    for case in context["plan"]}
    count = len(entries)
    passed = sum(item["passed"] for item in analyses.values())
    complete = sum(item["complete"] for item in analyses.values())
    failed = sum(item["complete"] and not item["passed"] for item in analyses.values())
    manifest_raw = json.dumps(entries, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return {"schema_version": 1, "scoring_unit": "required_analysis", "profile": profile,
            "required_case_count": count, "passed_case_count": passed,
            "failed_case_count": failed, "unknown_case_count": count - complete,
            "completed_case_count": complete, "pass_fraction": passed / count,
            "coverage": complete / count, "all_passed": passed == count,
            "required_case_ids": list(entries), "manifest": entries,
            "manifest_sha256": hashlib.sha256(manifest_raw).hexdigest(),
            "case_results": analyses, **diagnostics}
