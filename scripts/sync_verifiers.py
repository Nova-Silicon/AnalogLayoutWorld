#!/usr/bin/env python3
"""Materialize the canonical verifier into self-contained Harbor task bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analoglayoutworld.runner import task_base_image

WORKSPACE_ROOT_FILES = (
    "GUIDE.md", "GUIDE.zh-CN.md", "DEVICE_API.md", "DEVICE_API.zh-CN.md", "eda_env.sh",
)


def workspace_copy_instructions(prefix: str = "") -> str:
    """Copy the original task workspace, excluding container build metadata."""
    sources = " ".join(prefix + name for name in WORKSPACE_ROOT_FILES)
    return (f"COPY {sources} /alb-workspace/\n"
            f"COPY {prefix}task/ /alb-workspace/task/\n")


def agent_dockerfile(base_image: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", base_image):
        raise ValueError("Agent deployment requires a literal base image reference")
    return (f"ARG ALW_BASE_IMAGE={base_image}\nFROM ${{ALW_BASE_IMAGE}}\n"
            "USER root\nWORKDIR /alb-workspace\n"
            + workspace_copy_instructions()
            + 'ENTRYPOINT []\nCMD ["sleep", "infinity"]\n')


def verifier_deployment(base_image: str) -> dict[str, str]:
    """Canonical Docker-only deployment; Harbor inherits task resources/env."""
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", base_image):
        raise ValueError("Verifier deployment requires a literal base image reference")
    return {
        "Dockerfile": (
            f"ARG ALW_BASE_IMAGE={base_image}\nFROM ${{ALW_BASE_IMAGE}}\n"
            "USER root\nWORKDIR /alb-workspace\n"
            + workspace_copy_instructions("environment/")
            + 'COPY tests/ /tests/\nENTRYPOINT []\nCMD ["sleep", "infinity"]\n'
        ),
        "docker-compose.yaml": (
            "services:\n  main:\n    build:\n      context: ..\n"
            "      dockerfile: tests/Dockerfile\n    network_mode: none\n"
            "    cap_drop:\n      - NET_RAW\n      - NET_ADMIN\n"
            "    security_opt:\n      - no-new-privileges:true\n"
        ),
    }


def files(root: Path) -> dict[str, Path]:
    result = {}
    for p in sorted(root.rglob("*")):
        if "__pycache__" in p.parts or p.suffix in (".pyc", ".pyo"):
            continue
        if p.is_symlink():
            raise ValueError(f"Symlinks are not verifier inputs: {p.relative_to(root)}")
        if p.is_file():
            result[p.relative_to(root).as_posix()] = p
    return result


def digest(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def expected_tools(root: Path, runtime_profile: str, task_id: str) -> dict[str, Path]:
    if Path(runtime_profile).name != runtime_profile:
        raise ValueError("Invalid runtime profile")
    runtime = root / "configs/paper-v1/runtime-profiles" / (runtime_profile + ".json")
    annotation = f"eda/quality/annotations/{task_id}.json"
    result = {"runtime.json": runtime}
    for package in ("eda", "analoglayoutworld"):
        for name, p in files(root / "src" / package).items():
            relative = f"{package}/{name}"
            if relative == "analoglayoutworld/runner.py":
                continue  # The Docker launcher runs on the user's host.
            if relative.startswith("eda/quality/annotations/") and relative != annotation:
                continue
            if p.suffix in (".py", ".json", ".lvs"):
                result[relative] = p
    if annotation not in result:
        raise ValueError(f"Missing canonical quality annotation for {task_id}")
    return result


def sync(root: Path = ROOT, *, apply: bool = False) -> list[str]:
    manifest = json.loads((root / "configs/paper-v1/tasks.json").read_text())
    changes = []
    for row in manifest["tasks"]:
        task_id = row["task_id"]
        if Path(task_id).name != task_id:
            raise ValueError("Invalid task id")
        sources = expected_tools(root, row["runtime_profile"], task_id)
        expected = {name: digest(p) for name, p in sources.items()}
        task = root / "tasks" / task_id
        base = task / "tests"
        if task.is_symlink() or base.is_symlink():
            raise ValueError("Refusing symlinked task/verifier destination")
        deployment = verifier_deployment(task_base_image(task))
        deployment_changes = {}
        for name, content in deployment.items():
            path = base / name
            if path.is_symlink():
                raise ValueError("Refusing symlinked verifier deployment")
            if not path.is_file() or path.read_text() != content:
                deployment_changes[name] = content
        destination = base / "tools"
        actual = {n: digest(p) for n, p in files(destination).items()} if destination.exists() else {}
        desired = {"schema_version": 2,
                   "basis": "Self-contained paper-v1 verifier, deployed after the agent finishes.",
                   "files": expected}
        old = json.loads((base / "tool_manifest.json").read_text()) if (base / "tool_manifest.json").is_file() else None
        tools_changed = actual != expected or old != desired
        if tools_changed or deployment_changes:
            changes.append(task_id)
            if apply:
                if tools_changed:
                    if destination.is_symlink():
                        raise ValueError("Refusing symlinked verifier destination")
                    if destination.exists():
                        shutil.rmtree(destination)
                    destination.mkdir(parents=True)
                    for name, p in sources.items():
                        target = destination / name
                        target.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(p, target)
                    (base / "tool_manifest.json").write_text(json.dumps(desired, indent=2, sort_keys=True) + "\n")
                for name, content in deployment_changes.items():
                    (base / name).write_text(content)
    return changes


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true", help="Regenerate task tools and verifier deployment definitions")
    args = parser.parse_args()
    changed = sync(apply=args.apply)
    print(json.dumps({"mode": "apply" if args.apply else "check", "changed_tasks": changed}))
    return 0 if args.apply or not changed else 1


if __name__ == "__main__":
    raise SystemExit(main())

