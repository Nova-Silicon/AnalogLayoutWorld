"""Exercise Docker lifecycle and error boundaries without Docker or network access."""
from __future__ import annotations

import argparse
from contextlib import redirect_stdout
import io
import json
import math
import os
import signal
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from analoglayoutworld import runner


TASK_ID = "sky130-example-layout"
CONTAINER_ID = "c" * 64
IMAGE_ID = "sha256:" + "d" * 64
RUN_ID = "alw-verify-" + "a" * 16


class FakeDocker:
    """Model server-side resources separately from possibly failed client calls."""

    def __init__(self, *, verifier_rc=0, metrics=None, failures=None,
                 container_owner=RUN_ID, image_owner=RUN_ID,
                 inspect_failure_after_exec=False):
        self.calls = []
        self.verifier_rc = verifier_rc
        self.metrics = metrics if metrics is not None else {
            "pipeline_completed": True, "score_valid": True,
            "evaluation_error": False, "score": 0.76, "design_passed": True,
            "score_is_lower_bound": False,
        }
        self.failures = failures or {}
        self.container_owner = container_owner
        self.image_owner = image_owner
        self.inspect_failure_after_exec = inspect_failure_after_exec
        self.container_exists = False
        self.image_exists = False
        self.executed = False
        self.stopped = False
        self.collected = False
        self.submitted_files = None
        self.image = None

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        assert argv[0] == "docker", "Tests must never execute a non-mocked command"
        operation = argv[1]
        if argv[1:3] == ["container", "inspect"]:
            if self.inspect_failure_after_exec and self.executed:
                return subprocess.CompletedProcess(argv, 1, "", "Cannot connect to the Docker daemon")
            if not self.container_exists:
                return subprocess.CompletedProcess(argv, 1, "", f"Error: No such container: {argv[-1]}")
            return subprocess.CompletedProcess(argv, 0, f"{CONTAINER_ID}|{self.container_owner}\n", "")
        if argv[1:3] == ["image", "inspect"]:
            if not self.image_exists:
                return subprocess.CompletedProcess(argv, 1, "", f"Error: No such image: {argv[-1]}")
            return subprocess.CompletedProcess(argv, 0, f"{IMAGE_ID}|{self.image_owner}\n", "")
        if operation == "build":
            self.image = argv[argv.index("--tag") + 1]
            self.image_exists = True
        if operation == "create":
            # Creation can commit at the server before the client times out.
            self.container_exists = True
        if operation == "exec":
            self.executed = True
        if operation == "cp":
            operation = "collect" if argv[2].endswith(":/logs/verifier") else "deliver"
            if argv[3].endswith(":/alb-workspace/submission"):
                source = Path(argv[2].removesuffix("/."))
                self.submitted_files = sorted(str(p.relative_to(source))
                                              for p in source.rglob("*") if p.is_file())
        if argv[1:3] == ["image", "rm"]:
            operation = "image-rm"
        failure = self.failures.get(operation)
        if isinstance(failure, BaseException):
            raise failure
        if failure is not None:
            return subprocess.CompletedProcess(argv, failure)
        if operation == "stop":
            self.stopped = True
        elif operation == "collect":
            destination = Path(argv[3]) / "evaluation"
            destination.mkdir(parents=True)
            if self.metrics is not False:
                (destination / "metrics.json").write_text(json.dumps(self.metrics))
            self.collected = True
        elif operation == "rm":
            self.container_exists = False
        elif operation == "image-rm":
            self.image_exists = False
        if operation == "exec":
            return subprocess.CompletedProcess(argv, self.verifier_rc)
        return subprocess.CompletedProcess(argv, 0)


