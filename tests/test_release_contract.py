"""Static release contract: task identity, budget, trusted inputs and tools.

These checks cover the inputs and tools built into each independent verifier image.
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import sys
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analoglayoutworld.scoring import TASK_IDS, task_parameters

try:
    from harbor.models.task.config import TaskConfig
    from harbor.models.task.paths import TaskPaths
    from harbor.models.task.verifier_mode import resolve_verifier_environment_definition
    from harbor.environments.definition import should_upload_environment_dir
except ImportError:
    TaskConfig = None


def regular_files(directory: Path) -> dict[str, Path]:
    """List regular inputs without including interpreter-generated caches."""
    found = {}
    for path in sorted(directory.rglob("*")):
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        if path.is_symlink():
            raise AssertionError(f"Release inputs must not be symlinks: {path.relative_to(ROOT)}")
        if path.is_file():
            found[path.relative_to(directory).as_posix()] = path
    return found


def digests(directory: Path) -> dict[str, str]:
    return {name: hashlib.sha256(path.read_bytes()).hexdigest()
            for name, path in regular_files(directory).items()}


class ReleaseContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = json.loads((ROOT / "configs/paper-v1/tasks.json").read_text())
        cls.rows = cls.manifest["tasks"]

    def test_exact_paper_task_set_order_numbering_and_configuration(self):
        self.assertEqual(self.manifest["protocol"], "paper-v1")
        self.assertEqual(self.manifest["task_count"], 40)
        self.assertEqual([row["task_id"] for row in self.rows], list(TASK_IDS))
        self.assertEqual([row["number"] for row in self.rows], list(range(1, 41)))
        self.assertEqual({path.name for path in (ROOT / "tasks").iterdir() if path.is_dir()},
                         set(TASK_IDS))
        for row in self.rows:
            task_id = row["task_id"]
            with self.subTest(task=task_id):
                self.assertEqual(Path(task_id).name, task_id)
                self.assertEqual(len(task_parameters(task_id)["quality_saturation"]), 3)
                base = ROOT / "tasks" / task_id
                for required in ("instruction.md", "task.toml", "environment/Dockerfile",
                                 "tests/Dockerfile", "tests/docker-compose.yaml",
                                 "tests/test.sh", "tests/input_manifest.json",
                                 "tests/tool_manifest.json"):
                    self.assertTrue((base / required).is_file(), required)
                config = tomllib.loads((base / "task.toml").read_text())
                self.assertEqual(config["task"]["name"], "analoglayoutworld/" + task_id,
                                 "Harbor task package names use the org/name form")
                self.assertEqual(config["metadata"]["protocol"], "paper-v1")
                self.assertEqual(config["metadata"]["number"], row["number"])

    def test_all_runtime_profiles_are_explicit_task_inputs(self):
        profiles = ROOT / "configs/paper-v1/runtime-profiles"
        binned_tasks = {
            "sky130-adb-ahuja-compensated-two-stage-load-range-pvt-layout",
            "sky130-adb-capless-ldo-1v0-20ma-pvt-layout",
            "sky130-adb-constant-gm-stable-gain-amplifier-pvt-layout",
            "sky130-adb-current-starved-ring-vco-pvt-layout",
            "sky130-adb-fd-sampling-feedback-ota-gain1-settling40ns-noise300uv-pvt-mc-layout",
            "sky130-adb-low-power-oscillator-2mhz-pvt-layout",
            "sky130-adb-tia-zt8k-bw750m-noise5p-sfdr70-power5m-pt-layout",
            "sky130-adb-two-stage-miller-opamp-gain70-ugb20-pm60-noise50uv-pvt-layout",
            "sky130-internet-ajc-rc-osc-layout",
        }
        expected_models = {
            "binned": (
                "/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice",
                "17c208a699228f5acb87bf59c09c22a4c4d3937b6766b4957737d34e8e075f64"),
            "continuous": (
                "/opt/analog-layout/pdks/sky130/sky130A/libs.tech/combined/continuous/sky130.lib.spice",
                "c7e9fe87ffc2685bc56da02f92cd48b1403a5e9da85cc7978027fb0ca347d581"),
        }
        used = set()
        for row in self.rows:
            profile = row["runtime_profile"]
            with self.subTest(task=row["task_id"]):
                self.assertEqual(Path(profile).name, profile)
                self.assertEqual(profile, "binned" if row["task_id"] in binned_tasks else "continuous",
                                 "Preserve each paper task's original model family")
                path = profiles / (profile + ".json")
                self.assertFalse(path.is_symlink())
                self.assertTrue(path.is_file())
                manifest = json.loads(path.read_text())
                self.assertEqual(manifest["schema_version"], 1)
                self.assertIs(manifest["inherit_image_runtime"], True)
                self.assertEqual(manifest["paths"], {"model_lib": expected_models[profile][0]})
                self.assertEqual(manifest["file_sha256"], {"model_lib": expected_models[profile][1]})
                self.assertEqual(manifest["execution"], {
                    "mode": "image", "output_roots": ["/alb-workspace", "/logs/verifier"]})
            used.add(profile)
        self.assertEqual(used, {"binned", "continuous"})
        self.assertEqual(used, {path.stem for path in profiles.glob("*.json")})

    def test_explicit_evaluation_budgets_and_no_prebuilt_image_override(self):
        expected_env = {"ALB_VERIFIER_NO_TIMEOUT": "1",
                        "ALB_VERIFIER_BUDGET_SEC": "3300",
                        "ALB_VERIFIER_RECOVER_COMPLETED": "1",
                        "ALB_VERIFIER_SOLVER_POLICY": "auto"}
        for task_id in TASK_IDS:
            with self.subTest(task=task_id):
                config = tomllib.loads((ROOT / "tasks" / task_id / "task.toml").read_text())
                self.assertEqual(config["agent"]["timeout_sec"], 10800)
                self.assertEqual(config["verifier"]["timeout_sec"], 3600)
                self.assertEqual(config["verifier"].get("environment_mode"), "separate")
                for name, value in expected_env.items():
                    self.assertEqual(config["verifier"]["env"].get(name), value, name)
                self.assertNotIn("docker_image", config["environment"],
                                 "A prebuilt base image must not bypass the task Dockerfile")
                self.assertEqual(config["environment"]["gpus"], 0)
                self.assertGreater(config["environment"]["cpus"], 0)
                self.assertGreater(config["environment"]["memory_mb"], 0)

    def test_agent_environment_has_no_trusted_grader_or_answer_materials(self):
        forbidden_directories = {"tools", "tests", "solution", "solutions", "answers",
                                 "golden", "submission", ".git", ".secrets"}
        forbidden_names = {"measurement.json", "adapter.py", "verify.py",
                           "input_manifest.json", "tool_manifest.json"}
        for task_id in TASK_IDS:
            environment = ROOT / "tasks" / task_id / "environment"
            with self.subTest(task=task_id):
                for relative, path in regular_files(environment).items():
                    parts = PurePosixPath(relative).parts
                    self.assertFalse(set(parts[:-1]) & forbidden_directories, relative)
                    self.assertNotIn(path.name, forbidden_names)
                    self.assertNotIn(path.suffix.lower(), {".gds", ".oas", ".pyc", ".pyo"})

    def test_all_private_and_public_input_manifests_match_regular_file_bytes(self):
        for task_id in TASK_IDS:
            base = ROOT / "tasks" / task_id
            manifest = json.loads((base / "tests/input_manifest.json").read_text())
            with self.subTest(task=task_id):
                self.assertEqual(manifest["schema_version"], 2)
                self.assertEqual(digests(base / "tests/task"), manifest["files"])
                public = regular_files(base / "environment/task")
                for name, expected in manifest["public_files"].items():
                    relative = PurePosixPath(name)
                    self.assertFalse(relative.is_absolute())
                    self.assertNotIn("..", relative.parts)
                    self.assertNotIn("\\", name)
                    self.assertIn(name, public)
                    self.assertEqual(hashlib.sha256(public[name].read_bytes()).hexdigest(), expected)
                self.assertEqual(set(public), set(manifest["public_files"]),
                                 "All public task inputs must be manifest-bound")

    def test_public_and_trusted_dut_are_byte_identical(self):
        for task_id in TASK_IDS:
            base = ROOT / "tasks" / task_id
            with self.subTest(task=task_id):
                public = base / "environment/task/circuit.spice"
                trusted = base / "tests/task/circuit.spice"
                self.assertTrue(public.is_file())
                self.assertTrue(trusted.is_file())
                self.assertEqual(public.read_bytes(), trusted.read_bytes())
                # Some tasks publish an auxiliary LVS reference that the
                # verifier derives itself. When both copies are supplied,
                # they must agree; an optional public helper is not a DUT.
                public_reference = base / "environment/task/lvs_reference.spice"
                trusted_reference = base / "tests/task/lvs_reference.spice"
                if trusted_reference.is_file():
                    self.assertTrue(public_reference.is_file())
                    self.assertEqual(public_reference.read_bytes(), trusted_reference.read_bytes())

    def test_trusted_constraints_do_not_supply_precomputed_device_area(self):
        old_area_fields = {"area_utilization_definition", "fixed_effective_area_um2",
                           "effective_area_basis", "effective_area_devices"}
        for task_id in TASK_IDS:
            with self.subTest(task=task_id):
                path = ROOT / "tasks" / task_id / "tests/task/constraints.json"
                self.assertEqual(old_area_fields.intersection(json.loads(path.read_text())), set(),
                                 "Device area is measured from the submitted layout's LVS evidence")

    def test_every_task_verifier_matches_the_single_canonical_source(self):
        annotation_root = ROOT / "src/eda/quality/annotations"
        self.assertEqual(set(regular_files(annotation_root)), {f"{task_id}.json" for task_id in TASK_IDS})
        common = {}
        for package in ("eda", "analoglayoutworld"):
            for name, path in regular_files(ROOT / "src" / package).items():
                if package == "analoglayoutworld" and name == "runner.py":
                    continue
                if not path.is_relative_to(annotation_root) and path.suffix in (".py", ".json", ".lvs"):
                    common[f"{package}/{name}"] = hashlib.sha256(path.read_bytes()).hexdigest()
        for row in self.rows:
            task_id = row["task_id"]
            base = ROOT / "tasks" / task_id / "tests"
            profile = ROOT / "configs/paper-v1/runtime-profiles" / (row["runtime_profile"] + ".json")
            expected = {**common, "runtime.json": hashlib.sha256(profile.read_bytes()).hexdigest()}
            annotation = annotation_root / f"{task_id}.json"
            expected[annotation.relative_to(ROOT / "src").as_posix()] = hashlib.sha256(annotation.read_bytes()).hexdigest()
            manifest = json.loads((base / "tool_manifest.json").read_text())
            with self.subTest(task=task_id):
                self.assertEqual(json.loads(annotation.read_text())["task"], task_id)
                self.assertEqual(manifest["schema_version"], 2)
                for label, actual in (("manifest", manifest["files"]),
                                      ("tool bytes", digests(base / "tools"))):
                    changed = sorted(name for name in set(actual) | set(expected)
                                     if actual.get(name) != expected.get(name))
                    self.assertFalse(changed, f"Stale or unexpected {label}: {changed}")

    def test_all_forty_verifier_deployments_match_one_canonical_template_and_base(self):
        spec = importlib.util.spec_from_file_location("alw_sync_contract", ROOT / "scripts/sync_verifiers.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        from analoglayoutworld.runner import task_base_image

        for row in self.rows:
            task = ROOT / "tasks" / row["task_id"]
            with self.subTest(task=row["task_id"]):
                expected = sync.verifier_deployment(task_base_image(task))
                self.assertEqual(set(expected), {"Dockerfile", "docker-compose.yaml"})
                for name, content in expected.items():
                    self.assertEqual((task / "tests" / name).read_text(), content)
                self.assertIn("COPY environment/task/ /alb-workspace/task/\nCOPY tests/ /tests/\n", expected["Dockerfile"])
                self.assertNotIn("COPY environment/ /alb-workspace/", expected["Dockerfile"])
                self.assertIn("context: ..\n      dockerfile: tests/Dockerfile\n", expected["docker-compose.yaml"])
                self.assertIn("network_mode: none\n", expected["docker-compose.yaml"])

    def test_agent_build_copies_exact_original_workspace_without_build_metadata(self):
        spec = importlib.util.spec_from_file_location("alw_workspace_contract", ROOT / "scripts/sync_verifiers.py")
        sync = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(sync)
        from analoglayoutworld.runner import task_base_image

        for row in self.rows:
            task = ROOT / "tasks" / row["task_id"]
            with self.subTest(task=row["task_id"]):
                actual = (task / "environment/Dockerfile").read_text()
                self.assertEqual(actual, sync.agent_dockerfile(task_base_image(task)))
                self.assertNotIn("COPY . ", actual)
                self.assertNotIn("COPY Dockerfile ", actual)
                self.assertNotIn("COPY .dockerignore ", actual)
                self.assertIn("COPY task/ /alb-workspace/task/\n", actual)
                self.assertEqual(
                    {path.name for path in (task / "environment").iterdir()},
                    {*sync.WORKSPACE_ROOT_FILES, "task", "Dockerfile", ".dockerignore"},
                )

    @unittest.skipIf(TaskConfig is None, "Optional Harbor dependency is not installed")
    def test_task_configs_load_with_harbor(self):
        for task_id in TASK_IDS:
            with self.subTest(task=task_id):
                path = ROOT / "tasks" / task_id / "task.toml"
                config = TaskConfig.model_validate(tomllib.loads(path.read_text()))
                self.assertEqual(config.agent.timeout_sec, 10800)
                self.assertEqual(config.verifier.timeout_sec, 3600)
                self.assertEqual(config.verifier.environment_mode, "separate")
                self.assertFalse(should_upload_environment_dir(
                    path.parent / "environment", docker_image=config.environment.docker_image),
                    "Harbor must not upload build metadata after the filtered image build")

    @unittest.skipIf(TaskConfig is None, "Optional Harbor dependency is not installed")
    def test_harbor_uses_bundled_tests_and_inherits_resources_workdir_and_environment(self):
        for task_id in TASK_IDS:
            task = ROOT / "tasks" / task_id
            with self.subTest(task=task_id):
                config = TaskConfig.model_validate(tomllib.loads((task / "task.toml").read_text()))
                definition = resolve_verifier_environment_definition(config, TaskPaths(task))
                self.assertIsNotNone(definition)
                self.assertEqual(definition.directory, task / "tests")
                self.assertTrue(definition.bundled_tests)
                self.assertEqual(definition.config.model_dump(), config.environment.model_dump())
                self.assertIsNot(definition.config, config.environment)


if __name__ == "__main__":
    unittest.main()
