#!/usr/bin/env python3
"""Check actual wheel contents, runtime assets and bundled license notices."""
from __future__ import annotations

import argparse
from email.parser import BytesParser
import json
from pathlib import Path, PurePosixPath
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def runtime_files() -> dict[str, Path]:
    src = ROOT / "src"
    files = {
        path.relative_to(src).as_posix(): path
        for package in ("analoglayoutworld", "eda", "analoglayoutworld_agents")
        for path in (src / package).rglob("*.py")
        if "__pycache__" not in path.parts
    }
    tasks = json.loads((ROOT / "configs/paper-v1/tasks.json").read_text())["tasks"]
    resources = ["analoglayoutworld/data/paper-v1.json", "eda/sky130_dummy_purge_20261103_v2.lvs"]
    resources.extend(f"eda/quality/annotations/{task['task_id']}.json" for task in tasks)
    files.update({name: src / name for name in resources})
    return files


def check_wheel(path: Path) -> dict:
    with zipfile.ZipFile(path) as wheel:
        names = wheel.namelist()
        if len(names) != len(set(names)):
            raise ValueError("Duplicate wheel entries")
        for name in names:
            member = PurePosixPath(name)
            if member.is_absolute() or ".." in member.parts or "\\" in name:
                raise ValueError("Unsafe wheel member path")
        metadata_paths = [name for name in names if name.endswith(".dist-info/METADATA")]
        if len(metadata_paths) != 1 or len(PurePosixPath(metadata_paths[0]).parts) != 2:
            raise ValueError("Expected one wheel distribution metadata file")
        distribution = metadata_paths[0].removesuffix("/METADATA")
        runtime = runtime_files()
        licenses = sorted((ROOT / "LICENSES").glob("*.txt"))
        licenses.extend(ROOT / name for name in ("LICENSE", "LICENSING.md", "THIRD_PARTY_NOTICES.md"))
        license_files = {source.relative_to(ROOT).as_posix(): source for source in licenses}
        files = dict(runtime)
        files.update({f"{distribution}/licenses/{name}": source for name, source in license_files.items()})
        expected = set(files) | {
            f"{distribution}/{name}" for name in ("METADATA", "WHEEL", "entry_points.txt", "RECORD")
        }
        unexpected = set(names) - expected
        missing = expected - set(names)
        if unexpected:
            raise ValueError("Unexpected wheel entries: " + ", ".join(sorted(unexpected)))
        if missing:
            raise ValueError("Missing wheel entries: " + ", ".join(sorted(missing)))
        for name, source in files.items():
            if wheel.read(name) != source.read_bytes():
                raise ValueError("Wheel content differs: " + name)
        metadata = BytesParser().parsebytes(wheel.read(metadata_paths[0]))
        if set(metadata.get_all("License-File", [])) != set(license_files):
            raise ValueError("License-File metadata differs from the release license files")
        if metadata.get_payload(decode=True) != (ROOT / "README.md").read_bytes():
            raise ValueError("Wheel description differs from README.md")
    return {"status": "passed", "wheel": path.name,
            "runtime_files": len(runtime), "license_files": len(licenses)}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheel", type=Path)
    args = parser.parse_args()
    try:
        result = check_wheel(args.wheel)
    except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Wheel check failed: {error}\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
