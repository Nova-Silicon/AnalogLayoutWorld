#!/usr/bin/env python3
"""Verify the vendored SKY130 runtime without importing EDA packages."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys


def verify(root: Path) -> dict:
    root = root.resolve(strict=True)
    manifest_path = root / "asset-manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("Manifest must be a regular file")
    manifest = json.loads(manifest_path.read_text())
    if manifest.get("schema") != "analoglayoutworld-sky130-runtime-v1":
        raise ValueError("Unsupported SKY130 asset schema")
    entries = manifest.get("files")
    if not isinstance(entries, dict) or not entries:
        raise ValueError("Asset manifest is empty")
    actual = {}
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ValueError("Symbolic links are forbidden in SKY130 runtime assets")
        if path.is_file() and path != manifest_path:
            actual[str(path.relative_to(root))] = path
        elif not path.is_file() and not path.is_dir():
            raise ValueError("Non-regular runtime asset")
    if actual.keys() != entries.keys():
        missing = sorted(entries.keys() - actual.keys())
        extra = sorted(actual.keys() - entries.keys())
        raise ValueError(f"Asset file set differs: missing={missing[:5]}, extra={extra[:5]}")
    total = 0
    for name, expected in entries.items():
        path = Path(name)
        if path.is_absolute() or ".." in path.parts or str(path) != name:
            raise ValueError("Unsafe asset manifest path")
        content = actual[name].read_bytes()
        if expected != {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest()}:
            raise ValueError(f"Asset hash or size differs: {name}")
        total += len(content)
    if manifest.get("asset_file_count") != len(actual) or manifest.get("asset_bytes") != total:
        raise ValueError("Asset manifest totals differ")
    return {"verified": True, "files": len(actual), "bytes": total,
            "runtime_prefix": manifest.get("runtime_prefix")}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent / "sky130")
    args = parser.parse_args()
    try:
        print(json.dumps(verify(args.root), indent=2))
    except (OSError, ValueError) as error:
        print(f"SKY130 verification failed: {error}", file=sys.stderr)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
