#!/usr/bin/env bash
set -euo pipefail

# The verifier image contains this trusted tests directory.
ALB_TESTS="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
ALB_REPORT="${ALB_VERIFIER_DIR:-/logs/verifier}"
ALB_SUBMISSION="${ALB_SUBMISSION_DIR:-/alb-workspace/submission}"
mkdir -p "$ALB_REPORT/tmp" "$ALB_REPORT/cache"
# Harbor consumes reward files even when a verifier command exits nonzero.
# Remove only the published score, retain any prior evaluation evidence.
rm -f -- "$ALB_REPORT/reward.json" "$ALB_REPORT/reward.txt"
if [[ -e "$ALB_REPORT/evaluation" || -L "$ALB_REPORT/evaluation" ]]; then
    printf "Refusing to reuse an existing evaluation directory; choose a new report directory.\n" >&2
    exit 2
fi
export TMPDIR="$ALB_REPORT/tmp"
export XDG_CACHE_HOME="$ALB_REPORT/cache"
export PYTHONDONTWRITEBYTECODE=1
# Harbor supplies the actual allocation; standalone use defaults to task.toml.
export ALB_VERIFIER_CPUS="${ALB_VERIFIER_CPUS:-6}"
export ALB_VERIFIER_SOLVER_POLICY="${ALB_VERIFIER_SOLVER_POLICY:-auto}"
export ALB_VERIFIER_NO_TIMEOUT="${ALB_VERIFIER_NO_TIMEOUT:-1}"
export ALB_VERIFIER_BUDGET_SEC="${ALB_VERIFIER_BUDGET_SEC:-3300}"
export ALB_VERIFIER_RECOVER_COMPLETED="${ALB_VERIFIER_RECOVER_COMPLETED:-1}"

set +e
/opt/analog-layout/python/bin/python3.12 -I -B - "$ALB_TESTS" "$ALB_SUBMISSION" "$ALB_REPORT/evaluation" <<'PY'
from pathlib import Path
import sys
tests, submission, output = map(Path, sys.argv[1:])
# Import from the verifier copy, never the Agent's workspace or submission.
# ALB_BUNDLE_MANIFEST_BEGIN
import hashlib
import json

def check_private_bundle(root, manifest_path):
    manifest = json.loads(manifest_path.read_text())
    for relative, expected in manifest["files"].items():
        name = Path(relative)
        if name.is_absolute() or ".." in name.parts:
            raise RuntimeError("Unsafe private bundle path: " + relative)
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("Missing regular private bundle input: " + relative)
        with path.open("rb") as handle:
            actual = hashlib.file_digest(handle, "sha256").hexdigest()
        if actual != expected:
            raise RuntimeError("Private bundle hash mismatch: " + relative)

# Verify the inputs and tools bundled in this image before reading the submission.
check_private_bundle(tests / "task", tests / "input_manifest.json")
check_private_bundle(tests / "tools", tests / "tool_manifest.json")
# ALB_BUNDLE_MANIFEST_END
sys.path.insert(0, str(tests / "tools"))
from eda.evaluate import main
sys.argv = ["evaluate", "--submission-dir", str(submission), "--task", str(tests / "task"),
            "--out", str(output), "--profile", "full"]
raise SystemExit(main())
PY
ALB_EXIT=$?
set -e
if [[ "$ALB_EXIT" -le 1 ]]; then
    /opt/analog-layout/python/bin/python3.12 -I -B - "$ALB_REPORT" <<'PY_PUBLISH'
import json
import math
from pathlib import Path
import sys
report = Path(sys.argv[1])
try:
    metrics = json.loads((report / "evaluation/metrics.json").read_text())
    reward = json.loads((report / "evaluation/reward.json").read_text())
    score = metrics["score"]
    if (metrics.get("score_valid") is not True or metrics.get("evaluation_error") is not False
            or metrics.get("pipeline_completed") is not True
            or metrics.get("scoring_version") != "analoglayoutworld-paper-v1"
            or type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1
            or not isinstance(reward, dict) or type(reward.get("reward")) not in (int, float)
            or reward != {"reward": score}):
        raise ValueError("No valid terminal paper-v1 reward from this evaluation")
    temporary = report / "reward.json.new"
    temporary.write_text(json.dumps(reward, allow_nan=False) + "\n")
    temporary.replace(report / "reward.json")
except (OSError, KeyError, TypeError, ValueError) as error:
    print("Cannot publish verifier reward: " + str(error), file=sys.stderr)
    raise SystemExit(2)
PY_PUBLISH
fi
exit "$ALB_EXIT"
