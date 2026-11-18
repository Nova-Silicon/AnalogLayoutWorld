"""Check fixed tool versions, hashes and the actual SKY130 import; no evaluation."""
from __future__ import annotations

import argparse
import importlib.metadata
import json
from pathlib import Path
import re
import shlex

from .runtime import klayout_env, load_runtime, magic_env, run_command, sha256, shared_output, work_env


def model_dependencies(entry: Path) -> dict:
    """Check a SPICE library's file closure without changing model contents.

    This checks all included sections, not electrical correctness. .lib section
    declarations have two words; .lib filename section has three.
    """
    seen, missing, unresolved = set(), set(), []

    def walk(path: Path):
        path = path.resolve()
        if path in seen:
            return
        seen.add(path)
        if not path.is_file():
            missing.add(str(path))
            return
        for line in path.read_text(errors="replace").splitlines():
            if not re.match(r"^\s*\.(?:inc(?:lude)?|lib)\b", line, re.I):
                continue
            try:
                words = shlex.split(line, comments=True)
            except ValueError:
                unresolved.append({"file": str(path), "line": line})
                continue
            if len(words) < 2 or (words[0].lower() == ".lib" and len(words) < 3):
                continue
            dependency = words[1]
            if any(token in dependency for token in ("$", "{", "~")) or re.search(r"__[A-Z][A-Z0-9_]*__", dependency):
                unresolved.append({"file": str(path), "include": dependency})
                continue
            target = Path(dependency)
            walk(target if target.is_absolute() else path.parent / target)

    walk(entry)
    return {"name": "model_dependency_closure", "entry": str(entry),
            "files_checked": len(seen), "missing": sorted(missing),
            "unresolved": unresolved, "passed": not missing and not unresolved}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="New directory under the task's output roots")
    parser.add_argument("--model-lib", type=Path, action="append", default=[],
                        help="Also check the file closure of each specified SPICE library")
    args = parser.parse_args()
    out = shared_output(args.out)
    out.mkdir(parents=True, exist_ok=False)
    work_env(out)
    result = {"scope": "Local dependency preflight, not an Agent evaluation or DRC/LVS certification", "checks": []}
    checks = result["checks"]
    try:
        runtime = load_runtime()
        for library in args.model_lib:
            checks.append(model_dependencies(library))
        import sky130
        expected = Path(runtime["sky130_python"]) / "sky130/__init__.py"
        checks.append({"name": "sky130_import", "passed": Path(sky130.__file__).resolve() == expected,
                       "actual": sky130.__file__, "expected": str(expected)})
        for package in ("gdsfactory", "kfactory", "klayout"):
            version = importlib.metadata.version(package)
            checks.append({"name": package, "actual": version,
                           "expected": runtime["versions"][package],
                           "passed": version == runtime["versions"][package]})
        for key, digest in runtime["file_sha256"].items():
            actual = sha256(Path(runtime[key]))
            checks.append({"name": key + "_sha256", "actual": actual, "passed": actual == digest})
        for name, key, flags in (("klayout", "klayout_bin", ["-v"]),
                                  ("magic", "magic_bin", ["--version"]),
                                  ("ngspice", "ngspice_bin", ["--version"])):
            work = out / name
            env = {"klayout": klayout_env, "magic": magic_env}.get(name, work_env)(work)
            command = run_command([runtime[key], *flags], cwd=work, env=env, timeout=30)
            output = Path(command["log_path"]).read_text(errors="replace")
            checks.append({"name": name + "_cli", "passed": command["status"] == "completed"
                           and command["returncode"] == 0 and runtime["versions"][name] in output,
                           "command": command, "output": output.strip()})
    except Exception as exc:
        checks.append({"name": "preflight_exception", "passed": False, "error": str(exc)})
    result["passed"] = bool(checks) and all(check["passed"] for check in checks)
    (out / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if result["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
