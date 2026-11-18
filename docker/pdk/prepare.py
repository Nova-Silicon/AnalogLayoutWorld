#!/usr/bin/env python3
"""Assemble the pinned, redistributable SKY130 runtime from explicit sources.

This developer utility is not part of Docker's network path: the reviewed
runtime tree is vendored beside this script. All input directories are explicit;
no developer-machine paths, credentials or Git configuration are copied.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile


PREFIX = "/opt/analog-layout/pdks/sky130"
PCELLS_COMMIT = "5c7b9ba5f13b5411e53bbb5e35ed3db4f4e79986"
OPEN_PDKS_COMMIT = "0ec4fa67eade28cd0a4352c04df981840809427b"
MAGIC_FILES = ("sky130A.magicrc", "sky130A.tech", "sky130A.tcl",
               "sky130A-GDS.tech", "sky130A-BindKeys")
SOURCES = {
    "pcells": {
        "repository": "https://github.com/gdsfactory/skywater130",
        "commit": PCELLS_COMMIT,
        "selection": ["LICENSE", "sky130/"],
        "license": "MIT",
        "modifications": "none",
    },
    "klayout_decks": {
        "repository": "https://github.com/fossi-foundation/sky130_klayout_pdk",
        "commit": "4ea0975391feacbdac697bf07029d8908d292613",
        "selection": ["sky130A_mr.drc", "sky130.lvs"],
        "licenses": {"sky130A_mr.drc": "GPL-3.0", "sky130.lvs": "Apache-2.0"},
        "modifications": "none",
    },
    "magic_technology": {
        "repository": "https://github.com/RTimothyEdwards/open_pdks",
        "commit": OPEN_PDKS_COMMIT,
        "selection": list(MAGIC_FILES),
        "modifications": "Only the fallback PDK_ROOT in sky130A.magicrc and sky130A.tcl is relocated to the installed prefix.",
        "license_file": "licenses/open-pdks-LICENSE",
    },
    "continuous_models": {
        "repository": "https://github.com/chipfoundry/volare",
        "release": "sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b",
        "entry": "sky130A/libs.tech/combined/continuous/sky130.lib.spice",
        "assets": [
            {
                "url": "https://github.com/chipfoundry/volare/releases/download/sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b/common.tar.zst",
                "sha256": "8a7f06212c6d9fa5a1da6145f559f48a903434a5c5b6cd5352363700b6cadb94",
            },
            {
                "url": "https://github.com/chipfoundry/volare/releases/download/sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b/sky130_fd_pr.tar.zst",
                "sha256": "dcb49c7450dfb55c91ce315d258563895df1ed75d4a9090064aade8290030a87",
            },
        ],
        "license": "Apache-2.0",
        "modifications": "none; complete recursive include closure across every declared corner",
    },
    "binned_models": {
        "repository": "https://github.com/chipfoundry/volare",
        "release": "sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b",
        "entry": "sky130A/libs.tech/ngspice/sky130.lib.spice",
        "release_assets": "The same common.tar.zst and sky130_fd_pr.tar.zst assets recorded under continuous_models",
        "license": "Apache-2.0",
        "modifications": "none; recursive include closure preserves libs.tech and libs.ref relative paths",
    },
    "netgen_setup": {
        "repository": "https://github.com/RTimothyEdwards/open_pdks",
        "commit": OPEN_PDKS_COMMIT,
        "template": "sky130/netgen/sky130_setup.tcl",
        "preprocessor": "common/preproc.py",
        "defines": ["TECHNAME=sky130A", "METAL5", "MIM", "REDISTRIBUTION"],
        "license_file": "licenses/open-pdks-LICENSE",
    },
    "process_documentation": {
        "repository": "https://github.com/google/skywater-pdk",
        "commit": "7198cf647113f56041e02abf3eb623692820c5e1",
        "license": "Apache-2.0",
        "selection": "Original rule/device RST, CSV/TSV and local figures used by the offline reference subset",
        "modifications": "none",
    },
}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def model_closure(entry: Path, root: Path) -> tuple[list[Path], list[dict]]:
    """Resolve literal .include/.inc and external .lib references, failing closed."""
    root = root.resolve(strict=True)
    pending = [entry.resolve(strict=True)]
    seen: set[Path] = set()
    edges = []
    while pending:
        path = pending.pop()
        path.relative_to(root)
        if path in seen:
            continue
        if path.is_symlink() or not path.is_file():
            raise ValueError("Models must be regular files")
        seen.add(path)
        for line_number, line in enumerate(path.read_text().splitlines(), 1):
            if not re.match(r"^\s*\.(inc|include|lib)\b", line, re.IGNORECASE):
                continue
            words = shlex.split(line, comments=False)
            if words[0].lower() == ".lib" and len(words) == 2:
                continue
            if len(words) < 2 or any(c in words[1] for c in "${}"):
                raise ValueError("Unsupported dynamic SPICE model reference")
            reference = Path(words[1])
            if reference.is_absolute():
                raise ValueError("Absolute SPICE model reference")
            candidate = path.parent / reference
            if candidate.is_symlink():
                raise ValueError("Symbolic SPICE model reference")
            child = candidate.resolve(strict=True)
            child.relative_to(root)
            edges.append({"file": str(path.relative_to(root)), "line": line_number,
                          "includes": str(child.relative_to(root))})
            pending.append(child)
    return sorted(seen), sorted(edges, key=lambda x: (x["file"], x["line"], x["includes"]))


def copy_regular(source: Path, target: Path) -> None:
    if source.is_symlink() or not source.is_file():
        raise ValueError("Source is not a regular file")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    target.chmod(0o644)


def git_blob(checkout: Path, commit: str, path: str) -> bytes:
    return subprocess.check_output(["git", "-C", str(checkout), "show", f"{commit}:{path}"])


def extract_pcells(checkout: Path, destination: Path) -> None:
    archive = subprocess.check_output([
        "git", "-C", str(checkout), "archive", PCELLS_COMMIT, "LICENSE", "sky130",
    ])
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as stream:
        for member in stream.getmembers():
            relative = Path(member.name)
            if relative.is_absolute() or ".." in relative.parts:
                raise ValueError("Unsafe upstream archive path")
            if member.isdir():
                continue
            if not member.isfile():
                raise ValueError("Upstream archive contains a non-regular file")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.extractfile(member).read())
            target.chmod(0o755 if member.mode & 0o111 else 0o644)


def relocate_magic(text: str) -> str:
    # The old qualified installation performed exactly this path relocation.
    # Capture its fallback line, not an installation-specific source directory.
    pattern = r"(?m)^([ \t]*set (?:PDK_ROOT|TECHPATH) )/[^\r\n]+$"
    relocated, count = re.subn(pattern, lambda match: match[1] + PREFIX, text)
    if count != 1:
        raise ValueError("Expected exactly one Magic fallback PDK_ROOT")
    return relocated


def write_readme(path: Path) -> None:
    path.write_text("""# Pinned SKY130 runtime assets

