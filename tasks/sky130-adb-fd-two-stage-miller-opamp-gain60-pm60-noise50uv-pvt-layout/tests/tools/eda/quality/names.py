"""Resolve annotation names (current circuit.spice) to lvsdb reference names.

The LVS reference netlist is the *normalized* netlist of the run (see
``reference-name-map.json``: e.g. ``XREF -> XMREF``, ``XCBOOTSTRAP ->
CCBOOTSTRAP``).  KLayout's SKY130 SPICE reader then drops the element letter
(``CCMILLER -> CMILLER``) and, for X-cards that are devices, the ``X`` plus the
following element letter (``XMP1 -> P1``, ``XR2a_0 -> 2A_0``, ``XQ1 -> 1``).
Hierarchy is flattened with ``.`` separators and the subcircuit instance loses
its leading ``X`` (``XAMP.XM1 -> AMP.1``).  Old netlists sometimes expanded an
``m=8`` device into ``XQ2__unit1..8``; those are resolved as one logical device.

Resolution tries, in order: the run's own name map, the KLayout stripping rule
(only when the second letter really is an element letter) and plain ``X``
stripping, and accepts a candidate only if its device class equals the class
the schematic gives that instance.  Reference names shared by two devices of
different classes (XMN8 / XRN8 -> N8) carry a '#<class>' suffix.  Anything
else is reported as unresolved -- never guessed.
"""

from __future__ import annotations

import json
import math
import re
from pathlib import Path

_CLASS_LETTER = {"M": "MOS", "R": "RES", "C": "CAP", "Q": "BJT", "D": "DIODE"}


def klayout_key(instance: str) -> str:
    s = instance.upper()
    if s.startswith("X") and len(s) > 2:
        return s[2:]
    return s[1:] if len(s) > 1 else s


def element_class(instance: str) -> str | None:
    s = instance.upper()
    if s.startswith("X") and len(s) > 1:
        return _CLASS_LETTER.get(s[1])
    return _CLASS_LETTER.get(s[:1])


def load_name_map(lvs_dir: Path) -> dict[str, list[str]]:
    p = Path(lvs_dir) / "reference-name-map.json"
    out: dict[str, list[str]] = {}
    if not p.exists():
        return out
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise ValueError(f"Malformed trusted reference-name map: {p}") from error
    for m in data.get("mappings", []):
        o, n = m.get("original_instance"), m.get("normalized_instance")
        if o and n:
            out.setdefault(o.upper(), []).append(n)
    return out


_ELEMENT_LETTERS = set(_CLASS_LETTER)


def model_class(model: str) -> str | None:
    """Device class of a SKY130 primitive model name (None: a subcircuit)."""
    m = model.lower()
    if not m.startswith("sky130_fd_pr__"):
        return None  # a subcircuit call
    if "fet" in m:
        return "MOS"
    if "res" in m:
        return "RES"
    if "cap" in m:
        return "CAP"
    if "pnp" in m or "npn" in m:
        return "BJT"
    if "diode" in m:
        return "DIODE"
    return None


def parse_schematic(text: str) -> tuple[dict, dict]:
    """-> ({subckt: {INSTANCE: (class|None, model)}}, {subckt: ports}) of a
    SPICE netlist (continuation lines joined, comments dropped)."""
    lines, cur = [], ""
    for raw in text.splitlines():
        t = raw.strip()
        if not t or t.startswith("*"):
            continue
        if t.startswith("+"):
            cur += " " + t[1:]
            continue
        if cur:
            lines.append(cur)
        cur = t
    if cur:
        lines.append(cur)
    subs, ports, now = {"": {}}, {}, ""
    for ln in lines:
        tok = ln.split()
        head = tok[0].lower()
        if head == ".subckt":
            now = tok[1].upper()
            subs.setdefault(now, {})
            ports[now] = tok[2:]
            continue
        if head == ".ends":
            now = ""
            continue
        if head.startswith("."):
            continue
        plain = [x for x in tok[1:] if "=" not in x]
        if not plain:
            continue
        inst = tok[0].upper()
        letter = inst[0]
        if letter == "X":
            model = plain[-1]
            subs[now][inst] = (model_class(model), model.upper())
        elif letter in _CLASS_LETTER:
            model = plain[-1] if len(plain) > 2 else ""
            subs[now][inst] = (_CLASS_LETTER[letter], model.upper())
    return subs, ports


