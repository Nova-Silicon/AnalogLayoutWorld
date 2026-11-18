"""Exercise trusted entrypoint publication without invoking any EDA software."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout/tests/test.sh"


class EntrypointTests(unittest.TestCase):
    def execute(self, *, metrics=None, exit_code=0, stale=False, corrupt=False, reward=None):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        tests, report = root / "tests", root / "report"
        (tests / "tools/eda").mkdir(parents=True)
        (tests / "task").mkdir()
        report.mkdir()
        (tests / "tools/eda/__init__.py").write_text("")
        metrics = metrics or {"score": 0.4, "score_valid": True,
                              "evaluation_error": False, "pipeline_completed": True,
                              "scoring_version": "analoglayoutworld-paper-v1"}
        reward = reward if reward is not None else {"reward": metrics["score"]}
        module = ("import json\nfrom pathlib import Path\nimport sys\n"
                  "def main():\n"
                  "    out=Path(sys.argv[sys.argv.index('--out')+1]);out.mkdir()\n"
                  f"    (out/'metrics.json').write_text({json.dumps(metrics)!r})\n"
                  f"    (out/'reward.json').write_text({json.dumps(reward)!r})\n"
                  f"    return {exit_code}\n")
        (tests / "tools/eda/evaluate.py").write_text(module)
        tool_files = {p.relative_to(tests / "tools").as_posix():
                      hashlib.sha256(p.read_bytes()).hexdigest()
                      for p in (tests / "tools").rglob("*") if p.is_file()}
        (tests / "tool_manifest.json").write_text(json.dumps({"files": tool_files}))
        (tests / "input_manifest.json").write_text(json.dumps({"files": {}}))
        shell = TEMPLATE.read_text().replace("/opt/analog-layout/python/bin/python3.12", sys.executable)
        (tests / "test.sh").write_text(shell)
        if corrupt:
            (tests / "tools/eda/evaluate.py").write_text("raise RuntimeError('changed tool')\n")
        if stale:
            (report / "evaluation").mkdir()
            (report / "evaluation/reward.json").write_text('{"reward": 0.9}')
            (report / "reward.json").write_text('{"reward": 0.9}')
        env = dict(os.environ, ALB_VERIFIER_DIR=str(report), ALB_SUBMISSION_DIR=str(root / "submission"))
        result = subprocess.run(["bash", str(tests / "test.sh")], env=env,
                                capture_output=True, text=True, timeout=20)
        return result, report

    def test_publishes_current_valid_pass(self):
        result, report = self.execute()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads((report / "reward.json").read_text()), {"reward": 0.4})

    def test_valid_nonpassing_design_keeps_its_score(self):
        result, report = self.execute(exit_code=1)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(json.loads((report / "reward.json").read_text()), {"reward": 0.4})

    def test_existing_evaluation_cannot_republish_old_reward(self):
        result, report = self.execute(stale=True, corrupt=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("Refusing to reuse", result.stderr)
        self.assertFalse((report / "reward.json").exists())
        self.assertEqual(json.loads((report / "evaluation/reward.json").read_text()), {"reward": 0.9})

    def test_bundle_failure_never_publishes(self):
        result, report = self.execute(corrupt=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Private bundle hash mismatch", result.stderr)
        self.assertFalse((report / "reward.json").exists())

    def test_incomplete_or_invalid_metrics_cannot_publish(self):
        for key, value in (("pipeline_completed", False), ("score_valid", False),
                           ("evaluation_error", True), ("scoring_version", "other-protocol")):
            with self.subTest(key=key):
                metrics = {"score": 0.4, "score_valid": True, "evaluation_error": False,
                           "pipeline_completed": True, "scoring_version": "analoglayoutworld-paper-v1"}
                metrics[key] = value
                result, report = self.execute(metrics=metrics, exit_code=1)
                self.assertEqual(result.returncode, 2)
                self.assertFalse((report / "reward.json").exists())

    def test_reward_must_agree_with_metrics(self):
        result, report = self.execute(reward={"reward": 0.9})
        self.assertEqual(result.returncode, 2)
        self.assertFalse((report / "reward.json").exists())


if __name__ == "__main__":
    unittest.main()
