#!/usr/bin/env python3
"""Review or update all 80 agent/verifier Dockerfiles to one image digest."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analoglayoutworld.runner import task_base_image


def pinned_reference(value: str) -> str:
    """Validate syntax only; this cannot establish visibility or image contents."""
    repository = r"[a-z0-9]+(?:[._-][a-z0-9]+)*(?:/[a-z0-9]+(?:[._-][a-z0-9]+)*)*"
    registry = r"[a-z0-9]+(?:[.-][a-z0-9]+)+(?::[0-9]+)?"
    pattern = rf"{registry}/{repository}(?::[A-Za-z0-9_][A-Za-z0-9_.-]{{0,127}})?@sha256:[0-9a-f]{{64}}"
    if not re.fullmatch(pattern, value):
        raise ValueError("Use a full registry/repository@sha256:<64 lowercase hex> reference")
    return value


def task_defaults(root: Path) -> dict[str, str]:
    """Preserve the forty-task agent-default API used by maintainers."""
    manifest = json.loads((root / "configs/paper-v1/tasks.json").read_text())
    rows = manifest["tasks"]
    if manifest.get("task_count") != 40 or len(rows) != 40:
        raise ValueError("Image pinning requires the complete 40-task release")
    values = {}
    for row in rows:
        task_id = row["task_id"]
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", task_id) or task_id in values:
            raise ValueError("Invalid or duplicate task identity")
        task = root / "tasks" / task_id
        dockerfile = task / "environment/Dockerfile"
        if task.is_symlink() or dockerfile.is_symlink() or dockerfile.parent.is_symlink():
            raise ValueError("Task Dockerfile must not be a symbolic link")
        values[task_id] = task_base_image(task)
    if len(set(values.values())) != 1:
        raise ValueError("The 40 tasks have inconsistent base image defaults; review before pinning")
    return values


def dockerfile_default(path: Path) -> str:
    if path.is_symlink() or path.parent.is_symlink() or not path.is_file():
        raise ValueError("Verifier Dockerfile must be a regular file")
    text = path.read_text()
    values = re.findall(r"(?m)^ARG ALW_BASE_IMAGE=([^\s]+)\s*$", text)
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", values[0]):
        raise ValueError("Verifier Dockerfile must declare one literal ALW_BASE_IMAGE default")
    from_values = [value.strip() for value in re.findall(r"(?im)^[ \t]*FROM[ \t]+([^\r\n]*)$", text)]
    if from_values != ["${ALW_BASE_IMAGE}"]:
        raise ValueError("Verifier Dockerfile must have exactly one active FROM ${ALW_BASE_IMAGE}")
    return values[0]


def deployment_defaults(root: Path) -> dict[str, str]:
    """Require both roles in every task to share the same published base."""
    values = {}
    for task_id, image in task_defaults(root).items():
        values[f"tasks/{task_id}/environment/Dockerfile"] = image
        relative = f"tasks/{task_id}/tests/Dockerfile"
        values[relative] = dockerfile_default(root / relative)
    if len(set(values.values())) != 1:
        raise ValueError("The 80 agent/verifier Dockerfiles have inconsistent base image defaults; review before pinning")
    return values


def pin(root: Path, image: str, *, apply: bool = False) -> dict:
    image = pinned_reference(image)
    defaults = deployment_defaults(root)
    old = next(iter(defaults.values()))
    updates = []
    # Read and validate every target before writing any file.
    for relative in defaults:
        path = root / relative
        text = path.read_text()
        changed = re.sub(r"(?m)^ARG ALW_BASE_IMAGE=[^\r\n]*$",
                         "ARG ALW_BASE_IMAGE=" + image, text, count=1)
        if changed != text:
            updates.append((relative, path, changed))
    if apply:
        for _, path, text in updates:
            path.write_text(text)
    return {"mode": "apply" if apply else "dry-run", "old_base_image": old,
            "new_base_image": image,
            "changed_tasks": list(dict.fromkeys(Path(row[0]).parts[1] for row in updates)),
            "changed_dockerfiles": [row[0] for row in updates],
            "scope": "Source update only; no registry access, build, login, pull or push performed"}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--image", required=True, help="Verified registry manifest/index digest, not local image ID")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--apply", action="store_true", help="Write the reviewed pin into all 80 agent/verifier Dockerfiles")
    args = parser.parse_args(argv)
    try:
        print(json.dumps(pin(args.root, args.image, apply=args.apply), indent=2))
        return 0
    except (OSError, ValueError, KeyError, TypeError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
