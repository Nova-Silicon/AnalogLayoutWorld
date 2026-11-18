"""Layout model of one trial: devices, nets and raw GDS layers.

Everything is derived from geometry and the LVS cross-reference, never from
cell names or the submission's hierarchy:

* devices come from the extracted (layout-side) netlist in report.lvsdb; their
  schematic names from the LVS device pairing; multi-finger devices that
  KLayout merged are split back into fingers via ``each_combined_abstract``;
* nets come from the extracted netlist, named by the LVS net pairing; their
  per-layer geometry from ``LayoutToNetlist.shapes_of_net``;
* poly/diff/tap/nwell and pin labels come from the flattened submission GDS.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, field
from pathlib import Path

import klayout.db as kdb

from . import layers as L
from .names import Resolver, load_name_map, schematic_classes, series_resistor_chains

UM = 1e-6  # KLayout device parameters in these lvsdb files are scaled by 1e6 (um * 1e6)


def _cls(dc) -> str:
    t = type(dc).__name__
    if "MOS" in t:
        return "MOS"
    if "Resistor" in t:
        return "RES"
    if "Capacitor" in t:
        return "CAP"
    if "BJT" in t:
        return "BJT"
    if "Diode" in t:
        return "DIODE"
    return "OTHER"


def _polarity(model: str) -> str | None:
    m = model.lower()
    if "pfet" in m or "pnp" in m:
        return "p"
    if "nfet" in m or "npn" in m:
        return "n"
    return None


def unique_ref_keys(items) -> list:
    """items: [(NAME, class, id)] of one reference circuit -> unique keys.
    A name used once keeps its name; a name shared by several devices gets
    '#<class>' and, if still shared, '#<class>#<k>' (k by device id)."""
    by_name = {}
    for name, cls, did in items:
        by_name.setdefault(name, []).append((cls, did))
    keys = []
    for name, cls, did in items:
        same = by_name[name]
        if len(same) == 1:
            keys.append(name)
            continue
        same_cls = sorted(i for c, i in same if c == cls)
        key = f"{name}#{cls}"
        if len(same_cls) > 1:
            key += f"#{same_cls.index(did)}"
        keys.append(key)
    return keys


def _box(b: kdb.DBox) -> tuple[float, float, float, float]:
    return (b.left, b.bottom, b.right, b.top)


@dataclass
class Finger:
    core: tuple  # channel / resistor body / MIM plate / emitter (um)
    full: tuple  # union of all terminal geometry of this part (um)
    orient: str | None  # 'V': gate poly / resistor body runs vertically; 'H': horizontally
    terms: list = field(default_factory=list)  # S/D strips (MOS) or heads (resistor) (um boxes)
    body_um2: float | None = None  # drawn resistor body area (poly resistors, see _resistor_bodies)
    src: str = "lvsdb device abstract"  # where core / full come from

    @property
    def center(self):
        x1, y1, x2, y2 = self.core
        return ((x1 + x2) / 2, (y1 + y2) / 2)

    @property
    def area(self):
        x1, y1, x2, y2 = self.full
        return max(0.0, (x2 - x1) * (y2 - y1))

    @property
    def term_span(self):
        """Box spanning the terminal shapes (resistor: its two heads, where
        the wires connect -- the geometry the lvsdb abstract provides)."""
        if not self.terms:
            return self.full
        xs1, ys1, xs2, ys2 = zip(*self.terms)
        return (min(xs1), min(ys1), max(xs2), max(ys2))


@dataclass
class Device:
    lid: int
    lname: str
    ref: str | None
    cls: str
    model: str
    polarity: str | None
    params: dict
    ref_params: dict
    fingers: list[Finger]
    terms: dict = field(default_factory=dict)  # terminal -> net key
    instance_path: tuple[int, ...] = ()

    @property
    def uid(self):
        """Physical occurrence identity; a device ID is local to its circuit.

        Combined abstracts/fingers remain parts of this same device. Two
        occurrences of a shared subcircuit must not share their identity.
        """
        return (self.instance_path, self.lid)

    @property
    def area(self):
        return sum(f.area for f in self.fingers)

    @property
    def center(self):
        a = self.area or 1.0
        return (sum(f.center[0] * f.area for f in self.fingers) / a,
                sum(f.center[1] * f.area for f in self.fingers) / a)

    @property
    def bbox(self):
        xs1, ys1, xs2, ys2 = zip(*(f.full for f in self.fingers))
        return (min(xs1), min(ys1), max(xs2), max(ys2))


@dataclass
class NetInfo:
    key: str
    lnet: object
    trans: object
    ref: str | None
    lname: str
    sources: list = field(default_factory=list)  # non-overlapping hierarchy roots: (net, transform)


class GeometryModel:
    """Explicit frozen-input adapter; no trial discovery or historical lookup."""

    def __init__(self, gds_path, lvsdb_path, task_path, task_name, geometry):
        self.task = task_name
        self.task_path = Path(task_path)
        self.dir = Path(lvsdb_path).parent
        self.gds_path = Path(gds_path)
        self.lvs_dir = Path(lvsdb_path).parent
        self.lvsdb_path = Path(lvsdb_path)
        self.status = {"lvs": "passed"}
        self.bbox = tuple(geometry["bbox_um"]) if geometry.get("bbox_um") else None
        self.bbox_area = geometry.get("area_um2")
        self.loaded = False

    # ------------------------------------------------------------------ loading
    def load(self):
        if self.loaded:
            return self
        self.layer_info = L.infer_metal_layers(self.lvsdb_path)
        lv = kdb.LayoutVsSchematic()
        lv.read(str(self.lvsdb_path))
        self.lvs = lv
        self.nl = lv.netlist()
        self.refnl = lv.reference
        self.xref = lv.xref()
        self.ly = lv.internal_layout()
        self.dbu = self.ly.dbu
        self._regions = {}
        self._layer_regions = {}
        self._pairs()
        self._load_gds()
        self._resistor_bodies()
        self.loaded = True
        return self

    def _resistor_bodies(self):
        """Poly resistors: replace the terminal-only geometry by the drawn body.

        The lvsdb device abstract of a resistor holds only its two terminal
        heads, so core = full = the box spanning the heads.  For a straight
        resistor that box covers the body; for a folded (serpentine) one it
        can cover just the narrow strip between the two ends.
        The LVS deck (eda/sky130_dummy_purge_20261103*.lvs) extracts every
        poly resistor from R = poly AND poly_res (66/13) minus diff / tap /
        ...; one R polygon per device part, touching both of its heads.  So
        core := bbox of the R polygon(s) touching both heads of the part,
        full := core + heads; orient: a rectangular body keeps the
        head-to-head direction (= current direction), a folded body takes
        its stripe direction (the longer total edge length).  Parts whose
        body is not found, and non-poly resistors (metal / diffusion), keep
        the terminal geometry (src says why)."""
        stats = {"body": 0, "terminal_heads": 0, "reasons": []}
        r_body = None
        e = 2  # dbu: the heads touch the body
        for d in self.devices:
            if d.cls != "RES":
                continue
            for f in d.fingers:
                f.src = "terminal heads (lvsdb device abstract)"
            if not any(k in d.model.lower() for k in ("res_generic_po", "res_high_po", "res_xhigh_po")):
                stats["terminal_heads"] += len(d.fingers)
                stats["reasons"].append(f"{d.ref or d.lname}: {d.model} is not a poly resistor")
                continue
            if r_body is None:
                r_body = ((self.gds["poly"] & self.gds["polyres"]) - self.gds["diff"] - self.gds["tap"]).merged()
            for f in d.fingers:
                body = kdb.Region()
                if len(f.terms) == 2:
                    a, b = (kdb.Region(kdb.Box(round(t[0] / self.dbu), round(t[1] / self.dbu), round(t[2] / self.dbu),
                                               round(t[3] / self.dbu)).enlarged(e, e)) for t in f.terms)
                    body = r_body.interacting(a).interacting(b)
                if body.is_empty():
                    stats["terminal_heads"] += 1
                    stats["reasons"].append(f"{d.ref or d.lname}: no poly AND 66/13 polygon touching both heads")
                    continue
                bb = body.bbox()
                core = kdb.DBox(bb.left * self.dbu, bb.bottom * self.dbu, bb.right * self.dbu, bb.top * self.dbu)
                full = kdb.DBox(*f.full) + core
                if not (body.count() == 1 and next(body.each()).is_box()):
                    hl = sum(abs(ed.dx()) for ed in body.edges().each() if ed.dy() == 0)
                    vl = sum(abs(ed.dy()) for ed in body.edges().each() if ed.dx() == 0)
                    f.orient = "H" if hl > vl else "V"
                f.core, f.full = _box(core), _box(full)
                f.body_um2 = body.area() * self.dbu * self.dbu
                f.src = "body"
                stats["body"] += 1
        self.resistor_geometry = stats

    def layer_region(self, metal: str):
        lname = self.layer_info["layers"].get(metal)
        if not lname:
            return None
        if lname not in self._layer_regions:
            self._layer_regions[lname] = self.lvs.layer_by_name(lname)
        return self._layer_regions[lname]

    def _ref_keys(self):
        """Unique key per reference device.  KLayout drops 'X' + element letter,
        so XMN8 (MOS) and XRN8 (resistor) both become 'N8'; such names get a
        class suffix ('N8#MOS', 'N8#RES') -- see unique_ref_keys()."""
        self._refkey = {}
        for c in self.refnl.each_circuit():
            items = [(d.expanded_name().upper(), _cls(d.device_class()), d.id()) for d in c.each_device()]
            for (name, cls, did), key in zip(items, unique_ref_keys(items)):
                self._refkey[(c.name, did)] = key

    def _rk(self, d) -> str:
        return self._refkey.get((d.circuit().name, d.id()), d.expanded_name().upper())

    def _pairs(self):
        self._ref_keys()
        cpairs = {}
        for cp in self.xref.each_circuit_pair():
            if cp.first():
                cpairs[cp.first().cell_index] = cp
        top = next(self.nl.each_circuit_top_down())
        self.top_name = top.name
        self.devices: list[Device] = []
        self.nets: dict[str, NetInfo] = {}
        self.ref_device_class: dict[str, str] = {}
        self.unmatched_layout_devices: list[Device] = []
        self.unmatched_ref_devices: list[str] = []
        self.xref_status = {}

        # A node is a physical occurrence of a circuit-local net. Reference
        # names are labels, never evidence that two nodes are connected.
        parents, occurrences = {}, {}

        def find(node):
            parents.setdefault(node, node)
            if parents[node] != node:
                parents[node] = find(parents[node])
            return parents[node]

        def union(a, b):
            a, b = find(a), find(b)
            if a != b:
                parents[b] = a

        def walk(circ, trans: kdb.DCplxTrans, ref_prefix: str, lay_prefix: str, path: tuple):
            cp = cpairs.get(circ.cell_index)
            dev_ref, net_ref = {}, {}
            if cp is not None:
                self.xref_status[circ.name] = str(cp.status())
                for dp in self.xref.each_device_pair(cp):
                    a, b = dp.first(), dp.second()
                    if a and b:
                        dev_ref[a.id()] = ref_prefix + self._rk(b)
                    elif b and not a:
                        self.unmatched_ref_devices.append(ref_prefix + self._rk(b))
                for np_ in self.xref.each_net_pair(cp):
                    a, b = np_.first(), np_.second()
                    if a and b:
                        net_ref[a.cluster_id] = ref_prefix + b.expanded_name().upper()
            for n in circ.each_net():
                ref = net_ref.get(n.cluster_id)
                key = ref if ref else f"~{lay_prefix}{n.expanded_name()}"
                node = (path, n.cluster_id)
                find(node)
                occurrences[node] = (key, n, trans, ref, lay_prefix + n.expanded_name())
            # Resolve these occurrence keys only after all real pin edges
            # have been traversed, including aliases through deeper cells.
            local_nodes = {n.cluster_id: (path, n.cluster_id) for n in circ.each_net()}
            for d in circ.each_device():
                dev = self._device(d, trans, dev_ref.get(d.id()), local_nodes, lay_prefix, path)
                (self.devices if dev.ref else self.unmatched_layout_devices).append(dev)
                if not dev.ref:
                    self.devices.append(dev)
            for sc in circ.each_subcircuit():
                ref_sc = None
                if cp is not None:
                    for sp in self.xref.each_subcircuit_pair(cp):
                        if sp.first() and sp.first().id() == sc.id() and sp.second():
                            ref_sc = sp.second().expanded_name().upper()
                child_ref_prefix = ref_prefix + (ref_sc + "." if ref_sc else f"?{sc.expanded_name()}.")
                child_path = path + (sc.id(),)
                for child_net in sc.circuit_ref().each_net():
                    for pin in child_net.each_pin():
                        parent_net = sc.net_for_pin(pin.pin_id())
                        if parent_net is not None:
                            union((path, parent_net.cluster_id), (child_path, child_net.cluster_id))
                walk(sc.circuit_ref(), trans * sc.trans, child_ref_prefix,
                     lay_prefix + sc.expanded_name() + "/", child_path)

        walk(top, kdb.DCplxTrans(), "", "", ())
        groups = {}
        for node in occurrences:
            groups.setdefault(find(node), []).append(node)
        self.net_aliases, self._net_port_names, self.ref_nets = {}, {}, set()
        canonical_nodes = {}
        for nodes in groups.values():
            # Prefer a named, shallow reference net. Preserve the old names
            # and iteration order for flat circuits.
            named = [node for node in nodes if occurrences[node][3]]
            primary = min(named or nodes, key=lambda node: len(node[0]))
            key, lnet, trans, ref, lname = occurrences[primary]
            if key in self.nets:
                raise ValueError(f"Distinct physical nets have the same qualified key: {key}")
            sources, source_paths = [], []
            for node in sorted(nodes, key=lambda item: len(item[0])):
                path = node[0]
                # shapes_of_net(..., recursive=True) already includes the
                # connected descendant geometry. Keep only ancestor roots;
                # distinct roots at the same depth can still contribute.
                if any(len(ancestor) < len(path) and path[:len(ancestor)] == ancestor
                       for ancestor in source_paths):
                    continue
                info = occurrences[node]
                sources.append((info[1], info[2]))
                source_paths.append(path)
            self.nets[key] = NetInfo(key, lnet, trans, ref, lname, sources)
            port_names = set()
            for node in nodes:
                alias, _, _, alias_ref, _ = occurrences[node]
                old = self.net_aliases.setdefault(alias, key)
                if old != key:
                    raise ValueError(f"Ambiguous qualified net alias: {alias}")
                canonical_nodes[node] = key
                if alias_ref:
                    self.ref_nets.add(alias_ref)
                    if not node[0]:
                        port_names.add(alias_ref.lower())
            self._net_port_names[key] = port_names
        for dev in self.devices:
            dev.terms = {terminal: canonical_nodes[node] for terminal, node in dev.terms.items()}
        # reference-side device classes for name resolution (unique keys)
        self._flatten_ref_names()
        self.dev_by_ref = {}
        for d in self.devices:
            if d.ref:
                self.dev_by_ref.setdefault(d.ref, d)
        self.resolver = Resolver(self.ref_device_class, self.ref_nets, load_name_map(self.lvs_dir),
                                 schematic_classes(self.task_path / "circuit.spice"))

    def _flatten_ref_names(self):
        """Collect reference device names including those inside subcircuits."""
        names = {}
        tops = list(self.refnl.each_circuit_top_down())
        if not tops:
            return

        def walk(c, prefix):
            for d in c.each_device():
                names[prefix + self._rk(d)] = _cls(d.device_class())
            for sc in c.each_subcircuit():
                walk(sc.circuit_ref(), prefix + sc.expanded_name().upper() + ".")

        walk(tops[0], "")
        self.ref_device_class = names

    def _device(self, d, trans, ref, net_ref, lay_prefix, instance_path=()) -> Device:
        dc = d.device_class()
        cls = _cls(dc)
        params = {p.name: d.parameter(p.name) for p in dc.parameter_definitions()}
        parts = [(d.device_abstract, d.trans)] + [
            (r.device_abstract, d.trans * r.trans) for r in d.each_combined_abstract()]
        fingers = []
        for ab, t in parts:
            cell = self.ly.cell(ab.cell_index())
            per_layer = []
            for li in self.ly.layer_indexes():
                bx = [(trans * t) * s.dbbox() for s in cell.shapes(li).each()]
                if bx:
                    per_layer.append(bx)
            if not per_layer:
                continue
            allb = [b for bl in per_layer for b in bl]
            full = kdb.DBox()
            for b in allb:
                full += b
            singles = [bl[0] for bl in per_layer if len(bl) == 1]
            pairs = [bl for bl in per_layer if len(bl) == 2]
            core = min(singles, key=lambda b: b.area()) if singles else full
            orient = None
            if cls in ("MOS", "RES") and pairs:
                a, b = pairs[0]
                dx = abs(a.center().x - b.center().x)
                dy = abs(a.center().y - b.center().y)
                if cls == "MOS":  # S/D strips left/right -> current along x -> poly vertical
                    orient = "V" if dx > dy else "H"
                else:  # resistor heads above/below -> body vertical
                    orient = "V" if dy > dx else "H"
            tboxes = [_box(b) for b in pairs[0]] if pairs else []
            fingers.append(Finger(_box(core), _box(full), orient, tboxes))
        terms = {}
        for td in dc.terminal_definitions():
            n = d.net_for_terminal(td.id())
            if n is not None:
                terms[td.name] = net_ref.get(n.cluster_id) or f"~{lay_prefix}{n.expanded_name()}"
        ref_params = {}
        if ref:
            ref_params = {}
        return Device(d.id(), lay_prefix + d.expanded_name(), ref, cls, dc.name,
                      _polarity(dc.name), params, ref_params, fingers, terms, instance_path)

    def _load_gds(self):
        g = kdb.Layout()
        g.read(str(self.gds_path))
        # Regions may retain references to source shapes in older KLayout
        # runtimes. Keep their owning layout alive for this model's lifetime.
        self.gds_layout = g
        tops = g.top_cells()
        top = next((c for c in tops if c.name.casefold() == self.top_name.casefold()), None)
        if top is None:
            raise ValueError("Passed LVS top is absent from the supplied GDS; no largest-cell fallback")
        self.gds_dbu = g.dbu

        def reg(layer, dt):
            li = g.find_layer(layer, dt)
            if li is None:
                return kdb.Region()
            r = kdb.Region(top.begin_shapes_rec(li))
            if abs(g.dbu - self.dbu) > 1e-12:
                r.transform(kdb.ICplxTrans(g.dbu / self.dbu))
            return r.merged()

        self.gds = {
            "poly": reg(66, 20), "diff": reg(65, 20), "tap": reg(65, 44), "nwell": reg(64, 20),
            "licon": reg(66, 44), "rpm": reg(86, 20), "urpm": reg(79, 20), "polyres": reg(66, 13),
            "capm": reg(89, 44), "cap2m": reg(97, 44),
        }
        texts = []
        for lix in g.layer_indexes():
            info = g.get_info(lix)
            it = top.begin_shapes_rec(lix)
            while not it.at_end():
                sh = it.shape()
                if sh.is_text():
                    p = (it.dtrans() * sh.dtext).trans.disp
                    texts.append({"text": sh.text_string, "layer": (info.layer, info.datatype),
                                  "x": p.x, "y": p.y, "top": it.cell().cell_index() == top.cell_index()})
                it.next()
        self.texts = texts
        self.gds_top_bbox = _box(top.dbbox())

    # --------------------------------------------------------------- geometry
    def net_region(self, key: str, metal: str) -> kdb.Region:
        """Merged polygons of a net on a metal/via layer (dbu units)."""
        key = getattr(self, "net_aliases", {}).get(key, key)
        ck = (key, metal)
        if ck in self._regions:
            return self._regions[ck]
        ni = self.nets.get(key)
        lr = self.layer_region(metal)
        if ni is None or lr is None:
            r = kdb.Region()
        else:
            sources = ni.sources or [(ni.lnet, ni.trans)]
            regions = []
            for net, trans in sources:
                t = kdb.ICplxTrans(trans, self.dbu) if not trans.is_unity() else kdb.ICplxTrans()
                regions.append(self.lvs.shapes_of_net(net, lr, True, t))
            r = regions[0]
            if len(regions) > 1:
                # Shared descendant cuts may be reached through two aliased
                # parent nets. Deduplicate identical polygons, preserving
                # separate adjacent via cuts rather than merging them.
                r = kdb.Region()
                seen = set()
                for region in regions:
                    for polygon in region.each():
                        if polygon not in seen:
                            seen.add(polygon)
                            r.insert(polygon)
            if metal not in L.VIAS:
                r = r.merged()
        self._regions[ck] = r
        return r

    def via_count(self, key: str, via: str) -> int:
        return self.net_region(key, via).count()

    def device_area_union(self) -> float:
        r = kdb.Region()
        for d in self.devices:
            for f in d.fingers:
                x1, y1, x2, y2 = f.full
                r.insert(kdb.Box(round(x1 / self.dbu), round(y1 / self.dbu), round(x2 / self.dbu), round(y2 / self.dbu)))
        return r.merged().area() * self.dbu * self.dbu

    def port_points(self, key: str) -> list[tuple[float, float, str]]:
        """Pin label positions for a (top-level) net: [(x, y, metal)]."""
        key = getattr(self, "net_aliases", {}).get(key, key)
        names = getattr(self, "_net_port_names", {}).get(key, {key.split(".")[-1].lower()})
        pts = []
        for t in self.texts:
            if t["text"].lower() in names and t["top"]:
                metal = L.LABEL_TO_METAL.get(t["layer"][0])
                pts.append((t["x"], t["y"], metal))
        return pts

    def resolve_device(self, name: str) -> tuple[list[Device], str]:
        refs, how = self.resolver.device(name)
        devs = [self.dev_by_ref[r] for r in refs if r in self.dev_by_ref]
        if devs:
            return devs, how
        if refs:
            # the reference device exists but has no layout partner (e.g. it
            # was combined with a parallel device by LVS): do not guess
            return [], f"unresolved: reference {refs} has no matched layout device (combined or unmatched in LVS)"
        # KLayout combines series/parallel segments (XR2a_0 + XR2a_1 -> "2A_0");
        # a segment absent from the reference netlist is mapped to the combined
        # device carrying a sibling's name, if exactly one such device exists.
        m = re.match(r"^(.*?)(_\d+|__unit\d+)$", name, re.I)
        if m:
            base = m.group(1)
            want = self.resolver.expected_class(name)
            cands = []
            for d in self.devices:
                if not d.ref or len(d.fingers) < 2 or (want and d.cls != want):
                    continue
                for k in range(0, 64):
                    r2, _ = self.resolver.device(f"{base}_{k}")
                    if d.ref in r2:
                        cands.append(d)
                        break
            cands = list({id(c): c for c in cands}.values())
            if len(cands) == 1:
                return cands, f"segment merged by KLayout into combined device {cands[0].ref}"
        verified = self._verified_series_resistor(name)
        if verified is not None:
            return verified
        return [], how

    def _verified_series_resistor(self, name):
        """Resolve a removed RES segment only with bound topology evidence.

        Unlike the legacy multi-abstract alias fallback, this also supports a
        single physical resistor replacing a source series chain. No source
        segment geometry is invented: all aliases name the existing matched
        logical device, and matching's normal member deduplication still runs.
        """
        if self.resolver.expected_class(name) != "RES":
            return None
        if not hasattr(self, "_series_resistor_aliases"):
            self._series_resistor_aliases = {}
            reference_path = self.lvs_dir / "reference.spice"
            try:
                result = json.loads((self.lvs_dir / "result.json").read_text())
                reference_bytes = reference_path.read_bytes()
                reference_sha = hashlib.sha256(reference_bytes).hexdigest()
                if (result.get("check") != "lvs" or result.get("status") != "passed"
                        or result.get("details", {}).get("matches") is not True
                        or reference_sha != result.get("reference_sha256")
                        or hashlib.sha256(self.lvsdb_path.read_bytes()).hexdigest() != result.get("report_sha256")
                        or hashlib.sha256(self.gds_path.read_bytes()).hexdigest() != result.get("input_sha256")):
                    return None
                chains = series_resistor_chains(reference_bytes.decode("utf-8"), self.top_name)
                native = self._reference_resistor_records()
                for proof in chains:
                    candidates = []
                    for key, record in native.items():
                        if key not in proof["native_member_keys"] or key not in self.dev_by_ref:
                            continue
                        if sum(device.ref == key for device in self.devices) != 1:
                            continue
                        target = self.dev_by_ref[key]
                        if (target.cls != "RES" or record["model"] != proof["model"]
                                or target.model.casefold() != proof["model"]
                                or sorted(record["endpoints"]) != proof["endpoints"]
                                or record["bulk"] != proof["bulk"]):
                            continue
                        length = record["parameters"].get("L", 0) * UM
                        width = record["parameters"].get("W", 0) * UM
                        if width == 0 and re.fullmatch(r"sky130_fd_pr__res_(?:x?high)_po_(0p35|0p69|1p41|2p85|5p73)", record["model"]):
                            width = float(record["model"].rsplit("_", 1)[1].replace("p", "."))
                        dimensions = ((length, proof["l_um"]), (width, proof["w_um"]),
                                      (target.params.get("L", 0) * UM, proof["l_um"]),
                                      (target.params.get("W", 0) * UM, proof["w_um"]))
                        if all(math.isfinite(a) and a > 0 and math.isclose(a, b, rel_tol=1e-9, abs_tol=1e-8)
                               for a, b in dimensions):
                            candidates.append((key, target))
                    if len(candidates) != 1:
                        continue
                    key, target = candidates[0]
                    evidence = {**proof, "surviving_reference": key, "reference_sha256": reference_sha,
                                "proof": "unbranched_same_model_width_unit_m_series_chain_and_native_terminals_dimensions"}
                    for alias in proof["members"]:
                        self._series_resistor_aliases.setdefault(alias, []).append((target, evidence))
            except (OSError, ValueError, UnicodeError, KeyError, TypeError):
                self._series_resistor_aliases.clear()
                return None  # unqualified or incomplete inputs retain the existing missing result
        parts = name.upper().split(".")
        prefix = ".".join(self.resolver._path(parts[:-1]))
        prefix = prefix + "." if prefix else ""
        leaves = [parts[-1], *self.resolver.name_map.get(parts[-1], [])]
        options = [item for leaf in leaves
                   for item in self._series_resistor_aliases.get(prefix + leaf.upper(), [])]
        unique = {(target.uid, evidence["surviving_reference"]): (target, evidence)
                  for target, evidence in options}
        if len(unique) != 1:
            return None
        target, proof = next(iter(unique.values()))
        if not hasattr(self, "verified_resistor_series_mappings"):
            self.verified_resistor_series_mappings = {}
        self.verified_resistor_series_mappings[name] = {**proof, "requested_instance": name}
        return [target], f"verified series-merged resistor in compared reference: {target.ref}"

    def _reference_resistor_records(self):
        """Read native reference terminals through actual hierarchy pin aliases."""
        records = {}

        def walk(circuit, prefix, aliases, ancestors):
            if circuit.name in ancestors:
                raise ValueError("Recursive native reference cannot prove a series mapping")
            def net_name(net):
                # SPICE reference nets do not carry extracted cluster IDs
                # (all can be zero); use their circuit-local expanded keys.
                local = net.expanded_name().upper()
                return aliases.get(local, prefix + local)

            for device in circuit.each_device():
                if _cls(device.device_class()) != "RES":
                    continue
                terminals = {terminal.name: net_name(device.net_for_terminal(terminal.id()))
                             for terminal in device.device_class().terminal_definitions()
                             if device.net_for_terminal(terminal.id()) is not None}
                if not {"A", "B"} <= terminals.keys() or set(terminals) - {"A", "B", "W"}:
                    continue
                key = prefix + self._rk(device)
                records[key] = {"model": device.device_class().name.casefold(),
                                "parameters": {p.name: device.parameter(p.id())
                                               for p in device.device_class().parameter_definitions()},
                                "endpoints": [terminals["A"], terminals["B"]], "bulk": terminals.get("W")}
            for sub in circuit.each_subcircuit():
                child_aliases = {}
                for child_net in sub.circuit_ref().each_net():
                    for pin in child_net.each_pin():
                        parent_net = sub.net_for_pin(pin.pin_id())
                        if parent_net is not None:
                            child_aliases[child_net.expanded_name().upper()] = net_name(parent_net)
                walk(sub.circuit_ref(), prefix + sub.expanded_name().upper() + ".", child_aliases,
                     ancestors | {circuit.name})

        tops = [c for c in self.refnl.each_circuit_top_down()
                if c.name.casefold() == self.top_name.casefold()]
        if len(tops) == 1:
            walk(tops[0], "", {}, set())
        return records

    def resolve_group(self, names: list[str]) -> tuple[list[tuple[str, list[Device]]], list[str]]:
        out, problems = [], []
        for n in names:
            devs, how = self.resolve_device(n)
            if not devs:
                problems.append(f"{n}: {how}")
                continue
            if "merged" in how:
                problems.append(f"{n}: note: {how}")
            out.append((n, devs))
        return out, problems

    def resolve_net(self, name: str) -> tuple[str | None, str]:
        key, how = self.resolver.net(name)
        return (self.net_aliases.get(key, key), how) if key is not None else (None, how)

    def summary(self) -> dict:
        nf = {d.ref: len(d.fingers) for d in self.devices if d.ref}
        return {
            "task": self.task, "top": self.top_name, "trial_dir": str(self.dir),
            "status": self.status, "bbox_um": self.bbox, "bbox_area_um2": self.bbox_area,
            "device_count": len([d for d in self.devices if d.ref]),
            "unmatched_layout_devices": [d.lname for d in self.unmatched_layout_devices],
            "unmatched_reference_devices": self.unmatched_ref_devices,
            "device_area_union_um2": self.device_area_union(),
            "layer_inference": self.layer_info,
            "xref_status": self.xref_status,
            "fingers_per_device": nf,
            "resistor_geometry": getattr(self, "resistor_geometry", None),
            **({"verified_resistor_series_mappings": list(self.verified_resistor_series_mappings.values())}
               if getattr(self, "verified_resistor_series_mappings", None) else {}),
        }