class RunnerFixture(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="alw-runner-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        (self.root / "configs/paper-v1").mkdir(parents=True)
        (self.root / "configs/paper-v1/tasks.json").write_text(json.dumps({
            "tasks": [{"task_id": TASK_ID, "number": 1, "title": "Example"}],
        }))
        task = self.root / "tasks" / TASK_ID
        (task / "environment").mkdir(parents=True)
        (task / "tests").mkdir()
        (task / "environment/Dockerfile").write_text(
            "ARG ALW_BASE_IMAGE=example:fixed\nFROM ${ALW_BASE_IMAGE}\n")
        (task / "tests/test.sh").write_text("#!/bin/sh\nexit 0\n")
        (task / "task.toml").write_text('[environment]\n[environment.env]\nPDK_ROOT="/opt/pdk"\n')
        self.source = self.root / "submission"
        (self.source / "src").mkdir(parents=True)
        (self.source / "layout.gds").write_bytes(b"fixed-gds-placeholder")
        (self.source / "src/design.py").write_text("# Archived; never executed by the runner\n")
        (self.source / "README.md").write_text("Example submission\n")
        (self.source / "not-an-artifact.txt").write_text("Must not be copied\n")
        self.output = self.root / "output"

    def args(self, **changes):
        values = dict(repository=str(self.root), task=TASK_ID, submission=str(self.source),
                      out=str(self.output), cpus=6.0, memory="32g", base_image=None)
        values.update(changes)
        return argparse.Namespace(**values)

    def run_fake(self, docker, **changes):
        with patch.object(runner.shutil, "which", return_value="/mock/docker"), \
                patch.object(runner.subprocess, "run", side_effect=docker), \
                patch.object(runner.uuid, "uuid4", return_value=SimpleNamespace(hex="a" * 32)), \
                redirect_stdout(io.StringIO()):
            return runner.verify(self.args(**changes))

    def summary(self):
        return json.loads(self.output.joinpath("summary.json").read_text())


class Lifecycle(RunnerFixture):
    def test_report_uses_published_dockerfile_default_without_stale_local_tag(self):
        image = "ghcr.io/example/eda@sha256:" + "d" * 64
        path = self.root / "tasks" / TASK_ID / "environment/Dockerfile"
        path.write_text("ARG ALW_BASE_IMAGE=" + image + "\nFROM ${ALW_BASE_IMAGE}\n")
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker), 0)
        self.assertEqual(self.summary()["base_image"], image)

    def test_explicit_development_image_is_built_and_reported_consistently(self):
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker, base_image="local/eda:rebuild"), 0)
        self.assertEqual(self.summary()["base_image"], "local/eda:rebuild")
        build = next(call for call in docker.calls if call[1] == "build")
        self.assertIn("ALW_BASE_IMAGE=local/eda:rebuild", build)

    def test_success_stops_then_collects_then_removes_own_identity(self):
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker), 0)
        summary = self.summary()
        self.assertEqual(summary["status"], "evaluated")
        self.assertTrue(summary["cleanup_complete"])
        self.assertEqual(summary["score"], 0.76)
        self.assertFalse(docker.container_exists)
        self.assertFalse(docker.image_exists)
        operations = [call[1] for call in docker.calls]
        stop = operations.index("stop")
        collect = next(i for i, call in enumerate(docker.calls)
                       if call[1] == "cp" and call[2].endswith(":/logs/verifier"))
        remove = operations.index("rm")
        self.assertLess(stop, collect)
        self.assertLess(collect, remove)
        for call in docker.calls:
            if call[1] in ("start", "stop", "rm"):
                self.assertEqual(call[-1], CONTAINER_ID)
        self.assertTrue(any(call[1:3] == ["container", "inspect"]
                            for call in docker.calls[:stop]))
        build = next(call for call in docker.calls if call[1] == "build")
        self.assertIn("org.analoglayoutworld.run=" + RUN_ID, build)
        self.assertEqual(Path(build[-1]), self.root / "tasks" / TASK_ID / "environment")
        self.assertNotIn("prune", operations)

    def test_valid_nonpassing_or_partial_score_is_not_an_execution_error(self):
        metrics = {"pipeline_completed": True, "score_valid": True, "evaluation_error": False,
                   "score": 0.23, "design_passed": False, "score_is_lower_bound": True}
        docker = FakeDocker(verifier_rc=1, metrics=metrics)
        self.assertEqual(self.run_fake(docker), 1)
        self.assertEqual(self.summary()["status"], "evaluated")
        self.assertTrue(self.summary()["score_is_lower_bound"])

    def test_outer_timeout_stops_server_work_and_retains_reports_without_grading(self):
        docker = FakeDocker(failures={"exec": subprocess.TimeoutExpired("docker exec", 3600)})
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.stopped)
        self.assertTrue(docker.collected)
        summary = self.summary()
        self.assertEqual(summary["verifier_returncode"], 124)
        self.assertEqual(summary["status"], "error")
        self.assertNotIn("score", summary)
        self.assertTrue((self.output / summary["metrics"]).is_file())

    def test_client_oserror_still_collects_before_container_removal(self):
        docker = FakeDocker(failures={"exec": OSError("client connection closed")})
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.collected)
        self.assertFalse(docker.container_exists)
        self.assertEqual(self.summary()["status"], "error")

    def test_server_created_container_is_recovered_after_create_client_timeout(self):
        docker = FakeDocker(failures={"create": subprocess.TimeoutExpired("docker create", 180)})
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.stopped)
        self.assertTrue(docker.collected)
        self.assertFalse(docker.container_exists)
        self.assertTrue(self.summary()["cleanup_complete"])

    def test_stop_failure_does_not_skip_report_collection(self):
        docker = FakeDocker(failures={"stop": 1})
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.collected)
        self.assertFalse(docker.container_exists)
        self.assertIn("stop", self.summary()["reason"])

    def test_failed_or_timed_out_collection_is_a_run_error_and_still_cleans(self):
        for failure in (1, subprocess.TimeoutExpired("docker cp", 180)):
            with self.subTest(failure=type(failure).__name__):
                if self.output.exists():
                    import shutil
                    shutil.rmtree(self.output)
                docker = FakeDocker(failures={"collect": failure})
                self.assertEqual(self.run_fake(docker), 2)
                self.assertFalse(docker.container_exists)
                self.assertEqual(self.summary()["status"], "error")

    def test_image_removal_nonzero_is_reported_as_incomplete_cleanup(self):
        docker = FakeDocker(failures={"image-rm": 1})
        self.assertEqual(self.run_fake(docker), 2)
        self.assertFalse(self.summary()["cleanup_complete"])
        self.assertTrue(docker.image_exists)
        self.assertIn("image", " ".join(self.summary()["cleanup_errors"]))

    def test_container_with_another_owner_is_never_started_stopped_or_removed(self):
        docker = FakeDocker(container_owner="another-run")
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.container_exists)
        self.assertFalse(any(call[1] in ("start", "stop", "rm") for call in docker.calls))
        self.assertFalse(self.summary()["cleanup_complete"])

    def test_image_with_another_owner_is_never_removed(self):
        docker = FakeDocker(image_owner="another-run")
        self.assertEqual(self.run_fake(docker), 2)
        self.assertFalse(any(call[1:3] == ["image", "rm"] for call in docker.calls))
        self.assertFalse(self.summary()["cleanup_complete"])

    def test_inspect_connection_failure_does_not_mean_resource_is_absent(self):
        docker = FakeDocker(inspect_failure_after_exec=True)
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.container_exists)
        self.assertFalse(any(call[1] in ("stop", "rm") for call in docker.calls))
        self.assertFalse(self.summary()["cleanup_complete"])

    def test_external_interruption_propagates_after_scoped_cleanup(self):
        docker = FakeDocker(failures={"exec": KeyboardInterrupt()})
        with self.assertRaises(KeyboardInterrupt):
            self.run_fake(docker)
        self.assertTrue(docker.collected)
        self.assertFalse(docker.container_exists)
        self.assertFalse(docker.image_exists)
        self.assertEqual(self.summary()["status"], "error")

    def test_cli_sigterm_cleans_own_resources_and_preserves_exit143(self):
        docker = FakeDocker()
        old_handler = signal.getsignal(signal.SIGTERM)

        def interrupt_exec(argv, **kwargs):
            value = docker(argv, **kwargs)
            if argv[1] == "exec":
                signal.raise_signal(signal.SIGTERM)
            return value

        argv = ["--repository", str(self.root), "verify", "--task", TASK_ID,
                "--submission", str(self.source), "--out", str(self.output)]
        with patch.object(runner.shutil, "which", return_value="/mock/docker"), \
                patch.object(runner.subprocess, "run", side_effect=interrupt_exec), \
                patch.object(runner.uuid, "uuid4", return_value=SimpleNamespace(hex="a" * 32)):
            with self.assertRaises(SystemExit) as stopped:
                runner.main(argv)
        self.assertEqual(stopped.exception.code, 143)
        self.assertEqual(signal.getsignal(signal.SIGTERM), old_handler)
        self.assertTrue(docker.collected)
        self.assertFalse(docker.container_exists)
        self.assertFalse(docker.image_exists)
        self.assertEqual(self.summary()["status"], "error")


