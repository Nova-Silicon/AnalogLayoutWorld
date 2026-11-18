"""Fixed DUT reference core area, independent of EDA tools and catalog code.

Bare W/L values follow the reviewed task convention of micrometres; suffixed
dimensions are SI values converted to micrometres. Only the specified top and
its reachable subcircuits contribute. External bench statements are ignored
and includes are never opened. Unknown reachable devices are errors.

This sums MOS channels, resistor bodies, MIM plates and BJT emitters, not their
physical footprint union. Different layers can share an XY projection, so the
reference-area/bounding-box ratio is positive and finite but is not capped at 1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
import re


SCORING_VERSION = "device-area-v2"
AREA_UTILIZATION_DEFINITION = "fixed_device_effective_area_over_manufacturing_bbox"

# Explicitly reviewed models, not a prefix-based fallback for future devices.
_MOS = frozenset({
    "sky130_fd_pr__nfet_01v8", "sky130_fd_pr__pfet_01v8",
    "sky130_fd_pr__nfet_01v8_lvt", "sky130_fd_pr__pfet_01v8_lvt",
    "sky130_fd_pr__nfet_05v0_nvt",
})
_RESISTORS = {
    "sky130_fd_pr__res_generic_po": None,
    "sky130_fd_pr__res_high_po": None,
    "sky130_fd_pr__res_high_po_0p35": 0.35,
    "sky130_fd_pr__res_high_po_0p69": 0.69,
    "sky130_fd_pr__res_high_po_1p41": 1.41,
    "sky130_fd_pr__res_high_po_5p73": 5.73,
    "sky130_fd_pr__res_xhigh_po": None,
    "sky130_fd_pr__res_xhigh_po_0p35": 0.35,
    "sky130_fd_pr__res_xhigh_po_0p69": 0.69,
    "sky130_fd_pr__res_xhigh_po_1p41": 1.41,
    "sky130_fd_pr__res_generic_m1": None,
}
_MIM = frozenset({"sky130_fd_pr__cap_mim_m3_1", "sky130_fd_pr__cap_mim_m3_2"})
_BJT = {
    "sky130_fd_pr__npn_05v5_w1p00l1p00": (1.0, 1.0),
    "sky130_fd_pr__pnp_05v5_w0p68l0p68": (0.68, 0.68),
}
_MODELS = _MOS | _RESISTORS.keys() | _MIM | _BJT.keys()
_MOS_ANNOTATIONS = frozenset({"ad", "as", "pd", "ps", "nrd", "nrs", "sa", "sb", "sd"})
_NUMBER = re.compile(r"([+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?)([a-zA-Z]*)\Z")
_SUFFIXES = {"": 1.0, "t": 1e12, "g": 1e9, "meg": 1e6, "k": 1e3,
             "m": 1e-3, "u": 1e-6, "n": 1e-9, "p": 1e-12, "f": 1e-15}
_PARAMETER = re.compile(
    r"([a-zA-Z_]\w*)\s*=\s*(\{[^{}]*\}|'[^']*'|\"[^\"]*\"|[^\s]+)"
)


@dataclass
class _Device:
    name: str
    card: str
    nodes: list[str]
    model: str
    parameters: dict[str, str]
    line: int


@dataclass
class _Circuit:
    name: str
    ports: list[str]
    devices: list[_Device] = field(default_factory=list)
    names: set[str] = field(default_factory=set)
    directives: list[str] = field(default_factory=list)


def _without_comment(line: str) -> str:
    quote = None
    braces = 0
    for index, char in enumerate(line):
        if quote:
            if char == quote:
                quote = None
        elif char in "'\"":
            quote = char
        elif char == "{":
            braces += 1
        elif char == "}":
            braces -= 1
        elif char in ";$" and braces == 0:
            return line[:index].strip()
    return line.strip()


def _logical_lines(text: str):
    current, start = "", 0
    for number, raw in enumerate(text.splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith("*"):
            continue
        line = _without_comment(raw)
        if not line:
            continue
        if line.startswith("+"):
            if not current:
                raise ValueError(f"L{number}: continuation without a statement")
            current += " " + line[1:].strip()
        else:
            if current:
                yield start, current
            current, start = line, number
    if current:
        yield start, current


def _parameters(text: str, line: int) -> dict[str, str]:
    values = {}
    position = 0
    while position < len(text):
        match = _PARAMETER.match(text, position)
        if match is None:
            raise ValueError(f"L{line}: invalid parameter syntax near {text[position:]!r}")
        key, value = match.groups()
        key = key.casefold()
        if key in values:
            raise ValueError(f"L{line}: duplicate parameter {key}")
        values[key] = value
        position = match.end()
        if position < len(text) and not text[position].isspace():
            raise ValueError(f"L{line}: missing parameter separator")
        while position < len(text) and text[position].isspace():
            position += 1
    return values


def _split_statement(text: str, line: int):
    assignment = re.search(r"(?:^|\s)([a-zA-Z_]\w*)\s*=", text)
    marker = re.search(r"\bparams\s*:", text, re.I)
    cut = assignment.start(1) if assignment else len(text)
    if marker and marker.start() < cut:
        cut = marker.start()
        tail = text[marker.end():].strip()
    else:
        tail = text[cut:].strip()
    return text[:cut].split(), _parameters(tail, line), marker is not None


def _parse(text: str) -> dict[str, _Circuit]:
    circuits, stack = {}, []
    active = None
    for line, statement in _logical_lines(text):
        head = statement.split(None, 1)[0].casefold()
        if head == ".subckt":
            words, parameters, marker = _split_statement(statement, line)
            if len(words) < 3:
                raise ValueError(f"L{line}: subcircuit needs a name and ports")
            if parameters or marker:
                raise ValueError(f"L{line}: parameterized subcircuit definitions are unsupported")
            name, ports = words[1], words[2:]
            key = name.casefold()
            if key in circuits or key in _MODELS:
                raise ValueError(f"L{line}: duplicate or reserved subcircuit name {name}")
            if len({p.casefold() for p in ports}) != len(ports):
                raise ValueError(f"L{line}: duplicate subcircuit port")
            stack.append(active)
            active = _Circuit(name, ports)
            circuits[key] = active
        elif head == ".ends":
            words = statement.split()
            if active is None or not stack:
                raise ValueError(f"L{line}: .ends without .subckt")
            if len(words) > 2 or (len(words) == 2 and words[1].casefold() != active.name.casefold()):
                raise ValueError(f"L{line}: .ends does not match {active.name}")
            active = stack.pop()
        elif active is None:
            # The caller supplies the fixed DUT text, not a bench include tree.
            continue
        elif head.startswith("."):
            active.directives.append(f"L{line}: {statement}")
        else:
            words, parameters, _ = _split_statement(statement, line)
            if len(words) < 4:
                raise ValueError(f"L{line}: incomplete device statement")
            name = words[0]
            if name.casefold() in active.names:
                raise ValueError(f"L{line}: duplicate device instance {name}")
            active.names.add(name.casefold())
            active.devices.append(_Device(name, name[0].upper(), words[1:-1], words[-1], parameters, line))
    if stack or active is not None:
        raise ValueError(f"Unclosed subcircuit {active.name if active else '<unknown>'}")
    return circuits


def _number(value: str, label: str, *, dimension: bool = False,
            integer: bool = False, allow_zero: bool = False) -> float:
    match = _NUMBER.fullmatch(value)
    if match is None:
        raise ValueError(f"{label}: expected a literal number, got {value!r}")
    suffix = match[2].casefold()
    if suffix not in _SUFFIXES or (suffix and not dimension):
        raise ValueError(f"{label}: unsupported units in {value!r}")
    number = float(match[1])
    if dimension and suffix:
        number *= _SUFFIXES[suffix] * 1e6
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ValueError(f"{label}: expected a {'nonnegative' if allow_zero else 'positive'} finite number")
    if integer and not number.is_integer():
        raise ValueError(f"{label}: only positive integer multiplicity/finger count is qualified")
    return number


def _finite_positive(value: object, label: str) -> float:
    try:
        valid = type(value) in (int, float) and math.isfinite(value) and value > 0
    except OverflowError:
        valid = False
    if not valid:
        raise ValueError(f"{label} must be positive and finite")
    return value


def _leaf(device: _Device, prefix: str, hierarchy_m: float) -> dict:
    model, p = device.model.casefold(), device.parameters
    label = f"L{device.line} {prefix + device.name}"
    if model in _MOS:
        kind, pins, cards = "MOS", 4, {"X", "M"}
        allowed = {"w", "l", "m", "mult", "nf"} | _MOS_ANNOTATIONS
    elif model in _RESISTORS:
        kind = "R"
        if model.endswith("__res_generic_m1"):
            pins, cards = 2, {"R"}
        else:
            pins, cards = (2 if model.endswith("__res_generic_po") else 3), {"X"}
        allowed = {"w", "l", "m", "mult"}
    elif model in _MIM:
        kind, pins, cards, allowed = "C", 2, {"X"}, {"w", "l", "m", "mult", "mf"}
    elif model in _BJT:
        kind, cards, allowed = "BJT", {"X", "Q"}, {"m", "mult"}
        pins = 4 if model.startswith("sky130_fd_pr__npn_") else 3
    else:
        raise ValueError(f"{label}: unsupported or ideal device/model {device.model}")
    if device.card not in cards or len(device.nodes) != pins:
        raise ValueError(f"{label}: unsupported card or terminal count for {device.model}")
    if set(p) - allowed:
        raise ValueError(f"{label}: unsupported parameters {sorted(set(p) - allowed)}")
    instance_m = _number(p.get("m", "1"), label + " m", integer=True)
    mult = _number(p.get("mult", "1"), label + " mult")
    if kind in {"R", "BJT"} and mult != 1:
        raise ValueError(f"{label}: nonunit mult is not qualified for {kind}")
    if kind == "C":
        _number(p.get("mf", "1"), label + " mf")
    if kind == "BJT":
        w, length = _BJT[model]
        basis = "bjt_emitter"
    else:
        fixed_width = _RESISTORS[model] if kind == "R" else None
        if "w" not in p and fixed_width is None:
            raise ValueError(f"{label}: missing w")
        if "l" not in p:
            raise ValueError(f"{label}: missing l")
        w = _number(p["w"], label + " w", dimension=True) if "w" in p else fixed_width
        length = _number(p["l"], label + " l", dimension=True)
        if fixed_width is not None and not math.isclose(w, fixed_width, rel_tol=0, abs_tol=1e-12):
            raise ValueError(f"{label}: width disagrees with fixed-width model")
        basis = {"MOS": "mos_channel", "R": "resistor_body", "C": "mim_plate"}[kind]
    m = _finite_positive(hierarchy_m * instance_m, label + " combined m")
    area = _finite_positive(w * length * m, label + " reference area")
    row = {"instance": prefix + device.name, "model": device.model, "kind": kind,
           "area_basis": basis, "w_um": w, "l_um": length,
           "instance_m": instance_m, "hierarchy_m": hierarchy_m, "m": m,
           "parameters": dict(p), "effective_area_um2": area}
    if kind == "MOS":
        row["w_total_um"] = w
        row["nf"] = _number(p.get("nf", "1"), label + " nf", integer=True)
        for key in _MOS_ANNOTATIONS & p.keys():
            value = p[key]
            # Reviewed parasitic expressions do not affect W/L or multiplicity.
            if not ((value.startswith("'") and value.endswith("'"))
                    or (value.startswith('"') and value.endswith('"'))
                    or (value.startswith("{") and value.endswith("}"))):
                _number(value, label + " " + key, dimension=True, allow_zero=True)
    return row


def floating_ports(text: str, top: str) -> list[str]:
    """Return ``top`` ports whose net reaches no device or subcircuit terminal.

    Uses this module's reference parser. Connectivity is checked only among the
    statements directly inside ``top``: a port wired to any instance terminal
    counts as connected, even if that child pin is itself unused (conservative).
    """
    if not isinstance(text, str) or not isinstance(top, str) or not top.strip():
        raise ValueError("text and a nonempty top name must be strings")
    circuit = _parse(text).get(top.casefold())
    if circuit is None:
        raise ValueError(f"Missing top subcircuit {top}")
    used = {node.casefold() for device in circuit.devices for node in device.nodes}
    return [port for port in circuit.ports if port.casefold() not in used]


def reference_area(text: str, top: str) -> dict:
    """Return the reviewed fixed DUT area; reject unsupported/ambiguous inputs.

    Physical multiplicity m (including hierarchy m) must be a positive integer.
    MOS nf already partitions total W; reviewed mult/mf parameters are not extra
    physical copies. Known non-area MOS parasitic expressions are kept opaque.
    """
    if not isinstance(text, str) or not isinstance(top, str) or not top.strip():
        raise ValueError("text and a nonempty top name must be strings")
    circuits = _parse(text)
    if top.casefold() not in circuits:
        raise ValueError(f"Missing top subcircuit {top}")
    rows, names = [], set()

    def walk(name: str, prefix: str, multiplier: float, ancestors: set[str]):
        key = name.casefold()
        if key in ancestors:
            raise ValueError(f"Recursive subcircuit hierarchy at {prefix + name}")
        circuit = circuits[key]
        if circuit.directives:
            raise ValueError("Unsupported/parameterized DUT directive: " + circuit.directives[0])
        for device in circuit.devices:
            child = device.model.casefold()
            if device.card == "X" and child in circuits:
                if len(device.nodes) != len(circuits[child].ports):
                    raise ValueError(f"L{device.line}: subcircuit terminal count mismatch")
                if set(device.parameters) - {"m"}:
                    raise ValueError(f"L{device.line}: parameterized hierarchy is unsupported")
                m = _number(device.parameters.get("m", "1"), prefix + device.name + " m", integer=True)
                effective_m = _finite_positive(multiplier * m, "Hierarchy multiplicity")
                walk(child, prefix + device.name + "/", effective_m, ancestors | {key})
            else:
                row = _leaf(device, prefix, multiplier)
                if row["instance"].casefold() in names:
                    raise ValueError("Duplicate flattened device instance " + row["instance"])
                names.add(row["instance"].casefold())
                rows.append(row)

    walk(top, "", 1.0, set())
    try:
        totals = {kind: math.fsum(row["effective_area_um2"] for row in rows if row["kind"] == kind)
                  for kind in ("MOS", "R", "C", "BJT")}
        total = math.fsum(totals.values())
    except OverflowError as error:
        raise ValueError("Reference area sum is not finite") from error
    _finite_positive(total, "Fixed reference area")
    return {
        "scoring_version": SCORING_VERSION,
        "area_utilization_definition": AREA_UTILIZATION_DEFINITION,
        "fixed_effective_area_um2": total,
        "effective_area_basis": (
            "Sum of fixed reference MOS W_total*L, resistor body W*L, MIM plate W*L, "
            "and model-defined BJT emitter W*L, each times instance and hierarchy m once. "
            "nf/mult/mf are not extra multipliers. This is core area, not footprint union."
        ),
        "effective_area_devices": rows,
        "kind_totals_um2": totals,
    }


def area_utilization(reference: dict, total_area_um2: float) -> dict:
    """Return Aref/bbox unchanged, including ratios greater than one."""
    if not isinstance(reference, dict):
        raise ValueError("reference must be an object")
    if reference.get("scoring_version", SCORING_VERSION) != SCORING_VERSION:
        raise ValueError("Reference scoring_version differs from device-area-v2")
    effective = _finite_positive(reference.get("fixed_effective_area_um2"), "Fixed reference area")
    total = _finite_positive(total_area_um2, "Total area")
    raw = _finite_positive(effective / total, "Reference-area ratio")
    return {**reference, "scoring_version": SCORING_VERSION,
            "area_utilization_definition": AREA_UTILIZATION_DEFINITION,
            "effective_area_um2": effective, "area_um2": total,
            "raw_area_utilization": raw, "area_utilization": raw,
            "area_utilization_status": "measured"}
