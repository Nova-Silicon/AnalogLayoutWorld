"""Exercise the publication selector without Docker, credentials or network."""
from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

try:
    import yaml
except ImportError:
    yaml = None

ROOT = Path(__file__).resolve().parents[1]


@unittest.skipUnless(yaml is not None and shutil.which("bash"),
                     "Publication checks require optional PyYAML and Bash")
class ImageWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # BaseLoader preserves GitHub's `on` key instead of treating it as bool.
        cls.config = yaml.load((ROOT / ".github/workflows/image.yml").read_text(),
                               Loader=yaml.BaseLoader)
        cls.steps = cls.config["jobs"]["build"]["steps"]
        cls.selector = next(s["run"] for s in cls.steps if s.get("id") == "image")

    def select(self, event, ref, tag="", publish=""):
        with tempfile.TemporaryDirectory(prefix="alw-image-selector-") as directory:
            output = Path(directory) / "output"
            env = {"PATH": os.environ.get("PATH", os.defpath),
                   "SOURCE_REPOSITORY": "Example/Benchmark",
                   "EVENT_NAME": event, "SOURCE_REF": ref,
                   "REQUESTED_TAG": tag, "REQUESTED_PUBLISH": publish,
                   "GITHUB_OUTPUT": str(output)}
            result = subprocess.run(["bash", "-c", self.selector], env=env,
                                    capture_output=True, text=True, timeout=10)
            values = dict(line.split("=", 1) for line in output.read_text().splitlines()) \
                if output.exists() else {}
            return result, values

    def test_manual_defaults_to_build_only_and_publish_requires_true(self):
        inputs = self.config["on"]["workflow_dispatch"]["inputs"]
        self.assertEqual(inputs["publish"]["default"], "false")
        for publish in ("false", "true"):
            with self.subTest(publish=publish):
                result, values = self.select("workflow_dispatch", "refs/heads/main",
                                             "paper-v1", publish)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(values, {"publish": publish,
                    "name": "ghcr.io/example/benchmark",
                    "reference": "ghcr.io/example/benchmark:paper-v1"})

    def test_dedicated_tag_publishes_its_suffix_without_manual_inputs(self):
        self.assertEqual(self.config["on"]["push"], {"tags": ["eda-image/*"]})
        self.assertEqual(self.config["jobs"]["build"]["if"],
                         "${{ github.event_name == 'workflow_dispatch' || !github.event.deleted }}")
        result, values = self.select("push", "refs/tags/eda-image/paper-v2")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(values, {"publish": "true",
            "name": "ghcr.io/example/benchmark",
            "reference": "ghcr.io/example/benchmark:paper-v2"})

    def test_unrelated_events_refs_or_invalid_inputs_never_emit_a_publication(self):
        cases = [("push", "refs/heads/main", "", ""),
                 ("push", "refs/tags/paper-v1", "", ""),
                 ("push", "refs/tags/eda-image/paper/v1", "", ""),
                 ("push", "refs/tags/eda-image/", "", ""),
                 ("pull_request", "refs/pull/1/merge", "paper-v1", "true"),
                 ("workflow_dispatch", "refs/heads/main", "paper-v1", "yes")]
        cases += [("workflow_dispatch", "refs/heads/main", tag, "true")
                  for tag in ("", "../bad", "bad;tag", "bad\ntag", "x" * 129)]
        for case in cases:
            with self.subTest(case=case):
                result, values = self.select(*case)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(values, {})

    def test_registry_login_and_push_are_guarded_and_all_shell_blocks_parse(self):
        registry_steps = [s for s in self.steps if "docker login " in s.get("run", "")
                          or "docker push " in s.get("run", "")]
        self.assertEqual(len(registry_steps), 2)
        for step in registry_steps:
            self.assertEqual(step["if"], "${{ steps.image.outputs.publish == 'true' }}")
        for step in self.steps:
            if "run" in step:
                with self.subTest(step=step.get("name")):
                    result = subprocess.run(["bash", "-n"], input=step["run"],
                                            capture_output=True, text=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
