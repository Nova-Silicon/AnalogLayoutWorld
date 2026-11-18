#!/usr/bin/env python3
"""Check the 40-task release closure without Docker, a model, or network access."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import sys
import tomllib


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analoglayoutworld.runner import task_base_image

PDK_PREFIX = "/opt/analog-layout/pdks/sky130/"
MODELS = {
    "continuous": "sky130A/libs.tech/combined/continuous/sky130.lib.spice",
    "binned": "sky130A/libs.tech/ngspice/sky130.lib.spice",
}
POLICY = {
    "ALB_VERIFIER_NO_TIMEOUT": "1", "ALB_VERIFIER_BUDGET_SEC": "3300",
    "ALB_VERIFIER_RECOVER_COMPLETED": "1", "ALB_VERIFIER_SOLVER_POLICY": "auto",
}
REGISTRY_HOST = re.compile(rb"\b(registry(?:-[a-z0-9]+)?\.[a-z0-9.-]+)/", re.IGNORECASE)
PUBLIC_REGISTRIES = {b"registry.npmjs.org", b"registry-1.docker.io"}
TEXT_EXTENSIONS = {".py", ".json", ".toml", ".sh", ".md", ".txt", ".yaml", ".yml",
                   ".spice", ".spi", ".cir", ".tcl", ".tech", ".rst", ".drc", ".lvs"}


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def read_json(path: Path) -> dict:
    require(not path.is_symlink() and path.is_file(), "Missing regular JSON input: " + path.name)
    value = json.loads(path.read_text())
    require(isinstance(value, dict), "Expected JSON object: " + path.name)
    return value


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def relative_files(root: Path) -> dict[str, Path]:
    require(not root.is_symlink() and root.is_dir(), "Expected a regular directory")
    result = {}
    for path in root.rglob("*"):
        require(not path.is_symlink(), "Symbolic link in release files")
        if "__pycache__" in path.parts or path.suffix in (".pyc", ".pyo"):
            continue
        require(path.is_file() or path.is_dir(), "Non-regular release file")
        if path.is_file():
            result[path.relative_to(root).as_posix()] = path
    return result


def verify_file_map(directory: Path, expected: dict) -> None:
    require(isinstance(expected, dict), "File manifest must be an object")
    for name in expected:
        path = Path(name)
        require(not path.is_absolute() and ".." not in path.parts and str(path) == name,
                "Unsafe file manifest path")
    actual = relative_files(directory)
    require(actual.keys() == expected.keys(), "File set differs from its manifest")
    for name, path in actual.items():
        require(isinstance(expected[name], str) and digest(path) == expected[name],
                "File hash differs: " + name)


def load_helper(path: Path, module_name: str):
    specification = importlib.util.spec_from_file_location(module_name, path)
    helper = importlib.util.module_from_spec(specification)
    specification.loader.exec_module(helper)
    return helper


def check_task(root: Path, row: dict, canonical_tools: dict[str, str],
               canonical_deployment: dict[str, str] | None = None) -> None:
    task_id = row["task_id"]
    task = root / "tasks" / task_id
    for name in ("instruction.md", "task.toml", "environment/Dockerfile", "tests/test.sh",
                 "tests/Dockerfile", "tests/docker-compose.yaml"):
        path = task / name
        require(not path.is_symlink() and path.is_file() and bool(path.stat().st_size),
                "Missing regular task entry: " + name)
    settings = tomllib.loads((task / "task.toml").read_text())
    require(settings.get("schema_version") == "1.4", "Unsupported task TOML schema")
    require(settings.get("task", {}).get("name") == "analoglayoutworld/" + task_id,
            "Task TOML identity differs")
    metadata = settings.get("metadata", {})
    require(metadata.get("protocol") == "paper-v1" and metadata.get("number") == row["number"],
            "Task TOML protocol/number differs")
    require(settings.get("agent", {}).get("timeout_sec") == 10800,
            "Agent budget differs from paper-v1")
    require(settings.get("verifier", {}).get("timeout_sec") == 3600,
            "Outer verifier budget differs from paper-v1")
    require(settings.get("verifier", {}).get("environment_mode") == "separate",
            "Public release requires a fresh separate verifier container")
    require(all(settings.get("verifier", {}).get("env", {}).get(k) == v for k, v in POLICY.items()),
            "Verifier solver/budget policy differs")
    environment = settings.get("environment", {})
    require("docker_image" not in environment,
            "Thin Dockerfile task must not skip its build through docker_image")
    require(environment.get("cpus") == 6 and environment.get("memory_mb") == 32768
            and environment.get("gpus") == 0, "Unexpected default task resources")
    require(environment.get("workdir") == "/alb-workspace", "Task workdir differs")
    dockerfile = (task / "environment/Dockerfile").read_text()
    agent_base = task_base_image(task)
    sync = load_helper(ROOT / "scripts/sync_verifiers.py", "alw_sync_task_check")
    if canonical_deployment is None:
        canonical_deployment = sync.verifier_deployment(agent_base)
    for name, expected in canonical_deployment.items():
        require((task / "tests" / name).read_text() == expected,
                "Verifier deployment differs from canonical definition/base image: " + name)
    require(dockerfile == sync.agent_dockerfile(agent_base),
            "Agent Dockerfile must copy only the original workspace, without build metadata")
    require(not re.search(r"(?im)^\s*(?:COPY|ADD)\s+.*(?:\.\./|/tests\b|tests/)", dockerfile),
            "Task Dockerfile references trusted material outside its public context")
    public = relative_files(task / "environment")
    require(not any(name == "tests" or name.startswith(("tests/", "tools/eda/"))
                    or Path(name).name in ("tool_manifest.json", "input_manifest.json")
                    for name in public), "Trusted verifier material leaked into environment")
    expected_roots = {*sync.WORKSPACE_ROOT_FILES, "task", "Dockerfile", ".dockerignore"}
    require({Path(name).parts[0] for name in public} == expected_roots,
            "Public environment must contain exactly the original workspace and build metadata")
    require(all((task / "environment" / name).is_file() for name in sync.WORKSPACE_ROOT_FILES),
            "Original workspace guide or environment setup file is missing")

    private_manifest = read_json(task / "tests/input_manifest.json")
    verify_file_map(task / "tests/task", private_manifest.get("files"))
    verify_file_map(task / "environment/task", private_manifest.get("public_files"))
    identity = read_json(task / "tests/task/identity.json")
    require(identity.get("task_name") == task_id, "Trusted task identity differs")
    tools_manifest = read_json(task / "tests/tool_manifest.json")
    verify_file_map(task / "tests/tools", tools_manifest.get("files"))
    profile = row.get("runtime_profile")
    require(profile in MODELS, "Unknown task runtime model profile")
    require(tools_manifest["files"] == canonical_tools,
            "Task verifier copy differs from canonical source for this task/profile; run sync_verifiers.py --apply")
    runtime = read_json(task / "tests/tools/runtime.json")
    selected_model = PDK_PREFIX + MODELS[profile]
    require(runtime.get("paths", {}).get("model_lib") == selected_model,
            "Task runtime model selection differs")
    require(runtime.get("file_sha256", {}).get("model_lib")
            == digest(root / "docker/pdk/sky130" / MODELS[profile]),
            "Task model hash differs from packaged PDK")
    measurement = read_json(task / "tests/task/testbench/measurement.json")
    require(measurement.get("model_library", selected_model) == selected_model,
            "Trusted measurement model_library differs from task runtime")
    for content_root in (task / "environment", task / "tests"):
        for relative, path in relative_files(content_root).items():
            if path.suffix in TEXT_EXTENSIONS or path.name == "Dockerfile":
                data = path.read_bytes()
                require(b"/mnt/" not in data, "Host mount reference: " + relative)
                require(all(host.lower() in PUBLIC_REGISTRIES for host in REGISTRY_HOST.findall(data)),
                        "Unexpected registry host: " + relative)


def check_release(root: Path = ROOT, *, require_pinned_image: bool = False) -> dict:
    root = root.resolve(strict=True)
    for name in relative_files(root / "tests"):
        require(re.fullmatch(r"test_[a-z0-9_]+\.py", name),
                "Only self-contained Python tests belong in the release test directory: " + name)
    manifest = read_json(root / "configs/paper-v1/tasks.json")
    rows = manifest.get("tasks")
    require(manifest.get("protocol") == "paper-v1" and manifest.get("task_count") == 40
            and isinstance(rows, list) and len(rows) == 40, "Release must contain exactly 40 paper-v1 tasks")
    task_ids = [row.get("task_id") for row in rows]
    require(all(isinstance(x, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", x)
                for x in task_ids), "Invalid task ID")
    require(len(set(task_ids)) == 40 and [row.get("number") for row in rows] == list(range(1, 41)),
            "Task IDs/numbers must be unique and ordered 1–40")
    actual_tasks = {p.name for p in (root / "tasks").iterdir() if p.is_dir()}
    require(actual_tasks == set(task_ids), "Task directory set differs from the frozen release")
    pins = load_helper(root / "scripts/pin_base_image.py", "alw_image_pin_check")
    base_images = pins.deployment_defaults(root)
    base_image = next(iter(base_images.values()))
    if require_pinned_image:
        pins.pinned_reference(base_image)
    scoring = read_json(root / "src/analoglayoutworld/data/paper-v1.json")
    require(scoring.get("protocol_id") == "analoglayoutworld-paper-v1"
            and scoring.get("task_ids") == task_ids
            and set(scoring.get("task_parameters", {})) == set(task_ids),
            "Scoring parameters and task release differ")

    sync = load_helper(root / "scripts/sync_verifiers.py", "alw_sync_release_check")
    canonical_deployment = sync.verifier_deployment(base_image)
    pdk_verify = load_helper(root / "docker/pdk/verify.py", "alw_pdk_release_check")
    pdk = pdk_verify.verify(root / "docker/pdk/sky130")
    failures = []
    for row in rows:
        try:
            sources = sync.expected_tools(root, row["runtime_profile"], row["task_id"])
            canonical_tools = {name: digest(path) for name, path in sources.items()}
            check_task(root, row, canonical_tools, canonical_deployment)
        except (OSError, ValueError, KeyError, TypeError) as error:
            failures.append({"task_id": row["task_id"], "error": str(error)})
    return {
        "status": "passed" if not failures else "failed", "protocol": "paper-v1",
        "task_count": len(rows), "runtime_profiles": dict(Counter(row["runtime_profile"] for row in rows)),
        "base_image": base_image, "require_pinned_image": require_pinned_image,
        "base_image_reference_count": len(base_images),
        "pdk": pdk, "errors": failures,
        "scope": "Static task, verifier, runtime and PDK packaging closure; no Docker or EDA executed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--require-pinned-image", action="store_true",
                        help="Reject unpinned candidate defaults; does not test registry visibility")
    args = parser.parse_args()
    try:
        result = check_release(args.root, require_pinned_image=args.require_pinned_image)
    except (OSError, ValueError, KeyError, TypeError) as error:
        result = {"status": "failed", "error": str(error)}
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
