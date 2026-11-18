"""Summarize configured simulation cases; final scoring lives in paper-v1."""
from __future__ import annotations

import math


def finite_number(value: object) -> bool:
    return type(value) in (int, float) and math.isfinite(value)


def summarize_cases(expected: dict, report: dict | None) -> dict:
    """Recheck measurement values against the trusted required-case manifest."""
    if not expected or any(not requirements for requirements in expected.values()):
        raise ValueError("Scoring requires nonempty cases with required measurements")
    for case_id, requirements in expected.items():
        if not isinstance(requirements, dict):
            raise ValueError(f"Case {case_id}: required measurements must be an object")
        for name, limits in requirements.items():
            if not isinstance(limits, dict) or any(
                not finite_number(limits[bound]) for bound in ("min", "max") if bound in limits
            ):
                raise ValueError(f"Case {case_id}, {name}: invalid limits")
            if "min" in limits and "max" in limits and limits["min"] > limits["max"]:
                raise ValueError(f"Case {case_id}, {name}: minimum exceeds maximum")
    reported = (report or {}).get("case_results", {})
    if not isinstance(reported, dict):
        raise ValueError("case_results must map case IDs to results")
    unexpected = set(reported) - set(expected)
    if unexpected:
        raise ValueError(f"Unexpected post-simulation cases: {sorted(unexpected)}")
    cases = {}
    for case_id, requirements in expected.items():
        case = reported.get(case_id)
        if case is None:
            cases[case_id] = {"status": "missing", "passed": False,
                              "missing_measurements": list(requirements), "failed_measurements": []}
            continue
        measurements = case.get("measurements", {})
        if not isinstance(measurements, dict):
            raise ValueError(f"Case {case_id}: measurements must be an object")
        missing, failed = [], []
        for name, limits in requirements.items():
            row = measurements.get(name, {})
            value = row.get("value")
            if row.get("status") != "measured" or not finite_number(value):
                missing.append(name)
                continue
            satisfied = True
            for bound, relation in (("min", lambda v, x: v >= x), ("max", lambda v, x: v <= x)):
                if bound in limits:
                    if not finite_number(limits[bound]):
                        raise ValueError(f"Case {case_id}, {name}: invalid {bound}")
                    satisfied = satisfied and relation(value, limits[bound])
            if not satisfied:
                failed.append(name)
        # A failed/unfinished simulator process cannot become a passing case just
        # because it emitted some plausible measurements before it stopped.
        execution_complete = case.get("status") in ("passed", "failed")
        passed = not missing and not failed and case.get("status") == "passed"
        status = "passed" if passed else "incomplete" if missing or not execution_complete else "failed"
        cases[case_id] = {"status": status, "passed": passed,
                          "missing_measurements": missing, "failed_measurements": failed,
                          "reported_status": case.get("status")}
    count = len(expected)
    passed_count = sum(case["passed"] for case in cases.values())
    return {"required_case_count": count, "passed_case_count": passed_count,
            "pass_fraction": passed_count / count, "all_passed": passed_count == count,
            "case_results": cases}
