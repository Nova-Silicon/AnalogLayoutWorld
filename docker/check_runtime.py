#!/usr/bin/env python3
"""Exercise installed EDA tools and package imports in the final image."""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET


def check_magic_manuals(directory: Path) -> dict[str, str]:
    # SHA-256 of the paper environment's text editions of Magic 8.3.685 help.
    expected = {
        "ext2spice.txt": "b2336dc69b673f54c417b2c6ce85b48bbb152cf0a87ac4c68aa1a124b166e853",
        "extract.txt": "2f46136380c83c6768a8f3fa44c524000f688a966b536d184d33318b488f8248",
        "extresist.txt": "ab5856dbe46c655fb1bd33fe23da5199ee8fee7f819581eebd12fde58bf640d0",
        "flatten.txt": "6a6a2abe6e2e5425ea7fffdf251a797865c062afcacdd62b6dfd5a7275a546d7",
        "gds.txt": "afd1934555076331450d672eacf95cd0eac25ca4740f520fb9c3006f57f3cc18",
    }
    for name, digest in expected.items():
        path = directory / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != digest:
            raise ValueError(f"Magic command reference differs from paper-v1: {path}")
    return expected


def unresolved(process) -> bool:
    static = any(value in process.stdout for value in ("not a dynamic executable", "statically linked"))
    return "not found" in process.stdout or bool(process.returncode and not static)


def loaded_paths(text: str) -> set[Path]:
    return {Path(value).resolve() for value in re.findall(r"(?:=>\s*|^\s*)(/\S+)\s+\(", text, re.MULTILINE)}


def parent_loader_context(library: Path, bundle: Path, consumers, analyses, dynamic_reader):
    """Prove a wheel auxiliary library through its actual parent loader.

    Callers restrict consumers to ELF files owned by the same wheel RECORD.
    This does not add any library-search directories to the runtime environment.
    """
    for consumer in sorted(consumers):
        if consumer.is_relative_to(bundle):
            continue
        process = analyses.get(consumer)
        if process is None or unresolved(process) or library.resolve() not in loaded_paths(process.stdout):
            continue
        dynamic = dynamic_reader(consumer)
        declared = []
        for kind, value in re.findall(r"\((RPATH|RUNPATH)\).*?\[([^]]+)\]", dynamic):
            for part in value.split(":"):
                expanded = part.replace("${ORIGIN}", str(consumer.parent)).replace("$ORIGIN", str(consumer.parent))
                if "$" not in expanded and Path(expanded).is_absolute() and Path(expanded).resolve() == bundle.resolve():
                    declared.append({"kind": kind, "value": part})
        if declared:
            return {"library": str(library), "consumer": str(consumer),
                    "bundle_directory": str(bundle), "declared_loader_paths": declared,
                    "proof": "same-wheel parent ELF ldd resolves the library and its complete dependency closure"}
    return None


def wheel_consumers(library: Path, site: Path):
    """Find the single installed distribution that owns this exact auxiliary file."""
    owners = []
    for distribution in importlib.metadata.distributions(path=[str(site)]):
        objects = {Path(distribution.locate_file(item)).resolve() for item in distribution.files or []
                   if ".so" in Path(item).name}
        if library.resolve() in objects:
            owners.append((distribution.metadata["Name"], objects))
    return owners[0] if len(owners) == 1 else (None, set())


