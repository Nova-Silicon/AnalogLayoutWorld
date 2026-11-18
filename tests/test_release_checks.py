"""Negative checks for publication manifests and per-task runtime selections."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import zipfile


ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("alw_release_checks", ROOT / "scripts/check_release.py")
checks = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checks)


class WheelContents(unittest.TestCase):
    def test_extra_packaged_data_is_rejected_even_inside_allowed_directories(self):
        checker = checks.load_helper(ROOT / "scripts/check_wheel.py", "alw_wheel_checks")
        distribution = "analoglayoutworld-1.0.dist-info"
        for name in ("eda/data.json.gz", "eda/quality/annotations/extra.json",
                     f"{distribution}/extra.json"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "example.whl"
                with zipfile.ZipFile(path, "w") as wheel:
                    wheel.writestr(f"{distribution}/METADATA", b"")
                    wheel.writestr(name, b"")
                with self.assertRaisesRegex(ValueError, "Unexpected wheel entries"):
                    checker.check_wheel(path)


class TaskClosure(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="alw-release-check-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.row = {"task_id": "sky130-example-layout", "number": 1,
                    "runtime_profile": "continuous"}
        self.task = self.root / "tasks" / self.row["task_id"]
        model = self.root / "docker/pdk/sky130" / checks.MODELS["continuous"]
        model.parent.mkdir(parents=True)
        model.write_text("* fixed model fixture\n")
        for path, contents in {
            "instruction.md": "Create the required physical layout.\n",
            "environment/Dockerfile": "ARG ALW_BASE_IMAGE=example:fixed\nFROM ${ALW_BASE_IMAGE}\nCOPY . /alb-workspace/\n",
            "environment/task/circuit.spice": ".subckt example a b\n.ends\n",
            "tests/test.sh": "#!/bin/sh\nexit 0\n",
            "tests/task/circuit.spice": ".subckt example a b\n.ends\n",
            "tests/task/identity.json": json.dumps({"task_name": self.row["task_id"]}),
            "tests/task/testbench/measurement.json": json.dumps({
                "model_library": checks.PDK_PREFIX + checks.MODELS["continuous"]}),
            "tests/tools/runtime.json": json.dumps({
                "paths": {"model_lib": checks.PDK_PREFIX + checks.MODELS["continuous"]},
                "file_sha256": {"model_lib": checks.digest(model)},
            }),
        }.items():
            target = self.task / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(contents)
        self.config = self.task / "task.toml"
        self.config.write_text('''schema_version="1.4"
[task]
name="analoglayoutworld/sky130-example-layout"
[metadata]
protocol="paper-v1"
number=1
[agent]
timeout_sec=10800
[verifier]
environment_mode="separate"
timeout_sec=3600
[verifier.env]
ALB_VERIFIER_NO_TIMEOUT="1"
ALB_VERIFIER_BUDGET_SEC="3300"
ALB_VERIFIER_RECOVER_COMPLETED="1"
ALB_VERIFIER_SOLVER_POLICY="auto"
[environment]
cpus=6
memory_mb=32768
gpus=0
workdir="/alb-workspace"
''')
        sync = checks.load_helper(ROOT / "scripts/sync_verifiers.py", "alw_sync_fixture")
        (self.task / "environment/Dockerfile").write_text(sync.agent_dockerfile("example:fixed"))
        (self.task / "environment/.dockerignore").write_text("work/\nsubmission/\n")
        for name in sync.WORKSPACE_ROOT_FILES:
            (self.task / "environment" / name).write_text("# original workspace fixture\n")
        for name, contents in sync.verifier_deployment("example:fixed").items():
            (self.task / "tests" / name).write_text(contents)
        self.refresh_manifests()
        self.canonical = self.file_hashes(self.task / "tests/tools")

    @staticmethod
    def file_hashes(root: Path):
        return {name: checks.digest(path) for name, path in checks.relative_files(root).items()}

    def refresh_manifests(self):
        (self.task / "tests/input_manifest.json").write_text(json.dumps({
            "files": self.file_hashes(self.task / "tests/task"),
            "public_files": self.file_hashes(self.task / "environment/task"),
        }))
        (self.task / "tests/tool_manifest.json").write_text(json.dumps({
            "files": self.file_hashes(self.task / "tests/tools"),
        }))

    def test_valid_task_has_no_runtime_or_build_context_gap(self):
        checks.check_task(self.root, self.row, self.canonical)

    def test_host_specific_task_references_are_rejected(self):
        guide = self.task / "environment/GUIDE.md"
        for example, reason in (("/mnt/example/design", "Host mount reference"),
                                ("registry.build.example/team/image:v1", "Unexpected registry host")):
            with self.subTest(example=example):
                guide.write_text(example)
                with self.assertRaisesRegex(ValueError, reason):
                    checks.check_task(self.root, self.row, self.canonical)

    def test_hidden_old_verifier_budget_is_rejected(self):
        self.config.write_text(self.config.read_text().replace("timeout_sec=3600", "timeout_sec=1800"))
        with self.assertRaisesRegex(ValueError, "Outer verifier budget"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_verifier_base_and_canonical_deployment_cannot_drift(self):
        for name, old, new in (
            ("Dockerfile", "ARG ALW_BASE_IMAGE=example:fixed", "ARG ALW_BASE_IMAGE=example:other"),
            ("Dockerfile", "COPY tests/ /tests/", "# COPY tests/ /tests/"),
            ("Dockerfile", "COPY environment/task/ /alb-workspace/task/", "COPY environment/ /alb-workspace/"),
            ("docker-compose.yaml", "context: ..", "context: ."),
            ("docker-compose.yaml", "network_mode: none", "network_mode: host"),
            ("docker-compose.yaml", "      - NET_RAW\n", ""),
            ("docker-compose.yaml", "      - no-new-privileges:true\n", ""),
            ("docker-compose.yaml", "    network_mode: none", "    cpus: 1\n    network_mode: none"),
        ):
            path = self.task / "tests" / name
            original = path.read_text()
            with self.subTest(name=name, old=old):
                path.write_text(original.replace(old, new))
                with self.assertRaisesRegex(ValueError, "canonical definition/base image"):
                    checks.check_task(self.root, self.row, self.canonical)
            path.write_text(original)

    def test_deployment_sync_is_dry_run_safe_idempotent_and_keeps_tools_unchanged(self):
        sync = checks.load_helper(ROOT / "scripts/sync_verifiers.py", "alw_sync_generation_test")
        profile = self.root / "configs/paper-v1/runtime-profiles/continuous.json"
        profile.parent.mkdir(parents=True)
        profile.write_text((self.task / "tests/tools/runtime.json").read_text())
        (profile.parent.parent / "tasks.json").write_text(json.dumps({"tasks": [self.row]}))
        for package in ("eda", "analoglayoutworld", "analoglayoutworld_agents"):
            source = self.root / "src" / package / "example.py"
            source.parent.mkdir(parents=True)
            source.write_text("# " + package + " fixture\n")
        annotations = self.root / "src/eda/quality/annotations"
        annotations.mkdir(parents=True)
        own_annotation = self.row["task_id"] + ".json"
        (annotations / own_annotation).write_text(json.dumps({"task": self.row["task_id"]}))
        (annotations / "other-task.json").write_text(json.dumps({"task": "other-task"}))
        sync.sync(self.root, apply=True)
        bundled_annotations = self.task / "tests/tools/eda/quality/annotations"
        self.assertEqual({p.name for p in bundled_annotations.iterdir()}, {own_annotation})
        expected = sync.verifier_deployment("example:fixed")
        before = self.file_hashes(self.task)
        tools_stat = (self.task / "tests/tools/eda/example.py").stat().st_mtime_ns
        for name in expected:
            (self.task / "tests" / name).unlink()
            del before["tests/" + name]
        self.assertEqual(sync.sync(self.root), [self.row["task_id"]])
        self.assertFalse((self.task / "tests/Dockerfile").exists())
        self.assertEqual(sync.sync(self.root, apply=True), [self.row["task_id"]])
        after = self.file_hashes(self.task)
        self.assertEqual({name: after[name] for name in before}, before)
        self.assertEqual(set(after) - set(before), {"tests/Dockerfile", "tests/docker-compose.yaml"})
        self.assertEqual((self.task / "tests/tools/eda/example.py").stat().st_mtime_ns, tools_stat)
        self.assertEqual(sync.sync(self.root), [])
        self.assertFalse(any("analoglayoutworld_agents" in name for name in after))

    def test_missing_task_annotation_cannot_produce_a_verifier_bundle(self):
        sync = checks.load_helper(ROOT / "scripts/sync_verifiers.py", "alw_sync_missing_annotation")
        with self.assertRaisesRegex(ValueError, "Missing canonical quality annotation"):
            sync.expected_tools(self.root, self.row["runtime_profile"], self.row["task_id"])

    def test_prebuilt_image_must_not_silently_skip_thin_dockerfile(self):
        self.config.write_text(self.config.read_text().replace(
            "[environment]\n", '[environment]\ndocker_image="example:base"\n'))
        with self.assertRaisesRegex(ValueError, "skip its build"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_commented_from_or_copy_cannot_pass_as_an_active_build_instruction(self):
        path = self.task / "environment/Dockerfile"
        original = path.read_text()
        for replacement in [original.replace("FROM ${ALW_BASE_IMAGE}",
                "# Previous: FROM ${ALW_BASE_IMAGE}\nFROM ubuntu:22.04"),
                original.replace("COPY task/ /alb-workspace/task/", "# COPY task/ /alb-workspace/task/")]:
            with self.subTest(replacement=replacement):
                path.write_text(replacement)
                with self.assertRaises(ValueError):
                    checks.check_task(self.root, self.row, self.canonical)

    def test_whole_build_context_must_not_be_copied_to_agent_workspace(self):
        path = self.task / "environment/Dockerfile"
        original = path.read_text()
        path.write_text(original.replace("COPY task/ /alb-workspace/task/", "COPY . /alb-workspace/"))
        with self.assertRaisesRegex(ValueError, "without build metadata"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_unregistered_root_files_and_missing_original_guides_are_rejected(self):
        extra = self.task / "environment/builder-notes.md"
        extra.write_text("# build-only note\n")
        with self.assertRaisesRegex(ValueError, "exactly the original workspace"):
            checks.check_task(self.root, self.row, self.canonical)
        extra.unlink()
        (self.task / "environment/GUIDE.md").unlink()
        with self.assertRaisesRegex(ValueError, "original workspace"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_re_signed_task_tool_copy_still_must_match_canonical_source(self):
        (self.task / "tests/tools/extra.py").write_text("# arbitrary verifier extension\n")
        self.refresh_manifests()
        with self.assertRaisesRegex(ValueError, "canonical source"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_re_signed_measurement_cannot_change_a_tasks_model_set(self):
        path = self.task / "tests/task/testbench/measurement.json"
        path.write_text(json.dumps({"model_library": checks.PDK_PREFIX + checks.MODELS["binned"]}))
        self.refresh_manifests()
        with self.assertRaisesRegex(ValueError, "measurement model_library"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_an_extra_public_task_file_cannot_escape_the_public_projection(self):
        (self.task / "environment/task/private-grader.py").write_text("# unexpected\n")
        with self.assertRaisesRegex(ValueError, "File set differs"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_trusted_bundle_must_not_be_copied_into_public_environment(self):
        leaked = self.task / "environment/tests/test.sh"
        leaked.parent.mkdir()
        leaked.write_text("# trusted verifier\n")
        with self.assertRaisesRegex(ValueError, "leaked into environment"):
            checks.check_task(self.root, self.row, self.canonical)

    def test_symlinks_and_unsafe_manifest_paths_are_rejected(self):
        linked = self.task / "environment/task/alias"
        linked.symlink_to(self.task / "tests/task/identity.json")
        with self.assertRaisesRegex(ValueError, "Symbolic"):
            checks.relative_files(self.task / "environment")
        with self.assertRaisesRegex(ValueError, "Unsafe"):
            checks.verify_file_map(self.task / "tests/task", {"../other.json": "0" * 64})


if __name__ == "__main__":
    unittest.main()