class Evidence(RunnerFixture):
    def test_abnormal_exit_cannot_publish_a_plausible_metrics_score(self):
        docker = FakeDocker(verifier_rc=2)
        self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(docker.collected)
        self.assertNotIn("score", self.summary())
        self.assertEqual(self.summary()["status"], "error")

    def test_missing_metrics_is_an_execution_error(self):
        self.assertEqual(self.run_fake(FakeDocker(metrics=False)), 2)
        self.assertEqual(self.summary()["status"], "error")

    def test_nonfinite_or_invalid_metric_types_cannot_break_or_fake_the_summary(self):
        changes = [
            {"score": float("nan")}, {"score": float("inf")}, {"score": -0.1},
            {"score": 1.1}, {"score": True}, {"score": "0.7"},
            {"design_passed": "false"}, {"score_valid": 1}, {"evaluation_error": None},
            {"pipeline_completed": False}, {"score_is_lower_bound": "false"},
        ]
        for index, change in enumerate(changes):
            with self.subTest(change=change):
                output = self.root / f"invalid-output-{index}"
                docker = FakeDocker()
                docker.metrics.update(change)
                self.assertEqual(self.run_fake(docker, out=str(output)), 2)
                summary = json.loads((output / "summary.json").read_text())
                self.assertEqual(summary["status"], "error")
                self.assertNotIn("score", summary)
                self.assertTrue(summary["cleanup_complete"])