def check(output: Path) -> dict:
    output.mkdir(parents=True, exist_ok=False)
    tools = Path("/opt/analog-layout/tools")
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen", LANG="C.UTF-8")
    env.pop("LD_LIBRARY_PATH", None)
    env.pop("LD_PRELOAD", None)
    for name, value in {
        "HOME": output / "home", "TMPDIR": output / "tmp", "XDG_CACHE_HOME": output / "cache",
        "XDG_RUNTIME_DIR": output / "xdg", "KLAYOUT_HOME": output / "klayout-home",
    }.items():
        value.mkdir(mode=0o700)
        env[name] = str(value)
    result = {"checks": {}, "passed": False, "elf_count": 0, "dynamic_link_errors": [],
              "validated_wheel_loader_contexts": []}

    def run(name, argv, stdin=None, *, timeout=90):
        process = subprocess.run(argv, input=stdin, text=True, env=env, cwd=output,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=timeout)
        (output / f"{name}.log").write_text(process.stdout)
        result["checks"][name] = {"returncode": process.returncode, "log": f"{name}.log"}
        if process.returncode:
            print(f"Image check {name} exited {process.returncode}; output tail:", file=sys.stderr)
            print(process.stdout[-8000:], file=sys.stderr)
            raise RuntimeError(f"Image check failed: {name}; see {name}.log")
        return process.stdout

    try:
        result["checks"]["magic_text_manuals"] = check_magic_manuals(tools / "magic/lib/magic/doc/text")
        # Fail early on missing runtime libraries before invoking any tool.
        # Check optional plugins as well as executable launch dependencies.
        klayout_lib = tools / "klayout/usr/lib/klayout"
        klayout_link_env = {**env, "LD_LIBRARY_PATH": ":".join(map(str, (
            klayout_lib, klayout_lib / "db_plugins", klayout_lib / "lay_plugins")))}
        candidates = set(tools.rglob("*"))
        python_root = Path("/opt/analog-layout/python")
        candidates.update(python_root.rglob("*.so*"))
        candidates.add(python_root / "bin/python3.12")
        candidates.add(Path("/opt/analog-layout/agent/bin/node"))
        link_logs = []
        analyses = {}
        for path in sorted(candidates):
            if path.is_symlink() or not path.is_file():
                continue
            with path.open("rb") as stream:
                if stream.read(4) != b"\x7fELF":
                    continue
            result["elf_count"] += 1
            # Only the native KLayout wrapper sets this search path. Python
            # wheels and other tools are inspected with the unmodified loader.
            context_env = klayout_link_env if path.is_relative_to(tools / "klayout") else env
            process = subprocess.run(["/usr/bin/ldd", str(path)], text=True, env=context_env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            link_logs.append(f"{path}\n{process.stdout}")
            analyses[path] = process

        def dynamic_reader(path):
            process = subprocess.run(["/usr/bin/readelf", "-d", str(path)], text=True, env=env,
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30)
            if process.returncode:
                raise RuntimeError(f"Cannot inspect wheel loader paths: {path}")
            link_logs.append(f"ELF loader paths: {path}\n{process.stdout}")
            return process.stdout

        site = python_root / "lib/python3.12/site-packages"
        for path, process in analyses.items():
            if not unresolved(process):
                continue
            bundle = next((parent for parent in path.parents
                           if parent.name.endswith(".libs") and parent.is_relative_to(site)), None)
            owner, consumers = wheel_consumers(path, site) if bundle else (None, set())
            context = parent_loader_context(path, bundle, consumers, analyses, dynamic_reader) if owner else None
            if context:
                context["distribution"] = owner
                context["bare_ldd_output"] = process.stdout
                result["validated_wheel_loader_contexts"].append(context)
                print(f"Validated {owner} wheel loader context: {path} via {context['consumer']}", flush=True)
                continue
            result["dynamic_link_errors"].append(str(path))
            print(f"Unresolved runtime dependency: {path}\n{process.stdout}", file=sys.stderr)
        (output / "ldd.log").write_text("\n".join(link_logs))
        if result["dynamic_link_errors"]:
            raise RuntimeError("Runtime ELF dependencies unresolved; see ldd.log")
        for name, version in [("klayout", "0.30.12"), ("magic", "8.3.685"), ("ngspice", "ngspice-46")]:
            text = run(f"{name}_version", [str(tools / "bin" / name), "-v" if name == "klayout" else "--version"])
            if version not in text:
                raise RuntimeError(f"Unexpected {name} version")
            if name == "ngspice" and "KLU" not in text:
                raise RuntimeError("ngspice was built without the qualified KLU solver")
        (output / "geometry.rb").write_text(
            'ly=RBA::Layout.new; ly.dbu=0.001; c=ly.create_cell("TOP"); '
            'c.shapes(ly.layer(1,0)).insert(RBA::Box.new(0,0,50,1000)); '
            'ly.write("toy.gds"); puts "ruby_geometry_ok"\n')
        if "ruby_geometry_ok" not in run("klayout_ruby", [str(tools / "bin/klayout"), "-b", "-r", "geometry.rb"]):
            raise RuntimeError("KLayout Ruby did not execute geometry creation")
        (output / "embedded_python.py").write_text(
            'import pya, sys\nassert sys.version_info[:2] == (3,10)\n'
            'ly=pya.Layout();ly.read("toy.gds");assert ly.top_cell().name=="TOP"\n'
            'print("embedded_python_geometry_ok")\n')
        if "embedded_python_geometry_ok" not in run("klayout_python", [str(tools / "bin/klayout"), "-b", "-r", "embedded_python.py"]):
            raise RuntimeError("KLayout embedded Python did not read the GDS")
        (output / "width.drc").write_text(
            'source("toy.gds", "TOP")\nreport("Image smoke", "width.lyrdb")\n'
            'input(1,0).width(0.14).output("width", "too narrow")\n')
        run("klayout_drc", [str(tools / "bin/klayout"), "-b", "-r", "width.drc"])
        if len(ET.parse(output / "width.lyrdb").findall("./items/item")) != 1:
            raise RuntimeError("KLayout DRC did not detect the intentional width violation")
        (output / "divider.spice").write_text(
            'Simulator smoke\nV1 in 0 DC 1\nR1 in out 1k\nR2 out 0 1k\n'
            '.control\nop\nprint v(out)\nquit\n.endc\n.end\n')
        if "5.000000e-01" not in run("ngspice_op", [str(tools / "bin/ngspice"), "-b", "divider.spice"]):
            raise RuntimeError("ngspice DC divider result differs from 0.5V")
        # The release tasks deliberately select two different upstream model
        # trees. Exercise both; this must not normalize task choices to one.
        (output / ".spiceinit").write_text("set ngbehavior=hsa\nset num_threads=1\n")
        for model_kind, relative, timeout in [
            ("continuous", "sky130A/libs.tech/combined/continuous/sky130.lib.spice", 90),
            ("binned", "sky130A/libs.tech/ngspice/sky130.lib.spice", 300),
        ]:
            entry = Path("/opt/analog-layout/pdks/sky130") / relative
            model_test = output / f"model_{model_kind}.spice"
            model_test.write_text(
                f"SKY130 {model_kind} model parse/DC smoke\n.lib '{entry}' tt\n"
                ".option scale=1e-6\nV_D d 0 1.0\nV_G g 0 1.0\n"
                "XQ d g 0 0 sky130_fd_pr__nfet_01v8 L=0.15 W=1 nf=1\n"
                ".control\nop\nprint i(v_d)\nquit\n.endc\n.end\n")
            name = f"model_{model_kind}_op"
            text = run(name, [str(tools / "bin/ngspice"), "-b", model_test.name], timeout=timeout)
            observed = re.search(r"(?im)^i\(v_d\)\s*=\s*([-+0-9.eE]+)", text)
            current = float(observed.group(1)) if observed else float("nan")
            if not math.isfinite(current) or abs(current) <= 1e-15:
                raise RuntimeError(f"SKY130 {model_kind} models did not produce a finite active-device DC result")
            result["checks"][name]["drain_current_a"] = current
        text = run("magic_tcl", [str(tools / "bin/magic"), "-dnull", "-noconsole"],
                   'puts "magic_tcl_ok"\nquit -noprompt\n')
        if "magic_tcl_ok" not in text:
            raise RuntimeError("Magic Tcl execution failed")
        (output / "netgen.tcl").write_text(
            'puts "NETGEN_VERSION=[package present Tclnetgen]"\nputs "NETGEN_LVS=[info commands lvs]"\nquit\n')
        text = run("netgen_tcl", [str(tools / "bin/netgen"), "-batch", "source", "netgen.tcl"])
        if "1.5.324" not in text or "NETGEN_LVS=lvs" not in text:
            raise RuntimeError("Netgen version or Tcl LVS command unavailable")
        run("python_eda", ["/opt/analog-layout/python/bin/python", "-I", "-B", "-c",
            "import importlib.metadata as m; import gdsfactory as gf, klayout.db as kdb, sky130; "
            "assert m.version('gdsfactory')=='9.45.0'; assert m.version('kfactory')=='2.6.1'; "
            "assert m.version('klayout')=='0.30.12'; "
            "ly=kdb.Layout(); ly.read('toy.gds'); assert ly.top_cell().name=='TOP'; "
            "print('eda_python_imports_and_gds_ok')"])
        run("python_geometry_numeric", ["/opt/analog-layout/python/bin/python", "-I", "-B", "-c",
            "from shapely.geometry import Point,box; import scipy.linalg; import numpy as np; "
            "p=Point(0,0).buffer(1); assert p.intersection(box(0,0,2,2)).area>0; "
            "assert np.allclose(scipy.linalg.solve([[2.,0.],[0.,3.]],[4.,9.]),[2.,3.]); "
            "print('SHAPELY_SCIPY_OK')"])
        if run("node", ["node", "--version"]).strip() != "v22.23.3":
            raise RuntimeError("Unexpected Node version")
        run("npm", ["npm", "--version"])
        if "15.1.0" not in run("ripgrep", ["rg", "--version"]):
            raise RuntimeError("Unexpected ripgrep version")
        run("pip_check", ["/opt/analog-layout/python/bin/python", "-I", "-m", "pip", "check"])
        result["passed"] = True
    finally:
        (output / "result.json").write_text(json.dumps(result, indent=2) + "\n")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(check(args.out), indent=2))
