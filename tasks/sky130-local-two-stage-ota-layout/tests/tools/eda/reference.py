"""Lossless instance-name view for the installed SKY130 KLayout LVS reader.

The reader infers a primitive from the first character after X. This helper
renames *known supported model* X instances only; nodes, model, parameters,
subcircuit names and the original simulation netlist remain untouched.

MIM simulation-wrapper -> geometry A/P translation is intentionally separate:
it changes the reference representation and is not a lossless name rewrite.
"""
from pathlib import Path
import argparse
import hashlib
import json
import re


DEFAULT_DECK = Path("/opt/analog-layout/pdks/sky130/klayout/sky130.lvs")


def supported_model_primitives(deck_text):
    match = re.search(r"DEVICE_LIST\s*=\s*\[(.*?)\]\.freeze", deck_text, re.S)
    if not match:
        raise ValueError("Cannot identify the installed deck's supported DEVICE_LIST")
    models = re.findall(r'"([^"]+)"\.upcase', match[1])
    result = {}
    for model in models:
        suffix = model.lower().removeprefix("sky130_fd_pr__")
        if re.match(r"(?:special_)?[np]fet_", suffix):
            result[model.casefold()] = "M"
        elif re.match(r"(?:npn|pnp)_", suffix):
            result[model.casefold()] = "Q"
        elif suffix.startswith("res_"):
            result[model.casefold()] = "R"
        elif suffix.startswith(("model__cap_", "cap_")):
            result[model.casefold()] = "C"
    return result


def normalize_reference(text, model_primitives):
    """Return (new_text, mappings, unsupported_x_models), scoped by subckt."""
    lines = text.splitlines(keepends=True)
    logical = []
    for line_no, line in enumerate(lines):
        if re.match(r"\s*\+", line) and logical:
            logical[-1][2] += " " + re.sub(r"^\s*\+", "", line).strip()
        else:
            logical.append([line_no, line, line.strip()])
    scoped = []
    scope = []
    names = {}
    for line_no, physical, statement in logical:
        subckt = re.match(r"(?i)\.subckt\s+(\S+)", statement)
        if subckt:
            scope.append(subckt[1])
        end = re.match(r"(?i)\.ends\b(?:[ \t]+([^$;*\s]+))?", statement)
        if end:
            if not scope or (end[1] and end[1].casefold() != scope[-1].casefold()):
                raise ValueError(f"Unmatched .ends at line {line_no + 1}")
            scope.pop()
        match = re.match(r"([Xx]\S+)\s+", statement)
        if not match:
            continue
        name = match[1]
        scope_path = tuple(scope)
        key = (tuple(part.casefold() for part in scope_path), name.casefold())
        if key in names:
            raise ValueError(f"Duplicate instance {'/'.join(scope) or '<top>'}/{name}")
        names[key] = line_no
        tokens = statement.split()
        models = [token for token in tokens[1:] if token.casefold().startswith("sky130_fd_pr__")]
        if len(models) != 1:
            continue
        scoped.append((line_no, scope_path, name, models[0]))
    if scope:
        raise ValueError(f"Unclosed .subckt {'/'.join(scope)}")
    mappings, unsupported = [], []
    for line_no, scope_path, name, model in scoped:
        scope_key = tuple(part.casefold() for part in scope_path)
        scope_name = scope_path[-1] if scope_path else "<top>"
        primitive = model_primitives.get(model.casefold())
        if primitive is None:
            unsupported.append({"subcircuit": scope_name, "subcircuit_path": list(scope_path), "instance": name, "model": model, "line_1based": line_no + 1})
            continue
        if name[1:2].upper() == primitive:
            continue
        new_name = "X" + primitive + name[1:]
        if (scope_key, new_name.casefold()) in names:
            index = 1
            while (scope_key, f"X{primitive}_ALB_{index:04d}".casefold()) in names:
                index += 1
            new_name = f"X{primitive}_ALB_{index:04d}"
        names[(scope_key, new_name.casefold())] = line_no
        lines[line_no] = re.sub(r"^(\s*)" + re.escape(name) + r"(?=\s)", lambda m: m[1] + new_name, lines[line_no], count=1)
        mappings.append({"subcircuit": scope_name, "subcircuit_path": list(scope_path), "original_instance": name, "normalized_instance": new_name, "model": model, "primitive": primitive, "line_1based": line_no + 1, "changed": ["instance_name_only"]})
    return "".join(lines), mappings, unsupported


def write_normalized_reference(source, destination, mapping_path, deck=DEFAULT_DECK):
    if destination.exists() or mapping_path.exists():
        raise ValueError("Refuse to overwrite existing reference or provenance")
    source_bytes = source.read_bytes()
    deck_bytes = deck.read_bytes()
    text, mapping, unsupported = normalize_reference(source_bytes.decode(), supported_model_primitives(deck_bytes.decode()))
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(text)
    manifest = {"schema_version": 1, "operation": "supported_model_instance_names_only", "source": str(source.resolve()), "source_sha256": hashlib.sha256(source_bytes).hexdigest(), "normalized": str(destination.resolve()), "normalized_sha256": hashlib.sha256(text.encode()).hexdigest(), "deck": str(deck), "deck_sha256": hashlib.sha256(deck_bytes).hexdigest(), "mappings": mapping, "unsupported_x_models": unsupported, "unchanged_semantics": ["node_order", "model_names", "parameter_text", "subcircuit_names"], "warning": "Unsupported models are preserved and reported; names-only normalization does not establish their LVS compatibility."}
    mapping_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    return manifest


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source", type=Path)
    parser.add_argument("destination", type=Path)
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--deck", type=Path, default=DEFAULT_DECK)
    args = parser.parse_args()
    result = write_normalized_reference(args.source, args.destination, args.mapping, args.deck)
    print(json.dumps({"renamed": len(result["mappings"]), "unsupported_models": result["unsupported_x_models"]}, ensure_ascii=False))