class SubmissionBoundary(RunnerFixture):
    def test_fractional_or_invalid_cpu_budgets_are_rejected_before_docker(self):
        for cpus in (0, -1, 0.5, 1.5, float("nan"), float("inf"), True):
            with self.subTest(cpus=cpus):
                docker = FakeDocker()
                with self.assertRaisesRegex(ValueError, "positive integer"):
                    self.run_fake(docker, cpus=cpus)
                self.assertEqual(docker.calls, [])
                self.assertFalse(self.output.exists())

    def test_only_formal_files_are_copied_and_archived_source_is_not_executed(self):
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker), 0)
        self.assertEqual(docker.submitted_files, ["README.md", "layout.gds", "src/design.py"])
        self.assertTrue(all(call[0] == "docker" for call in docker.calls))

    def test_missing_gds_or_source_is_left_for_the_verifier_to_grade(self):
        (self.source / "layout.gds").unlink()
        (self.source / "src/design.py").unlink()
        metrics = {"pipeline_completed": True, "score_valid": True, "evaluation_error": False,
                   "score": 0.0, "design_passed": False}
        docker = FakeDocker(verifier_rc=1, metrics=metrics)
        self.assertEqual(self.run_fake(docker), 1)
        self.assertEqual(docker.submitted_files, ["README.md"])
        self.assertEqual(self.summary()["score"], 0.0)

    def test_linked_source_directory_and_nested_source_file_are_rejected(self):
        linked = self.root / "submission-link"
        linked.symlink_to(self.source, target_is_directory=True)
        docker = FakeDocker()
        with self.assertRaisesRegex(ValueError, "regular directory"):
            self.run_fake(docker, submission=str(linked))
        self.assertFalse(docker.calls)
        (self.source / "src/linked.py").symlink_to(self.source / "src/design.py")
        self.assertEqual(self.run_fake(docker), 2)
        self.assertFalse(docker.calls)
        self.assertIn("link", self.summary()["reason"])

    def test_broken_artifact_link_is_rejected_without_following_it(self):
        (self.source / "README.md").unlink()
        (self.source / "README.md").symlink_to(self.root / "nonexistent-private-file")
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker), 2)
        self.assertFalse(docker.calls)

    def test_fifo_or_directory_disguised_as_gds_is_rejected(self):
        (self.source / "layout.gds").unlink()
        os.mkfifo(self.source / "layout.gds")
        docker = FakeDocker()
        self.assertEqual(self.run_fake(docker), 2)
        self.assertFalse(docker.calls)

    def test_output_inside_submission_or_a_link_is_rejected_before_making_files(self):
        output = self.source / "src/new-output"
        with self.assertRaisesRegex(ValueError, "outside"):
            self.run_fake(FakeDocker(), out=str(output))
        self.assertFalse(output.exists())
        linked = self.root / "linked-output"
        linked.symlink_to(self.root / "nonexistent-output", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "new"):
            self.run_fake(FakeDocker(), out=str(linked))

    def test_existing_output_is_not_overwritten(self):
        self.output.mkdir()
        sentinel = self.output / "keep"
        sentinel.write_text("original")
        with self.assertRaisesRegex(ValueError, "new"):
            self.run_fake(FakeDocker())
        self.assertEqual(sentinel.read_text(), "original")

    def test_a_file_swapped_to_a_link_after_stat_is_not_followed(self):
        outside = self.root / "outside.txt"
        outside.write_text("This must not enter the submission snapshot")
        original_open = os.open
        swapped = False

        def racing_open(path, flags, *args, **kwargs):
            nonlocal swapped
            if path == "design.py" and kwargs.get("dir_fd") is not None and not swapped:
                entry = self.source / "src/design.py"
                entry.unlink()
                entry.symlink_to(outside)
                swapped = True
            return original_open(path, flags, *args, **kwargs)

        docker = FakeDocker()
        with patch.object(runner.os, "open", side_effect=racing_open):
            self.assertEqual(self.run_fake(docker), 2)
        self.assertTrue(swapped)
        self.assertFalse(docker.calls)
        self.assertEqual(self.summary()["status"], "error")


if __name__ == "__main__":
    unittest.main()
