"""Keep the public job launcher on native Harbor's task and budget contract."""
from __future__ import annotations

import importlib.util
from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("public_harbor_launcher", ROOT / "scripts/run_harbor.py")
launcher = importlib.util.module_from_spec(spec)
spec.loader.exec_module(launcher)
TASK = "sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout"


class HarborLaunchTests(unittest.TestCase):
    def config(self, **kwargs):
        values = dict(task=TASK, agent="opencode", model="provider/model", concurrency=1,
                      name="example-run", jobs_dir=Path("/tmp/example-jobs"), agent_version="1.19.0")
        values.update(kwargs)
        return launcher.job_config(**values)

    def test_native_docker_configuration_defaults_to_three_attempts_and_no_retries(self):
        x = self.config()
        self.assertEqual(x["environment"], {"type": "docker", "delete": True})
        self.assertEqual(x["n_attempts"], 3)
        self.assertEqual(x["retry"], {"max_retries": 0})
        self.assertEqual(x["tasks"], [{"path": str(ROOT / "tasks" / TASK)}])
        self.assertNotIn("extra_instructions", x)
        self.assertNotIn("extra_instruction_paths", x)
        self.assertEqual(x["agents"][0]["kwargs"], {"version": "1.19.0"})

    def test_single_attempt_diagnostic_can_be_selected_explicitly(self):
        x = self.config(attempts=1)
        self.assertEqual(x["n_attempts"], 1)
        self.assertEqual(x["retry"], {"max_retries": 0})

    def test_all_means_exactly_the_current_40_tasks(self):
        x = self.config(task="all", concurrency=2)
        self.assertEqual(len(x["tasks"]), 40)
        self.assertEqual(len({r["path"] for r in x["tasks"]}), 40)
        self.assertEqual(x["verifier"]["env"]["ALB_VERIFIER_BUDGET_SEC"], "3300")

    def test_invalid_configuration_is_rejected_without_launch(self):
        for change in ({"task": "not-a-task"}, {"name": "../bad"}, {"concurrency": 0},
                       {"model": None}, {"agent_version": "$(something)"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.config(**change)

    def test_attempts_must_be_a_positive_integer(self):
        for attempts in (0, -1, 1.5, "3", True):
            with self.subTest(attempts=attempts), self.assertRaisesRegex(
                    ValueError, "Attempts must be a positive integer"):
                self.config(attempts=attempts)

    def test_oracle_diagnostic_does_not_require_a_model_or_fake_credentials(self):
        x = self.config(agent="oracle", model=None, agent_version=None)
        self.assertEqual(x["agents"], [{"name": "oracle"}])
        self.assertNotIn("env", x["agents"][0])

    def test_dry_run_writes_a_native_configuration_without_starting_harbor(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--task", TASK, "--model", "openai/example-model", "--agent-version", "1.19.0",
                    "--job-name", "example-run", "--jobs-dir", directory, "--dry-run"]
            with patch.object(launcher.subprocess, "run") as execute, redirect_stdout(io.StringIO()):
                self.assertEqual(launcher.main(args), 0)
            execute.assert_not_called()
            config = json.loads((Path(directory) / "example-run.json").read_text())
            self.assertEqual(config["job_name"], "example-run")
            self.assertEqual(config["n_attempts"], 3)
            self.assertEqual(config["agents"], [{"name": "opencode", "model_name": "openai/example-model",
                                                 "kwargs": {"version": "1.19.0"}}])
            self.assertEqual(config["tasks"], [{"path": str(ROOT / "tasks" / TASK)}])

    def test_dry_run_accepts_an_explicit_single_attempt(self):
        with tempfile.TemporaryDirectory() as directory:
            args = ["--task", TASK, "--model", "openai/example-model", "--attempts", "1",
                    "--job-name", "diagnostic-run", "--jobs-dir", directory, "--dry-run"]
            with patch.object(launcher.subprocess, "run") as execute, redirect_stdout(io.StringIO()):
                self.assertEqual(launcher.main(args), 0)
            execute.assert_not_called()
            config = json.loads((Path(directory) / "diagnostic-run.json").read_text())
            self.assertEqual(config["n_attempts"], 1)

    def test_invalid_cli_attempts_are_rejected_before_writing_or_launching(self):
        for attempts in ("0", "-1", "1.5", "invalid"):
            with self.subTest(attempts=attempts), tempfile.TemporaryDirectory() as directory:
                args = ["--task", TASK, "--model", "openai/example-model", "--attempts", attempts,
                        "--job-name", "invalid-run", "--jobs-dir", directory, "--dry-run"]
                with patch.object(launcher.subprocess, "run") as execute, redirect_stderr(io.StringIO()):
                    with self.assertRaises(SystemExit) as error:
                        launcher.main(args)
                self.assertEqual(error.exception.code, 2)
                self.assertEqual(list(Path(directory).iterdir()), [])
                execute.assert_not_called()

    def test_an_existing_dry_run_configuration_is_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "example-run.json"
            path.write_text('{"job_name":"previous-run"}\n')
            before = path.read_bytes()
            args = ["--task", TASK, "--model", "openai/example-model", "--job-name", "example-run",
                    "--jobs-dir", directory, "--dry-run"]
            with patch.object(launcher.subprocess, "run") as execute, redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as error:
                    launcher.main(args)
            self.assertEqual(error.exception.code, 2)
            self.assertEqual(path.read_bytes(), before)
            execute.assert_not_called()

    def test_pinned_harbor_schema_accepts_the_job(self):
        try:
            from harbor.models.job.config import JobConfig
        except ImportError:
            self.skipTest("Harbor is an optional host dependency")
        job = JobConfig.model_validate(self.config(task="all"))
        self.assertEqual(len(job.tasks), 40)
        self.assertEqual(job.n_attempts, 3)


if __name__ == "__main__":
    unittest.main()