def schematic_classes(netlist_path: Path):
    """Callable name -> device class, from the task's current circuit.spice
    (dotted hierarchical names follow subcircuit instances)."""
    p = Path(netlist_path)
    if not p.exists():
        return lambda name: None
    subs, _ = parse_schematic(p.read_text(encoding="utf-8", errors="replace"))
    used = {m for d in subs.values() for c, m in d.values() if c is None}
    tops = [k for k in subs if k and k not in used]

    def lookup(name: str) -> str | None:
        parts = name.upper().split(".")
        for top in tops + [""]:
            scope = top
            ok = True
            for inst in parts[:-1]:
                ent = subs.get(scope, {}).get(inst)
                if not ent or ent[0] is not None:
                    ok = False
                    break
                scope = ent[1]
            if ok and parts[-1] in subs.get(scope, {}):
                return subs[scope][parts[-1]][0]
        hits = {d[parts[-1]][0] for d in subs.values() if parts[-1] in d}
        return hits.pop() if len(hits) == 1 else None

    return lookup


class Resolver:
    """Map annotation device/net names to reference device keys.

    Reference keys are the KLayout expanded names, with '#<class>' appended
    when two reference devices share a name (model.unique_ref_keys).  Every
    candidate must have the expected device class; the class comes from the
    task's schematic, else from the normalized name in the run's name map,
    else from an element letter in the name.  Nothing is guessed: a name with
    no candidate of the right class, or with several, is unresolved."""

    def __init__(self, ref_devices: dict[str, str], ref_nets: set[str],
                 name_map: dict[str, list[str]], schematic=None):
        # ref_devices: {unique key: class (MOS/RES/CAP/BJT/DIODE)}
        self.ref_devices = ref_devices
        self.ref_nets = ref_nets
        self.name_map = name_map
        self.schematic = schematic or (lambda name: None)
        self.by_base: dict[str, list[str]] = {}
        for k in ref_devices:
            self.by_base.setdefault(k.split("#")[0], []).append(k)

    @staticmethod
    def _path(parts: list[str]) -> list[str]:
        return [p.upper()[1:] if p.upper().startswith("X") else p.upper() for p in parts]

    def expected_class(self, name: str) -> str | None:
        c = self.schematic(name)
        if c:
            return c
        leaf = name.split(".")[-1].upper()
        for norm in self.name_map.get(leaf, []):
            c = element_class(norm)
            if c:
                return c
        if leaf.startswith("X"):
            return _CLASS_LETTER.get(leaf[1:2]) if len(leaf) > 2 else None
        return _CLASS_LETTER.get(leaf[:1])

    def _hits(self, full: str) -> list[str]:
        hits = list(self.by_base.get(full, []))
        if not hits:
            hits = sorted(k for b, ks in self.by_base.items() if b.startswith(full + "__UNIT") for k in ks)
        return sorted(hits)

    def device(self, name: str) -> tuple[list[str], str]:
        parts = name.split(".")
        path, leaf = self._path(parts[:-1]), parts[-1].upper()
        want = self.expected_class(name)
        cands: list[tuple[str, str]] = []
        for norm in self.name_map.get(leaf, []):
            cands.append((klayout_key(norm), f"name-map {leaf}->{norm}"))
        if leaf.startswith("X") and leaf[1:2] in _ELEMENT_LETTERS and len(leaf) > 2:
            cands.append((leaf[2:], "klayout rule (X + element letter dropped)"))
        elif not leaf.startswith("X") and leaf[:1] in _ELEMENT_LETTERS and len(leaf) > 1:
            cands.append((leaf[1:], "klayout rule (element letter dropped)"))
        if leaf.startswith("X"):
            cands.append((leaf[1:], "X-strip rule (netlist normalised with an inserted element letter)"))
        notes = []
        for key, how in cands:
            full = ".".join(path + [key])
            hits = self._hits(full)
            if not hits:
                continue
            classes = {self.ref_devices[h] for h in hits}
            if want:
                hits = [h for h in hits if self.ref_devices[h] == want]
                if not hits:
                    notes.append(f"{full} exists only as {sorted(classes)} (expected {want})")
                    continue
            elif len(classes) > 1:
                notes.append(f"{full} is ambiguous {sorted(classes)} and the expected class is unknown")
                continue
            return hits, how + (f" [{want}]" if want else "")
        why = "; ".join(notes) if notes else "no reference device with that name (combined by LVS or absent)"
        return [], f"unresolved: {name}: {why}"

    def net(self, name: str) -> tuple[str | None, str]:
        parts = name.split(".")
        full = ".".join(self._path(parts[:-1]) + [parts[-1].upper()])
        if full in self.ref_nets:
            return full, "exact"
        return None, f"unresolved: no reference net {full}"


