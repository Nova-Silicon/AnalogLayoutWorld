#!/usr/bin/env python3
"""Build the fixed public DSH release without modifying an image or global npm."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]
VERSION = "0.2.1-rc.5"
PNPM_VERSION = "11.7.0"
PACKAGE = "@deepseek-ai/dsh"
ENTRYPOINT = "node_modules/@deepseek-ai/dsh/lib/bin.js"
LOCK = ROOT / "harnesses/deepseek-harness/pnpm-lock.yaml"
EMPTY_NPMRC = LOCK.with_name("npmrc.empty")
HOOK = LOCK.with_name(".pnpmfile.cjs")
HOOK_SHA256 = "2a22e4944889c7052b2f3523685df80ce3e4f89ebe43f1e45e349a314723d3a2"
LOCK_SHA256 = "ec20976bb6deb94e0422eb22ef80a75cb310c0439ca55a2bdbe81fbe56545ee9"
BUILD_APPROVALS = [
    "@deepseek-ai/dsh-subprocess-local@0.2.1-rc.5",
    "@google/genai@2.21.0", "koffi@3.1.1", "node-pty@1.2.0-beta.15",
    "protobufjs@7.6.6",
]


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def inventory(root: Path) -> dict:
    files = {}
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        if path.is_symlink():
            target = path.readlink()
            if target.is_absolute() or not path.exists() or not path.resolve().is_relative_to(root):
                raise ValueError("Dependency link escapes its bundle: " + name)
            files[name] = {"symlink": str(target)}
        elif path.is_file():
            files[name] = {"sha256": sha256(path), "bytes": path.stat().st_size}
        elif not path.is_dir():
            raise ValueError("Dependency bundle contains a special file: " + name)
    return files


def build(output: Path, cache: Path, pnpm: Path, node: Path) -> dict:
    # The frozen lock's optional native packages and recorded lifecycle approvals
    # were qualified on this platform. Other platforms need separate validation.
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ValueError("This fixed runtime build targets Linux x86_64")
    output = output.resolve()
    cache = cache.resolve()
    if output.exists() or output.is_symlink():
        raise ValueError("Output already exists; choose a new bundle directory")
    if cache.is_relative_to(output):
        raise ValueError("The mutable package cache must be outside the bundle")
    if sha256(LOCK) != LOCK_SHA256:
        raise ValueError("The reviewed DSH dependency lock has changed")
    if sha256(HOOK) != HOOK_SHA256:
        raise ValueError("The build hook bound by the frozen lock has changed")
    if EMPTY_NPMRC.read_text().strip():
        raise ValueError("The package-manager user configuration must remain empty")
    node = node.resolve(strict=True)
    pnpm = pnpm.resolve(strict=True)
    env = dict(os.environ, PATH=str(node.parent) + os.pathsep + os.environ.get("PATH", ""),
               npm_config_registry="https://registry.npmjs.org",
               npm_config_userconfig=str(EMPTY_NPMRC), npm_config_globalconfig="/dev/null",
               MAKEFLAGS="-j1", CMAKE_BUILD_PARALLEL_LEVEL="1", npm_config_jobs="1")
    node_version = subprocess.check_output([str(node), "--version"], text=True, env=env).strip()
    manager_version = subprocess.check_output([str(node), str(pnpm), "--version"], text=True, env=env).strip()
    if not node_version.startswith("v22.") or manager_version != PNPM_VERSION:
        raise ValueError("Use Node 22 and pnpm " + PNPM_VERSION + " for this lock")
    output.mkdir(parents=True)
    (output / "package.json").write_text(json.dumps({
        "name": "alw-dsh-runtime", "private": True, "version": "1.0.0",
        "dependencies": {PACKAGE: VERSION},
    }, indent=2) + "\n")
    (output / "pnpm-workspace.yaml").write_text(json.dumps({
        "packages": [], "allowBuilds": {name: True for name in BUILD_APPROVALS},
    }, indent=2) + "\n")
    shutil.copyfile(LOCK, output / LOCK.name)
    shutil.copyfile(HOOK, output / HOOK.name)
    subprocess.run([
        str(node), str(pnpm), "install", "--prod", "--frozen-lockfile",
        "--trust-lockfile", "--prefer-offline", "--registry", "https://registry.npmjs.org",
        "--store-dir", str(cache),
    ], cwd=output, env=env, check=True)
    if sha256(output / LOCK.name) != LOCK_SHA256:
        raise ValueError("Package installation changed the frozen lock")
    installed = json.loads((output / "node_modules/@deepseek-ai/dsh/package.json").read_text())
    if (installed.get("name"), installed.get("version")) != (PACKAGE, VERSION):
        raise ValueError("Installed DSH identity differs from the fixed release")
    if not (output / ENTRYPOINT).is_file():
        raise ValueError("The native DSH entrypoint was not installed")
    manifest = {
        "schema_version": 1, "package": PACKAGE, "version": VERSION,
        "entrypoint": ENTRYPOINT,
        "upstream": {"repository": "https://github.com/deepseek-ai/deepseek-harness",
                     "registry": "https://registry.npmjs.org"},
        "build": {"node_version": node_version, "package_manager": "pnpm",
                  "package_manager_version": manager_version, "allow_builds": BUILD_APPROVALS,
                  "system": platform.system(), "machine": platform.machine()},
        "lockfile": LOCK.name, "lock_sha256": LOCK_SHA256, "files": inventory(output),
    }
    (output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return {"version": VERSION, "manifest_sha256": sha256(output / "manifest.json"),
            "files": len(manifest["files"])}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--cache", type=Path, required=True)
    p.add_argument("--node", type=Path, required=True, help="Node 22 executable")
    p.add_argument("--pnpm", type=Path, required=True, help="pnpm 11.7.0 bin/pnpm.cjs")
    a = p.parse_args()
    try:
        result = build(a.output, a.cache, a.pnpm, a.node)
    except (OSError, ValueError, subprocess.CalledProcessError) as e:
        p.exit(1, str(e) + "\n")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
