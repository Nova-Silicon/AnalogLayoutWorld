"""Interpret the upstream Ahuja AC no-return check without masking missing data."""
import re

from eda.simulation import parse_measurements


def process_case(case, work, values):
    if case["analysis"] == "step":
        return {}
    log = (work / "command.log").read_text(errors="replace")
    required = case["source_measurements"]
    marker = case["return_marker"]
    measured, problems = parse_measurements(log, required + [marker])
    # The upstream predicate also requires every ordinary AC measurement,
    # including finite re-peak diagnostics. An absent crossing alone proves
    # neither that AC ran nor that its output was complete.
    if any(name not in measured for name in required):
        return {}
    if not re.search(r"(?m)^ngspice-\S+\s+done\s*$", log):
        return {}
    if marker in measured:
        return {"no_return_above_0db": 0.0}
    if problems.get(marker) != "missing measurement":
        return {}  # Duplicate/nonfinite return markers are not absent crossings.
    name = re.escape(marker)
    absent = re.search(
        rf"(?im)^\s*Error:\s*measure\s+{name}\s+when\(WHEN\)\s*:\s*out of interval\s*$",
        log,
    )
    attempted = re.search(
        rf"(?im)^\s*meas\s+ac\s+{name}\s+when\s+resp_db=0\s+rise=1\s+failed!\s*$",
        log,
    )
    if absent and attempted:
        return {"no_return_above_0db": 1.0}
    return {}
