#!/usr/bin/env python3
"""Generate the image-local EDA runtime manifest, without host-path fallbacks."""
from __future__ import annotations

import hashlib
import importlib.metadata
import json
from pathlib import Path
import re
import sys


PREFIX = Path("/opt/analog-layout")


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def runtime_paths(prefix: Path = PREFIX) -> dict[str, Path]:
    pdk = prefix / "pdks/sky130"
    return {
        "python_bin": prefix / "python/bin/python3.12",
        "sky130_python": pdk / "python",
        "klayout_bin": prefix / "tools/bin/klayout",
        "klayout_executable": prefix / "tools/klayout/usr/bin/klayout",
        "magic_bin": prefix / "tools/magic/bin/magic",
        "magic_executable": prefix / "tools/magic/lib/magic/tcl/magicdnull",
        "ngspice_bin": prefix / "tools/ngspice/bin/ngspice",
        "drc_deck": pdk / "klayout/sky130A_mr.drc",
        "lvs_deck": pdk / "klayout/sky130.lvs",
        "magic_rcfile": pdk / "sky130A/libs.tech/magic/sky130A.magicrc",
        "magic_tech": pdk / "sky130A/libs.tech/magic/sky130A.tech",
        "magic_pdk_tcl": pdk / "sky130A/libs.tech/magic/sky130A.tcl",
        "model_lib": pdk / "sky130A/libs.tech/combined/continuous/sky130.lib.spice",
        "model_lib_binned": pdk / "sky130A/libs.tech/ngspice/sky130.lib.spice",
        "sky130_mosfets": pdk / "python/sky130/pcells/mosfets.py",
        "sky130_resistors": pdk / "python/sky130/pcells/resistors.py",
        "pdk_asset_manifest": pdk / "asset-manifest.json",
        "netgen_bin": prefix / "tools/netgen/bin/netgen",
        "netgen_executable": prefix / "tools/netgen/lib/netgen/tcl/netgenexec",
        "netgen_library": prefix / "tools/netgen/lib/netgen/tcl/tclnetgen.so",
        "netgen_setup": pdk / "sky130A/libs.tech/netgen/sky130A_setup.tcl",
    }


def main() -> None:
    if sys.version_info[:3] != (3, 12, 14):
        raise ValueError("Finalize with the pinned EDA Python 3.12.14")
    pdk = PREFIX / "pdks/sky130"
    pdk_manifest = json.loads((pdk / "asset-manifest.json").read_text())
    pdk_sources = pdk_manifest["sources"]
    paths = runtime_paths()
    candidates = [
        ("model_file", pdk / "sky130A/libs.tech/combined/continuous", "*"),
        ("model_binned_file", pdk / "sky130A/libs.tech/ngspice", "*"),
        ("model_ref_file", pdk / "sky130A/libs.ref", "*.spice"),
        ("magic_library", PREFIX / "tools/magic", "*.so"),
        ("klayout_library", PREFIX / "tools/klayout/usr/lib/klayout", "*.so*"),
        ("ngspice_codemodel", PREFIX / "tools/ngspice/lib/ngspice", "*.cm"),
    ]
    for label, root, pattern in candidates:
        for number, path in enumerate(sorted(root.rglob(pattern))):
            if path.is_file() and not path.is_symlink():
                paths[f"{label}_{number:03d}"] = path
    paths["ngspice_init"] = PREFIX / "tools/ngspice/share/ngspice/scripts/spinit"
    for path in paths.values():
        path.resolve(strict=True).relative_to(PREFIX)
    versions = {
        name: importlib.metadata.version(name) for name in ("gdsfactory", "kfactory", "klayout")
    }
    if versions != {"gdsfactory": "9.45.0", "kfactory": "2.6.1", "klayout": "0.30.12"}:
        raise ValueError("EDA Python package versions differ from the release lock")
    versions.update(python="3.12.14", magic="8.3.685", ngspice="46", netgen="1.5.324")
    manifest = {
        "schema_version": 1,
        "status": "image-local runtime; stage validation recorded separately",
        "execution": {"mode": "image", "output_roots": ["/alb-workspace", "/logs/verifier"]},
        "paths": {key: str(path) for key, path in paths.items()},
        "versions": versions,
        "sources": {
            "skywater130": {
                "repository": pdk_sources["pcells"]["repository"],
                "commit": pdk_sources["pcells"]["commit"],
                "source_policy": "Unmodified pinned upstream source and resources",
            },
            "klayout_decks": {
                "repository": pdk_sources["klayout_decks"]["repository"],
                "commit": pdk_sources["klayout_decks"]["commit"],
            },
            "open_pdks_commit": pdk_sources["magic_technology"]["commit"],
            "model_volare_commit": pdk_sources["continuous_models"]["release"].removeprefix("sky130-"),
            "magic_commit": "bed8d4ff84333767aa923d469d339cd05c56a00a",
            "netgen_commit": "3cb047bd6b55ae09c8eefeb479b4fe746cfdb948",
            "netgen_setup_open_pdks_commit": pdk_sources["netgen_setup"]["commit"],
        },
        "file_sha256": {key: digest(path) for key, path in paths.items() if path.is_file()},
        "qualification": {
            "drc": "Selected SKY130 deck; not full foundry signoff",
            "lvs": "Connectivity, device geometry and top-port checks",
            "pex": "Provisional Magic RC extraction; no algorithm changes",
            "device_source": "Unmodified pinned upstream Python source and resources",
        },
    }
    (PREFIX / "runtime.json").write_text(json.dumps(manifest, indent=2) + "\n")
    site = PREFIX / "python/lib/python3.12/site-packages"
    (site / "analog_layout_sky130.pth").write_text(str(pdk / "python") + "\n")
    (PREFIX / "env.sh").write_text(
        "# Source explicitly when entering a non-Docker shell. No credentials.\n"
        "export PATH=/opt/analog-layout/python/bin:/opt/analog-layout/tools/bin:/opt/analog-layout/agent/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin\n"
        "export PDK_ROOT=/opt/analog-layout/pdks/sky130\n"
        "export PYTHONDONTWRITEBYTECODE=1\nexport MPLBACKEND=Agg\n"
    )
    lock = PREFIX / "provenance/requirements.lock"
    expected = {}
    for line in lock.read_text().splitlines():
        if line.strip() and not line.startswith("#"):
            package, version = line.split()[0].split("==")
            expected[package] = version
    installed = {package: importlib.metadata.version(package) for package in expected}
    if installed != expected:
        raise ValueError("Installed package versions differ from requirements.lock")
    (PREFIX / "provenance/python-packages.json").write_text(json.dumps(installed, indent=2) + "\n")
    print(PREFIX / "runtime.json")


if __name__ == "__main__":
    main()