The Python PCells and their fixed-cell GDS resources are unmodified upstream
library assets, not benchmark task solutions. `asset-manifest.json` lists every
installed file, public source revisions, license locations and byte hashes.

- `python/`: gdsfactory SKY130 package; add this directory to the Python path.
- `klayout/`: the selected DRC and LVS decks.
- `sky130A/libs.tech/magic/`: the qualified open_pdks technology/startup files.
- `sky130A/libs.tech/netgen/`: the original preprocessed SKY130A comparison setup.
- `sky130A/libs.tech/combined/continuous/`: the continuous SPICE models.
- `sky130A/libs.tech/ngspice/` and model-only files under `libs.ref/`: the separate
  binned SPICE model set. Both sets retain their complete recursive include
  closures across declared corners. Use the entry selected by each task.
- `docs/skywater-pdk/`: upstream process/device reference RST, tables and figures.
- `docs/DEVICE_API.md`: installed software API notes, separate from process rules.

Only Magic's two build-machine fallback paths are relocated to the fixed runtime
prefix. Technology, model and deck algorithms are unchanged. `setup.tcl` is an
identical regular-file alias of `sky130A_setup.tcl` for portable packaging.

This is the selected analog runtime subset, not a complete digital PDK install.
Optional standard-cell MAG search paths remain in Magic's upstream startup file;
those cell libraries are not needed by the GDS-ingestion analog extraction flow.
The selected DRC deck does not establish full foundry signoff or silicon validity.
Process reference documents and installed tool-specific implementations have
separate pinned revisions; use task-selected model entry points.
""")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--destination", type=Path, required=True)
    parser.add_argument("--pcells-checkout", type=Path, required=True)
    parser.add_argument("--drc-deck", type=Path, required=True)
    parser.add_argument("--lvs-deck", type=Path, required=True)
    parser.add_argument("--magic-directory", type=Path, required=True)
    parser.add_argument("--models-directory", type=Path, required=True)
    parser.add_argument("--binned-pdk-directory", type=Path, required=True,
                        help="Qualified Volare sky130A directory containing libs.tech and libs.ref")
    parser.add_argument("--open-pdks-checkout", type=Path, required=True)
    parser.add_argument("--process-docs-directory", type=Path, required=True)
    parser.add_argument("--process-docs-license", type=Path, required=True)
    parser.add_argument("--api-docs-directory", type=Path, required=True)
    parser.add_argument("--license-directory", type=Path, default=Path("/usr/share/common-licenses"))
    parser.add_argument("--compare-manifest", type=Path,
                        help="Require exactly the already reviewed file set and hashes")
    args = parser.parse_args()
    destination = args.destination.resolve()
    if destination.exists():
        raise SystemExit("Destination must not exist")
    destination.mkdir(parents=True)

    extract_pcells(args.pcells_checkout, destination / "python")
    for source, target in [(args.drc_deck, "klayout/sky130A_mr.drc"),
                           (args.lvs_deck, "klayout/sky130.lvs")]:
        copy_regular(source, destination / target)
    for name in MAGIC_FILES:
        source = args.magic_directory / name
        target = destination / "sky130A/libs.tech/magic" / name
        copy_regular(source, target)
        if name in ("sky130A.magicrc", "sky130A.tcl"):
            target.write_text(relocate_magic(target.read_text()))
    files, edges = model_closure(args.models_directory / "sky130.lib.spice", args.models_directory)
    model_target = destination / "sky130A/libs.tech/combined/continuous"
    for source in files:
        copy_regular(source, model_target / source.relative_to(args.models_directory.resolve()))
    binned_root = args.binned_pdk_directory.resolve(strict=True)
    binned_files, binned_edges = model_closure(
        binned_root / "libs.tech/ngspice/sky130.lib.spice", binned_root)
    for source in binned_files:
        copy_regular(source, destination / "sky130A" / source.relative_to(binned_root))

    setup_target = destination / "sky130A/libs.tech/netgen"
    setup_target.mkdir(parents=True)
    with tempfile.TemporaryDirectory(prefix="alw-pdk-preproc-") as temporary:
        temporary = Path(temporary)
        (temporary / "preproc.py").write_bytes(git_blob(args.open_pdks_checkout, OPEN_PDKS_COMMIT, "common/preproc.py"))
        (temporary / "setup.tcl").write_bytes(git_blob(args.open_pdks_checkout, OPEN_PDKS_COMMIT, "sky130/netgen/sky130_setup.tcl"))
        subprocess.run([sys.executable, str(temporary / "preproc.py"), str(temporary / "setup.tcl"),
                        str(setup_target / "sky130A_setup.tcl"), "-DTECHNAME=sky130A", "-DMETAL5", "-DMIM", "-DREDISTRIBUTION"], check=True)
    copy_regular(setup_target / "sky130A_setup.tcl", setup_target / "setup.tcl")

    for source in sorted(args.process_docs_directory.rglob("*")):
        if source.is_dir() and not source.is_symlink():
            continue
        copy_regular(source, destination / "docs/skywater-pdk" / source.relative_to(args.process_docs_directory))
    copy_regular(args.process_docs_license, destination / "docs/skywater-pdk/LICENSE")
    for name in ("DEVICE_API.md", "DEVICE_API.zh-CN.md"):
        copy_regular(args.api_docs_directory / name, destination / "docs" / name)
    copy_regular(destination / "python/LICENSE", destination / "licenses/gdsfactory-skywater130-MIT")
    license_target = destination / "licenses/open-pdks-LICENSE"
    license_target.parent.mkdir(parents=True, exist_ok=True)
    license_target.write_bytes(git_blob(args.open_pdks_checkout, OPEN_PDKS_COMMIT, "LICENSE"))
    for name in ("Apache-2.0", "GPL-3"):
        copy_regular(args.license_directory / name, destination / "licenses" / name)
    write_readme(destination / "README.md")
    (destination / "model-includes.json").write_text(json.dumps({
        "entry": "sky130A/libs.tech/combined/continuous/sky130.lib.spice",
        "all_corner_sections_scanned": True, "file_count": len(files), "edge_count": len(edges),
        "model_bytes": sum(p.stat().st_size for p in files), "edges": edges,
    }, indent=2) + "\n")
    (destination / "binned-model-includes.json").write_text(json.dumps({
        "entry": "sky130A/libs.tech/ngspice/sky130.lib.spice",
        "reference_root": "sky130A", "all_corner_sections_scanned": True,
        "file_count": len(binned_files), "edge_count": len(binned_edges),
        "model_bytes": sum(p.stat().st_size for p in binned_files), "edges": binned_edges,
    }, indent=2) + "\n")

    installed = {}
    for path in sorted(destination.rglob("*")):
        if path.is_symlink():
            raise ValueError("Package cannot contain symbolic links")
        if path.is_file():
            data = path.read_bytes()
            if b"/mnt/" in data:
                raise ValueError("Package contains a host mount reference")
            installed[str(path.relative_to(destination))] = {"bytes": len(data), "sha256": digest(path)}
    manifest = {
        "schema": "analoglayoutworld-sky130-runtime-v1", "runtime_prefix": PREFIX,
        "sources": SOURCES,
        "versions": {"technology": "sky130A", "gdsfactory_api": "9.45.0", "kfactory_api": "2.6.1"},
        "model_sets": {
            "continuous": {"entry": "sky130A/libs.tech/combined/continuous/sky130.lib.spice",
                           "closure_manifest": "model-includes.json"},
            "binned": {"entry": "sky130A/libs.tech/ngspice/sky130.lib.spice",
                       "closure_manifest": "binned-model-includes.json"},
        },
        "asset_file_count": len(installed), "asset_bytes": sum(x["bytes"] for x in installed.values()),
        "files": installed,
    }
    if args.compare_manifest:
        previous = json.loads(args.compare_manifest.read_text())
        if manifest != previous:
            raise ValueError("Generated package differs from the reviewed manifest")
    (destination / "asset-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"files": len(installed), "bytes": manifest["asset_bytes"],
                      "continuous_model_files": len(files), "continuous_model_edges": len(edges),
                      "binned_model_files": len(binned_files), "binned_model_edges": len(binned_edges)}, indent=2))


if __name__ == "__main__":
    main()
