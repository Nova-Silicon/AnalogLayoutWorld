"""Explicit MIM simulation-wrapper to fixed-deck LVS-only geometry view.

Not a circuit edit or simulation model. Supports cap_mim_m3_1/m3_2 with
literal positive W/L in um and positive integer SPICE instance multiplier m.
Connected arrays were checked against the unchanged process rules, including
wrong-count and wrong-size controls. Reference simplification is required.
The model's mult/mf statistical parameters are not nominal multipliers;
their original values remain in the simulation netlist.
"""
from pathlib import Path
import argparse
import hashlib
import json
import math
import re

MODEL = "sky130_fd_pr__cap_mim_m3_1"
PHYSICAL_MODEL = "sky130_fd_pr__model__cap_mim"
MODELS = {
    MODEL: PHYSICAL_MODEL,
    "sky130_fd_pr__cap_mim_m3_2": "sky130_fd_pr__model__cap_mim_m4",
}
QUALIFIED_DECK_SHA256 = "5b4ede4bdb4744b60e42c9b29baa93f40bb24430fb8f3a48a276a712a492ac38"


def mim_reference_view(text):
    lines = text.splitlines(keepends=True)
    # Instance names are local to a subcircuit, including nested definitions.
    # Collect before rewriting so a later C instance also blocks a collision.
    existing, scopes, scope = set(), [], []
    for i, line in enumerate(lines):
        subckt = re.match(r"\s*\.subckt\s+(\S+)", line, re.I)
        if subckt:
            scope.append(subckt[1])
        end = re.match(r"\s*\.ends\b(?:[ \t]+([^$;*\s]+))?", line, re.I)
        if end:
            if not scope or (end[1] and end[1].casefold() != scope[-1].casefold()):
                raise ValueError(f"Unmatched .ends at line {i + 1}")
            scope.pop()
        scopes.append(tuple(scope))
        instance = re.match(r"\s*([a-zA-Z]\S*)\s+", line)
        if instance:
            existing.add((tuple(part.casefold() for part in scope), instance[1].casefold()))
    if scope:
        raise ValueError(f"Unclosed .subckt {'/'.join(scope)}")
    mappings = []
    for i, line in enumerate(lines):
        if not any(model in line.casefold() for model in MODELS) or line.lstrip().startswith("*"):
            continue
        if i + 1 < len(lines) and lines[i + 1].lstrip().startswith("+"):
            raise ValueError(f"MIM row {i+1}: continuation parameters require explicit normalization")
        match = re.fullmatch(r"([ \t]*)(X\S+)\s+(\S+)\s+(\S+)\s+(sky130_fd_pr__cap_mim_m3_[12])\s+([^\n]+)(\n?)", line, re.I)
        if not match:
            raise ValueError(f"Unsupported MIM statement at line {i+1}; only flat literal instance rows are qualified")
        indent, old_name, bottom, top, model, parameters, newline = match.groups()
        model = model.casefold()
        physical_model = MODELS[model]
        entries = re.findall(r"(\w+)\s*=\s*([^\s]+)", parameters)
        if len({k.casefold() for k, v in entries}) != len(entries):
            raise ValueError("Duplicate MIM parameter is ambiguous")
        pairs = dict(entries)
        pairs = {key.casefold(): value for key, value in pairs.items()}
        residue = re.sub(r"\w+\s*=\s*[^\s]+", "", parameters).strip()
        if residue or not {"w", "l"} <= set(pairs) or set(pairs) - {"w", "l", "mult", "m", "mf"}:
            raise ValueError(f"MIM row {i+1}: require literal w/l and optional m/mult/mf; no dropped parameters")
        try:
            numbers = {key: float(value) for key, value in pairs.items()}
        except ValueError as error:
            raise ValueError("MIM sizes must be literal numbers in um, not expressions or suffixed SI dimensions") from error
        if not all(math.isfinite(value) and value > 0 for value in numbers.values()):
            raise ValueError("MIM parameters must be finite and positive")
        w, length = numbers["w"], numbers["l"]
        instance_m = numbers.get("m", 1.0)
        if not instance_m.is_integer():
            raise ValueError("Fractional MIM m is not qualified as a physical parallel array")
        count = int(instance_m)
        scope_key = tuple(part.casefold() for part in scopes[i])
        area, perimeter = w * length, 2 * (w + length)
        names, statements = [], []
        for unit in range(count):
            new_name = "C" + old_name[1:] + (f"__unit{unit+1}" if count > 1 else "")
            if (scope_key, new_name.casefold()) in existing:
                raise ValueError(f"LVS-view name collision {new_name} in {'/'.join(scopes[i]) or '<top>'}; resolve explicitly")
            existing.add((scope_key, new_name.casefold()))
            names.append(new_name)
            statements.append(f"{indent}{new_name} {bottom} {top} {physical_model} a={area:.12g} p={perimeter:.12g}")
        replacement = "\n".join(statements) + newline
        lines[i] = replacement
        mappings.append({
            "line_1based": i+1,
            "subcircuit": scopes[i][-1] if scopes[i] else "<top>",
            "subcircuit_path": list(scopes[i]),
            "original_instance": old_name,
            "physical_instances": names,
            "nodes_preserved": [bottom, top],
            "simulation_model": model,
            "physical_model": physical_model,
            "w_um": w, "l_um": length,
            "parallel_units": count,
            "non_nominal_parameters": {key: value for key, value in numbers.items() if key in {"mult", "mf"}},
            "unit_area_um2": area, "unit_perimeter_um": perimeter,
            "original_statement": line.rstrip(),
            "physical_statement": replacement.rstrip(),
            "reason": "Each physical unit is an A/P primitive under scale=true. Native schematic_simplify merges parallel units on both sides. This compares aggregate area/perimeter and connectivity; simulation retains the original model and statistical parameters.",
        })
    return "".join(lines), mappings


def write_mim_reference_view(source, destination, mapping_path):
    if destination.exists() or mapping_path.exists():
        raise ValueError("Refuse to overwrite input or evidence")
    original = source.read_bytes()
    output, mappings = mim_reference_view(original.decode())
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(output)
    manifest = {"schema_version": 2, "operation": "explicit_MIM_geometry_reference_view", "source": str(source.resolve()), "source_sha256": hashlib.sha256(original).hexdigest(), "destination": str(destination.resolve()), "destination_sha256": hashlib.sha256(output.encode()).hexdigest(), "required_lvs_option": {"scale": "true", "convert_subckts": "true", "schematic_simplify": "true"}, "mapping": mappings, "warning": "LVS ONLY. Preserve original circuit for ngspice, hierarchy probes and PEX simulation. No ideal capacitor is silently treated as a physical device. Qualified for the two MIM models and integer parallel m; this does not certify arbitrary PCell geometry, PEX accuracy, statistical equivalence, or full circuit layout."}
    mapping_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+"\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--mapping", type=Path, required=True)
    args = parser.parse_args()
    result = write_mim_reference_view(args.source, args.destination, args.mapping)
    print(json.dumps({"mapped_MIM": len(result["mapping"])}, ensure_ascii=False))
