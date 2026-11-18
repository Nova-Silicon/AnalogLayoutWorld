"""LVS-only geometry views of individually qualified physical resistors.

This does not change the simulated circuit, electrical models or dimensions.
The fixed-width family name represents the explicit original W to the reader.
"""

import math
import re


SOURCE_MODEL = "sky130_fd_pr__res_high_po"
GEOMETRY_MODEL = "sky130_fd_pr__res_high_po_0p35"
QUALIFIED_VIEWS = {
    "high_po_0p35_literal_um": (SOURCE_MODEL, GEOMETRY_MODEL, 0.35),
    "xhigh_po_0p69_literal_um": (
        "sky130_fd_pr__res_xhigh_po", "sky130_fd_pr__res_xhigh_po_0p69", 0.69,
    ),
}


def resistor_reference_view(
    text: str, view: str = "high_po_0p35_literal_um"
) -> tuple[str, list[dict]]:
    if view not in QUALIFIED_VIEWS:
        raise ValueError(f"Unknown LVS resistor geometry view: {view!r}")
    source_model, geometry_model, width_um = QUALIFIED_VIEWS[view]
    lines = text.splitlines(keepends=True)
    scope = []
    definitions = set()
    instances = set()
    mappings = []
    for index, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or stripped.startswith("*"):
            continue
        start = re.match(r"\s*\.subckt\s+(\S+)", line, re.I)
        if start:
            name = start[1].casefold()
            if name in {source_model, geometry_model}:
                raise ValueError("Reference must not redefine the PDK resistor model")
            key = (tuple(scope), name)
            if key in definitions:
                raise ValueError("Duplicate subcircuit definition")
            definitions.add(key)
            scope.append(name)
            continue
        end = re.match(r"\s*\.ends\b(?:[ \t]+([^$;*\s]+))?", line, re.I)
        if end:
            if not scope or (end[1] and end[1].casefold() != scope[-1]):
                raise ValueError("Unmatched .ends")
            scope.pop()
            continue
        instance = re.match(r"\s*([A-Za-z]\S*)\s+", line)
        if instance:
            key = (tuple(scope), instance[1].casefold())
            if key in instances:
                raise ValueError("Duplicate instance name in subcircuit")
            instances.add(key)
        if not re.search(r"\b" + source_model + r"\b", line, re.I):
            continue
        if not scope:
            raise ValueError("Resistor must be inside a subcircuit")
        if index + 1 < len(lines) and lines[index + 1].lstrip().startswith("+"):
            raise ValueError("Explicit resistor normalization required for continuation")
        match = re.fullmatch(
            r"([ \t]*)(X\S+)\s+(\S+)\s+(\S+)\s+(\S+)\s+("
            + source_model
            + r")\s+([^\n]+)(\n?)",
            line,
            re.I,
        )
        if not match:
            raise ValueError("Expected a three-terminal physical resistor X instance")
        indent, name, p, n, bulk, model, parameters, newline = match.groups()
        entries = re.findall(r"(\w+)\s*=\s*([^\s]+)", parameters)
        pairs = {key.casefold(): value for key, value in entries}
        if (len(pairs) != len(entries) or not {"w", "l"} <= pairs.keys()
                or pairs.keys() - {"w", "l", "m", "mult"}
                or re.sub(r"\w+\s*=\s*[^\s]+", "", parameters).strip()):
            raise ValueError("Require explicit literal W/L and optional m/mult")
        try:
            values = {key: float(value) for key, value in pairs.items()}
        except ValueError as exc:
            raise ValueError("Only literal resistor geometry is supported") from exc
        if not all(math.isfinite(value) and value > 0 for value in values.values()):
            raise ValueError("Resistor parameters must be positive and finite")
        if not math.isclose(values["w"], width_um, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"This view is qualified only for W={width_um:g} um")
        if values.get("m", 1.0) != 1:
            raise ValueError("Only resistor multiplicity m=1 is qualified")
        if values.get("mult", 1.0) != 1:
            raise ValueError("Nondefault statistical mult is not qualified")
        # Keep L, m and mult spellings. Only W's representation changes.
        retained = " ".join(f"{key}={value}" for key, value in entries
                            if key.casefold() != "w")
        replacement = f"{indent}{name} {p} {n} {bulk} {geometry_model} {retained}{newline}"
        lines[index] = replacement
        mappings.append({
            "source_instance": name,
            "subcircuit_path": list(scope),
            "nodes_preserved": [p, n, bulk],
            "source_model": model,
            "geometry_model": geometry_model,
            "w_um": values["w"],
            "l_um": values["l"],
            "m": values.get("m", 1.0),
            "original_statement": line.rstrip(),
            "geometry_statement": replacement.rstrip(),
        })
    if scope:
        raise ValueError("Unclosed subcircuit")
    return "".join(lines), mappings