def stem(name: str) -> str:
    """Name stem for grouping split devices: XR2a_0 / XR2a_1 -> XR2A."""
    leaf = name.split(".")[-1].upper()
    return re.sub(r"(__UNIT\d+|_\d+)$", "", leaf)


def series_resistor_chains(text: str, top: str) -> list[dict]:
    """Prove literal, unbranched series chains in the compared reference.

    This is topology evidence, not a suffix-based alias rule. Internal nodes
    may touch only the A/B terminals of two compatible resistors; ports,
    substrate terminals and connections to any other element stop a chain.
    Unsupported parameters/hierarchy remain unqualified rather than guessed.
    The caller must additionally match the surviving native reference and
    its paired layout device, including model, terminals and dimensions.
    """
    from ..area_v2 import _leaf, _parse

    circuits = _parse(text)
    top_key = top.casefold()
    if top_key not in circuits:
        return []
    proofs = []

    def walk(key, prefix, aliases, ancestors):
        if key in ancestors:
            return
        circuit = circuits[key]
        if circuit.directives:
            return

        def net_name(node):
            node = node.upper()
            return aliases.get(node, prefix + node)

        protected = {port.upper() for port in circuit.ports} | {"0"}
        touches, resistors = {}, {}
        for device in circuit.devices:
            for index, node in enumerate(device.nodes):
                touches.setdefault(node.upper(), []).append((device.name.upper(), index))
            try:
                row = _leaf(device, "", 1.0)
            except ValueError:
                continue
            if row["kind"] != "R" or row["m"] != 1.0:
                continue
            nodes = [node.upper() for node in device.nodes]
            if nodes[0] == nodes[1]:
                continue
            resistors[device.name.upper()] = {
                "name": device.name.upper(), "nodes": nodes,
                "model": device.model.casefold(), "w_um": row["w_um"],
                "l_um": row["l_um"],
            }
        parents = {name: name for name in resistors}

        def find(name):
            while parents[name] != name:
                parents[name] = parents[parents[name]]
                name = parents[name]
            return name

        internal = set()
        for node, terminals in touches.items():
            if node in protected or len(terminals) != 2:
                continue
            (left, lt), (right, rt) = terminals
            if left == right or lt > 1 or rt > 1 or left not in resistors or right not in resistors:
                continue
            a, b = resistors[left], resistors[right]
            if (a["model"] != b["model"] or len(a["nodes"]) != len(b["nodes"])
                    or not math.isclose(a["w_um"], b["w_um"], rel_tol=1e-12, abs_tol=1e-12)
                    or a["nodes"][2:] != b["nodes"][2:]):
                continue
            parents[find(left)] = find(right)
            internal.add(node)
        components = {}
        for name in resistors:
            components.setdefault(find(name), []).append(resistors[name])
        for members in components.values():
            if len(members) < 2:
                continue
            endpoints = [node for member in members for node in member["nodes"][:2] if node not in internal]
            if len(endpoints) != 2 or endpoints[0] == endpoints[1]:
                continue  # cycles / ambiguous or branched components are not series chains
            names = sorted(prefix + member["name"] for member in members)
            proofs.append({
                "members": names,
                "native_member_keys": sorted(prefix + klayout_key(member["name"]) for member in members),
                "model": members[0]["model"], "w_um": members[0]["w_um"],
                "l_um": math.fsum(member["l_um"] for member in members),
                "endpoints": sorted(net_name(node) for node in endpoints),
                "bulk": net_name(members[0]["nodes"][2]) if len(members[0]["nodes"]) == 3 else None,
            })
        for device in circuit.devices:
            child_key = device.model.casefold()
            if device.card != "X" or child_key not in circuits:
                continue
            if device.parameters or len(device.nodes) != len(circuits[child_key].ports):
                continue
            child_aliases = {port.upper(): net_name(node)
                             for port, node in zip(circuits[child_key].ports, device.nodes)}
            child_prefix = prefix + device.name.upper()[1:] + "."
            walk(child_key, child_prefix, child_aliases, ancestors | {key})

    walk(top_key, "", {}, set())
    return proofs
