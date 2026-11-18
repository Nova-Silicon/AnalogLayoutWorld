"""Power / ground / power-device net robustness.

v3: power = conventions (every circuit: rail width vs layer minimum, ring or
mesh, continuous trunk, redundant vias) and, only when a rail carries
>= power_min_current_a or power devices are annotated, 0.5 * conventions +
0.5 * current part (EM width, via current, IR drop as below).

Method (per analysed net):

1. Current budget.  ``currents_a[net]`` is the DC current of the rail.  Devices
   listed in ``currents_a`` (power devices) carry their own current; the rest
   of the rail current is shared by the other devices whose S/D (MOS), A/B
   (resistor) or C/E (BJT) terminal is on the net, proportional to W/L for
   MOS and 1/L for resistors (an [ASSUME] proxy -- no per-branch simulation).
   For power devices, their S/D nets that are not rails are analysed too:
   the power device terminal is the source and the other S/D devices on that
   net (or the pin, if none) take its current.
2. Resistor grid.  Every metal layer of the net (li1..met5) is rasterised with
   KLayout ``Region.rasterize`` (exact covered area per pixel).  A pixel with
   coverage c is a node; neighbours are joined by conductance
   min(c_i, c_j) / R_sheet (exact for a straight wire of any width), vias join
   layers with n_vias / R_via.  Device currents are injected on the li1 (or
   lowest available) pixels of the net that overlap the device's S/D strips
   (resistor heads), weighted by pixel coverage; the pin
   label pixels are held at 0 V.  Sheet/via resistances: Magic tech file
   (constants.py).  Diffusion, poly and licon are not modelled.
3. Results.  Linear current density J = |I_edge| / (c * pitch) per in-layer
   edge vs the EM limit of that layer (SkyWater tech LEF, DC average, 90 C;
   li1 has no public number -> assumption); via current per cut vs the LEF
   per-via limit.  Width score = 1 - current-weighted fraction of path length
   above the limit; via score = 1 - current-weighted fraction of via current
   above the limit; IR drop of a device = current-weighted mean drop over its
   injection pixels; IR score = soft(worst device drop % of supply, ir_pct0).
   Components of the net that the metal grid cannot connect to the pin (joined
   only through diffusion/poly/substrate) are reported, not solved. A positive
   load current on such pixels makes the current measurement incomplete; it
   does not prove physical disconnection of the GDS. Pixels at an ideal source
   are represented by their legitimate zero-drop current share.
"""

from __future__ import annotations

import math
import statistics

import numpy as np
import klayout.db as kdb
from scipy.sparse import coo_matrix
from scipy.sparse.csgraph import connected_components
from scipy.sparse.linalg import spsolve

from . import constants as K
from .constants import P
from .geom import soft, wmean
from .layers import METALS, VIAS

_SD = {"MOS": ("S", "D"), "RES": ("A", "B"), "BJT": ("C", "E")}


def _sink_terms(d):
    return _SD.get(d.cls, ())


def _weight(d):
    p = d.params
    if d.cls == "MOS":
        return max(p.get("W", 1.0), 1e-9) / max(p.get("L", 1.0), 1e-9)
    if d.cls == "RES":
        return 1.0 / max(p.get("L", 1.0), 1e-9)
    return 1.0


class Grid:
    def __init__(self, tm, key):
        self.tm, self.key, self.dbu = tm, key, tm.dbu
        self.layers = [m for m in METALS if not tm.net_region(key, m).is_empty()]
        bb = kdb.Box()
        area = 0.0
        for m in self.layers:
            r = tm.net_region(key, m)
            bb += r.bbox()
            area += r.area() * self.dbu ** 2
        self.bbox = bb
        w, h = bb.width() * self.dbu, bb.height() * self.dbu
        nl = max(1, len(self.layers))
        p = max(P["grid_min_pitch_um"], math.sqrt(w * h * nl / (4 * P["grid_max_cells"])),
                math.sqrt(area / P["grid_max_cells"]))
        self.pitch = p
        self.nx = max(1, int(math.ceil(w / p)) + 1)
        self.ny = max(1, int(math.ceil(h / p)) + 1)
        self.origin = (bb.left * self.dbu, bb.bottom * self.dbu)
        pd = int(round(p / self.dbu))
        cov = {}
        for m in self.layers:
            a = tm.net_region(key, m).rasterize(kdb.Point(bb.left, bb.bottom), kdb.Vector(pd, pd),
                                                kdb.Vector(pd, pd), self.nx, self.ny)
            cov[m] = np.clip(np.asarray(a, dtype=float) / float(pd * pd), 0.0, 1.0)  # [ny][nx]
        self.cov = cov
        self.index = {}
        n = 0
        for m in self.layers:
            idx = -np.ones((self.ny, self.nx), dtype=np.int64)
            mask = cov[m] > 0.02
            cnt = int(mask.sum())
            idx[mask] = np.arange(n, n + cnt)
            n += cnt
            self.index[m] = idx
        self.n = n

    def cell(self, x, y):
        j = int((x - self.origin[0]) / self.pitch)
        i = int((y - self.origin[1]) / self.pitch)
        return min(max(i, 0), self.ny - 1), min(max(j, 0), self.nx - 1)

    def node_near(self, m, i, j, r=2):
        idx = self.index.get(m)
        if idx is None:
            return -1
        best, bc = -1, 0.0
        for di in range(-r, r + 1):
            for dj in range(-r, r + 1):
                ii, jj = i + di, j + dj
                if 0 <= ii < self.ny and 0 <= jj < self.nx and idx[ii, jj] >= 0:
                    c = self.cov[m][ii, jj] / (1 + abs(di) + abs(dj))
                    if c > bc:
                        best, bc = int(idx[ii, jj]), c
        return best

    def build(self):
        rows, cols, vals, kinds = [], [], [], []
        self.edges = []  # (a, b, g, layer or via, coverage, n_cuts)
        for m in self.layers:
            idx, c = self.index[m], self.cov[m]
            rs = K.SHEET_RES[m]
            for di, dj in ((0, 1), (1, 0)):
                a = idx[: self.ny - di, : self.nx - dj]
                b = idx[di:, dj:]
                ca = c[: self.ny - di, : self.nx - dj]
                cb = c[di:, dj:]
                ok = (a >= 0) & (b >= 0)
                g = np.minimum(ca, cb)[ok] / rs
                for aa, bb_, gg, cc in zip(a[ok], b[ok], g, np.minimum(ca, cb)[ok]):
                    self.edges.append((int(aa), int(bb_), float(gg), m, float(cc), 0))
        self.via_missing = 0
        self.via_cuts = {}
        for k, v in enumerate(VIAS):
            lo, hi = METALS[k], METALS[k + 1]
            reg = self.tm.net_region(self.key, v)
            if reg.is_empty():
                continue
            cnt = 0
            per_cell = {}
            for poly in reg.each():
                c = poly.bbox().center()
                i, j = self.cell(c.x * self.dbu, c.y * self.dbu)
                per_cell[(i, j)] = per_cell.get((i, j), 0) + 1
                cnt += 1
            self.via_cuts[v] = cnt
            if lo not in self.index or hi not in self.index:
                self.via_missing += cnt
                continue
            for (i, j), ncut in per_cell.items():
                a = self.node_near(lo, i, j)
                b = self.node_near(hi, i, j)
                if a < 0 or b < 0:
                    self.via_missing += ncut
                    continue
                self.edges.append((a, b, ncut / K.VIA_RES[v], v, 1.0, ncut))
        e = self.edges
        if not e:
            self.G = None
            return
        a = np.array([x[0] for x in e]); b = np.array([x[1] for x in e]); g = np.array([x[2] for x in e])
        n = self.n
        r = np.concatenate([a, b, a, b]); c_ = np.concatenate([b, a, a, b])
        v = np.concatenate([-g, -g, g, g])
        self.G = coo_matrix((v, (r, c_)), shape=(n, n)).tocsr()
        self.adj = coo_matrix((np.ones(len(a)), (a, b)), shape=(n, n)).tocsr()


def _inject_nodes(grid, dev):
    """Grid nodes (and coverage weights) where a device's current enters the
    net: net pixels on the lowest layer overlapping the device's S/D strips
    (MOS) / heads (resistor); whole footprint for other devices.  Body-tap
    straps of the same net are thereby excluded (no DC current)."""
    for m in grid.layers:
        idx, cov = grid.index[m], grid.cov[m]
        nodes = {}
        for f in dev.fingers:
            for x1, y1, x2, y2 in (f.terms or [f.full]):
                i1, j1 = grid.cell(x1, y1)
                i2, j2 = grid.cell(x2, y2)
                sub = idx[i1:i2 + 1, j1:j2 + 1]
                cs = cov[i1:i2 + 1, j1:j2 + 1]
                for v, c in zip(sub[sub >= 0].ravel(), cs[sub >= 0].ravel()):
                    nodes[int(v)] = float(c)
        if nodes:
            return nodes, m
    return {}, None


def analyse_net(tm, key, sinks, sources, supply_v, label):
    """sinks: [(device, current_A)]; sources: list of ('pin', None) or ('dev', device)."""
    rec = {"net": label, "key": key, "supply_v": supply_v,
           "sink_currents_mA": {d.ref: round(i * 1e3, 4) for d, i in sinks}}
    if not sinks:
        rec.update(status="unavailable", reason="no current-carrying device terminals on net")
        return rec
    grid = Grid(tm, key)
    rec["grid_pitch_um"] = round(grid.pitch, 3)
    rec["grid_nodes"] = grid.n
    if grid.n == 0:
        rec.update(status="unavailable", reason="net has no metal")
        return rec
    grid.build()
    rec["via_cuts"] = grid.via_cuts
    rec["vias_unplaced"] = grid.via_missing
    fixed = set()
    src_notes = []
    for kind, obj in sources:
        if kind == "pin":
            pts = tm.port_points(key)
            for x, y, metal in pts:
                i, j = grid.cell(x, y)
                cand = [metal] if metal in grid.layers else []
                cand += [m for m in reversed(grid.layers) if m not in cand]
                for m in cand:
                    nd = grid.node_near(m, i, j, r=3)
                    if nd >= 0:
                        fixed.add(nd)
                        break
            src_notes.append(f"pin labels: {len(pts)}")
        else:
            nodes, m = _inject_nodes(grid, obj)
            fixed.update(nodes.keys())
            src_notes.append(f"source device {obj.ref} on {m}")
    if not fixed:
        rec.update(status="unavailable", reason="no pin label / source terminal found on the net's metal",
                   sources=src_notes)
        return rec
    rec["sources"] = src_notes
    # Coverage is a property of every injection pixel, not of whichever pixel
    # happens to be enumerated first.  Fixed pixels are ideal source points:
    # their share of the load is represented with zero voltage drop, rather
    # than redistributed to the remaining pixels or called disconnected.
    if grid.G is None:
        lab = np.arange(grid.n)
    else:
        _, lab = connected_components(grid.adj, directed=False)
    fixed_comps = {lab[x] for x in fixed}
    live = np.isin(lab, list(fixed_comps))
    inj = np.zeros(grid.n)
    dev_nodes, device_coverage = {}, {}
    isolated, partial, unmapped = [], [], []
    fixed_current = live_current = disconnected_current = unmapped_current = 0.0
    incomplete = False
    for d, cur in sinks:
        nodes, m = _inject_nodes(grid, d)
        if not nodes:
            dev_nodes[d.ref] = None
            unmapped.append(d.ref)
            unmapped_current += cur
            incomplete |= cur > 0
            device_coverage[d.ref] = {"status": "unmapped", "current_mA": cur * 1e3,
                                      "pixels": 0, "fixed_pixels": 0, "live_pixels": 0,
                                      "disconnected_pixels": 0, "represented_fraction": 0.0}
            continue
        keys = np.array(list(nodes.keys()), dtype=np.int64)
        w = np.array(list(nodes.values()), dtype=float)
        w = w / w.sum()
        dev_nodes[d.ref] = (keys, w)
        at_source = np.array([int(k) in fixed for k in keys], dtype=bool)
        in_grid = live[keys] & ~at_source
        disconnected = ~live[keys]
        fw, lw, dw = (float(w[mask].sum()) for mask in (at_source, in_grid, disconnected))
        fixed_current += cur * fw
        live_current += cur * lw
        disconnected_current += cur * dw
        inj[keys[in_grid]] += cur * w[in_grid]
        if disconnected.any() and cur > 0:
            incomplete = True
            (isolated if not live[keys].any() else partial).append(d.ref)
        device_coverage[d.ref] = {
            "status": "partial" if disconnected.any() else "complete",
            "current_mA": cur * 1e3, "pixels": len(keys), "fixed_pixels": int(at_source.sum()),
            "live_pixels": int(in_grid.sum()), "disconnected_pixels": int(disconnected.sum()),
            "represented_fraction": min(1.0, fw + lw),
        }
    total_current = sum(c for _, c in sinks)
    represented_current = fixed_current + live_current
    rec.update(
        total_current_mA=round(total_current * 1e3, 4),
        unconnected_current_mA=round((disconnected_current + unmapped_current) * 1e3, 4),
        isolated_devices=sorted(isolated), partial_devices=sorted(partial), unmapped_devices=sorted(unmapped),
        current_coverage={"status": "partial" if incomplete else "complete",
                          "fraction": min(1.0, represented_current / total_current) if total_current > 0 else 0.0,
                          "total_current_mA": total_current * 1e3,
                          "represented_current_mA": represented_current * 1e3,
                          "fixed_source_current_mA": fixed_current * 1e3,
                          "live_grid_current_mA": live_current * 1e3,
                          "disconnected_current_mA": disconnected_current * 1e3,
                          "unmapped_current_mA": unmapped_current * 1e3,
                          "devices": device_coverage},
    )
    if incomplete or total_current <= 0:
        rec.update(status="partial" if incomplete else "unavailable",
                   reason="Current is not fully represented in the metal resistor grid; "
                          "this is not a claim of physical GDS disconnection" if incomplete
                          else "no positive current to analyse",
                   width_score=None, via_score=None, ir_score=None,
                   ir_drop_pct=None, ir_drop_mV={}, ir_drop_max_pixel_mV={})
        return rec
    free = np.array([k for k in range(grid.n) if live[k] and k not in fixed], dtype=np.int64)
    V = np.zeros(grid.n)
    if len(free):
        Gf = grid.G[free][:, free]
        try:
            V[free] = spsolve(Gf.tocsc(), inj[free])
        except Exception as exc:  # singular / numerical trouble
            rec.update(status="unavailable", reason=f"grid solve failed: {exc}")
            return rec
    # edge currents
    over_w = tot_w = 0.0
    over_len = 0.0
    jmax_ratio = 0.0
    via_over = via_tot = 0.0
    via_worst = 0.0
    hot = []
    for a, b, g, lay, cov, ncut in grid.edges:
        if not (live[a] and live[b]):
            continue
        ie = abs(g * (V[a] - V[b]))
        if ie <= 0:
            continue
        if ncut == 0:
            j = ie / max(cov * grid.pitch, 1e-9) * 1e3  # mA/um
            lim = K.EM_MA_PER_UM[lay]
            w = ie * grid.pitch
            tot_w += w
            jmax_ratio = max(jmax_ratio, j / lim)
            if j > lim:
                over_w += w
                over_len += grid.pitch
                if len(hot) < 4000:
                    hot.append((a, b, lay, round(j / lim, 2)))
        else:
            per = ie / ncut * 1e3
            lim = K.EM_VIA_MA[lay]
            via_tot += ie
            via_worst = max(via_worst, per / lim)
            if per > lim:
                via_over += ie
    # IR drop at the sink devices: current-weighted mean over the device's
    # injection pixels (what the parallel fingers see); max reported too
    drops, drops_max = {}, {}
    for r, nodes in dev_nodes.items():
        if nodes is not None:
            keys, w = nodes
            drops[r] = float(np.sum(np.abs(V[keys]) * w))
            drops_max[r] = float(np.max(np.abs(V[keys])))
    worst = max(drops.values()) if drops else None
    rec.update(
        status="measured",
        width_overstress_fraction=(over_w / tot_w) if tot_w > 0 else 0.0,
        overstressed_length_um=round(over_len, 2),
        max_j_over_limit=round(jmax_ratio, 3),
        via_overstress_fraction=(via_over / via_tot) if via_tot > 0 else 0.0,
        max_via_current_over_limit=round(via_worst, 3),
        ir_drop_mV={r: round(v * 1e3, 3) for r, v in sorted(drops.items(), key=lambda kv: -kv[1])[:8]},
        ir_drop_max_pixel_mV={r: round(drops_max[r] * 1e3, 3) for r, _ in sorted(drops.items(), key=lambda kv: -kv[1])[:8]},
        ir_drop_pct=(100.0 * worst / supply_v) if worst is not None else None,
    )
    k_em = P["em_penalty_k"]
    rec["width_score"] = max(0.0, 1.0 - k_em * rec["width_overstress_fraction"])
    rec["via_score"] = max(0.0, 1.0 - k_em * rec["via_overstress_fraction"]) if via_tot > 0 else None
    rec["ir_score"] = soft(rec["ir_drop_pct"], P["ir_pct0"]) if rec["ir_drop_pct"] is not None else None
    # pixels for drawing (overstressed edges)
    xy = {}
    for m in grid.layers:
        idx = grid.index[m]
        ii, jj = np.nonzero(idx >= 0)
        for i, j in zip(ii, jj):
            xy[int(idx[i, j])] = (grid.origin[0] + (j + 0.5) * grid.pitch, grid.origin[1] + (i + 0.5) * grid.pitch)
    rec["_overstress_segments"] = [(xy[a], xy[b], lay, r) for a, b, lay, r in hot if a in xy and b in xy]
    return rec


def _conservative_width(tm, key, current_a):
    """Fraction of each layer's net metal narrower than I/J_max (whole rail
    current through every segment) -- an upper bound, reported only."""
    out = {}
    for m in METALS:
        r = tm.net_region(key, m)
        if r.is_empty():
            continue
        wreq = current_a * 1e3 / K.EM_MA_PER_UM[m]
        d = int(round(wreq / 2 / tm.dbu))
        if d <= 0:
            out[m] = 0.0
            continue
        opened = r.sized(-d).sized(d)
        narrow = r - opened
        out[m] = round(narrow.area() / r.area(), 4) if r.area() > 0 else 0.0
    return out


def _up(v, lo, hi):
    return max(0.0, min(1.0, (v - lo) / (hi - lo)))


def conventions(tm, key: str) -> dict:
    """Layout conventions of one supply/ground net (current-independent):
    width   length-weighted median rail width on met1..met5 / layer min width
    ring    the rail closes a loop (polygon with a hole, or a cycle through vias)
    trunk   share of the rail's met1+ length in its largest via-connected piece
    vias    share of via clusters (via..via4) with >= 2 cuts (redundant vias)"""
    dbu = tm.dbu
    wl, ring = [], False
    polys = {}
    for m in METALS[1:]:
        lst = []
        for poly in tm.net_region(key, m).each_merged():
            if poly.holes() > 0:
                ring = True
            length = 0.0
            for tz in poly.decompose_trapezoids():
                b = tz.bbox()
                w, h = b.width() * dbu, b.height() * dbu
                wl.append((min(w, h) / K.MIN_WIDTH[m], max(w, h)))
                length += max(w, h)
            lst.append((poly, length))
        polys[m] = lst
    if not wl:
        return {"score": None, "reason": "no met1+ rail metal"}
    wl.sort()
    half, acc, wmult = sum(l for _, l in wl) / 2, 0.0, wl[-1][0]
    for v, l in wl:
        acc += l
        if acc >= half:
            wmult = v
            break
    # via graph between met1..met5 polygons
    nodes = [(m, i) for m in METALS[1:] for i in range(len(polys[m]))]
    idx = {n: k for k, n in enumerate(nodes)}
    parent = list(range(len(nodes)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    edges = set()
    clusters_total = clusters_multi = 0
    for k, v in enumerate(VIAS):
        if v == "mcon":
            continue
        lo, hi = METALS[k], METALS[k + 1]
        cuts = tm.net_region(key, v)
        if cuts.is_empty():
            continue
        grown = cuts.sized(int(round(0.25 / dbu))).merged()
        for cl in grown.each_merged():
            n = (cuts & kdb.Region(cl)).count()
            clusters_total += 1
            clusters_multi += n >= 2
        for cut in cuts.each():
            c = cut.bbox().center()
            a = next((i for i, (pp, _) in enumerate(polys[lo]) if pp.bbox().contains(c) and pp.inside(c)), None)
            b = next((i for i, (pp, _) in enumerate(polys[hi]) if pp.bbox().contains(c) and pp.inside(c)), None)
            if a is None or b is None:
                continue
            ia, ib = idx[(lo, a)], idx[(hi, b)]
            if (ia, ib) not in edges:
                edges.add((ia, ib))
                ra, rb = find(ia), find(ib)
                if ra == rb:
                    ring = True  # a second path between two pieces closes a loop
                else:
                    parent[ra] = rb
    comp = {}
    for n, k in idx.items():
        comp[find(k)] = comp.get(find(k), 0.0) + polys[n[0]][n[1]][1]
    tot = sum(comp.values())
    trunk = max(comp.values()) / tot if tot > 0 else None
    vias = clusters_multi / clusters_total if clusters_total else None
    c = P["power_conv"]
    parts = {"width": _up(wmult, c["width_mult_zero"], c["width_mult_full"]), "ring": 1.0 if ring else 0.0,
             "trunk": None if trunk is None else _up(trunk, c["trunk_zero"], c["trunk_full"]),
             "vias": vias}
    vals = [v for v in parts.values() if v is not None]
    return {"score": sum(vals) / len(vals) if vals else None, "parts": parts,
            "width_multiple": round(wmult, 2), "ring_or_mesh": ring,
            "trunk_fraction": None if trunk is None else round(trunk, 3),
            "via_clusters": clusters_total, "via_clusters_multi": clusters_multi}


def _run(tm, key, sinks_avg, sinks_peak, sources, supply, label):
    """EM (width/vias) at average currents; IR at peak currents when the
    annotation gives peak device currents (see score_power)."""
    rec = analyse_net(tm, key, sinks_avg, sources, supply, label)
    same = [(d.uid, round(i, 12)) for d, i in sinks_avg] == [(d.uid, round(i, 12)) for d, i in sinks_peak]
    rec["current_mode"] = "dc"
    if same or rec.get("status") != "measured":
        return rec
    pk = analyse_net(tm, key, sinks_peak, sources, supply, label)
    rec["current_mode"] = ("peak device currents exceed the rail DC current: EM width/vias checked at "
                           "the rail-average share, IR drop at the annotated peak (dynamic IR)")
    if pk.get("status") == "measured":
        for k in ("ir_drop_mV", "ir_drop_max_pixel_mV", "ir_drop_pct"):
            rec[k] = pk.get(k)
        pct = pk.get("ir_drop_pct")
        rec["ir_score"] = soft(pct, P["ir_dyn_pct0"]) if pct is not None else None
        rec["ir_mode"] = f"dynamic (peak current), scored against {P['ir_dyn_pct0']}% instead of {P['ir_pct0']}%"
        rec["peak_max_j_over_limit"] = pk.get("max_j_over_limit")
        rec["peak_sink_currents_mA"] = pk.get("sink_currents_mA")
    else:
        # An available DC result is not evidence that the required peak-current
        # IR estimate was measured.  Keep the DC diagnostics without awarding
        # a complete current score for a partially represented peak scenario.
        rec.update(status=pk.get("status", "unavailable"),
                   reason="Peak-current estimate unavailable: " + pk.get("reason", "measurement incomplete"),
                   peak_current_coverage=pk.get("current_coverage"),
                   width_score=None, via_score=None, ir_score=None,
                   ir_drop_pct=None, ir_drop_mV={}, ir_drop_max_pixel_mV={})
    return rec


def score_power(tm, annotation) -> dict:
    nets = annotation.get("nets") or {}
    cur = {k.lower(): v for k, v in (annotation.get("currents_a") or {}).items()}
    # convention part (every circuit)
    conv_rows = {}
    for role in ("power", "ground"):
        for n in nets.get(role) or []:
            k, _ = tm.resolve_net(n)
            if k:
                conv_rows[n] = conventions(tm, k)
    conv_vals = [r["score"] for r in conv_rows.values() if r.get("score") is not None]
    conv_score = sum(conv_vals) / len(conv_vals) if conv_vals else None
    rail_names = [n.lower() for r in ("power", "ground") for n in (nets.get(r) or [])]
    max_rail = max([cur.get(n, 0.0) or 0.0 for n in rail_names] or [0.0])
    significant = max_rail >= P["power_min_current_a"] or bool(annotation.get("power_devices") or [])
    if not significant:
        return {"score": conv_score, "status": "measured" if conv_score is not None else "unavailable",
                "subscores": {"conventions": conv_score, "current": None},
                "conventions": conv_rows,
                "current_part": f"not scored: largest rail current {max_rail * 1e3:.3f} mA < "
                                f"{P['power_min_current_a'] * 1e3:.1f} mA and no power devices"}
    # optional annotation field supply_v: {net: volts} (case-insensitive) --
    # reference voltage of the IR-drop percentage for that net
    vsup = {str(k).lower(): float(v) for k, v in (annotation.get("supply_v") or {}).items()}
    problems = []
    power_devs = []
    for n in annotation.get("power_devices") or []:
        devs, how = tm.resolve_device(n)
        if not devs:
            problems.append(f"power device {n}: {how}")
            continue
        power_devs.append((n, devs[0], cur.get(n.lower())))
    explicit = {d.uid: (n, i) for n, d, i in power_devs if i}
    # Rails and their explicit (power-device) sinks; if the explicit currents on
    # a rail exceed the rail's DC current, they are peak values: their average
    # share is scaled down to the rail current for the EM checks.
    rails = []
    for role in ("power", "ground"):
        for n in nets.get(role) or []:
            k, how = tm.resolve_net(n)
            if k is None:
                problems.append(f"{n}: {how}")
                continue
            rails.append((role, n, k, cur.get(n.lower())))
    avg_scale = {lid: 1.0 for lid in explicit}
    for role, n, k, inet in rails:
        if not inet:
            continue
        on = [d for d in tm.devices if d.ref and d.uid in explicit and
              any(d.terms.get(t) == k for t in _sink_terms(d))]
        tot = sum(explicit[d.uid][1] for d in on)
        if tot > inet * 1.01:
            for d in on:
                avg_scale[d.uid] = min(avg_scale[d.uid], inet / tot)
    rows = []
    rail_keys = {k for _, _, k, _ in rails}
    for role, n, k, inet in rails:
        if not inet:
            rows.append({"net": n, "role": role, "status": "unavailable", "reason": "no current in annotation"})
            continue
        s_pk, s_avg, rest_dev = [], [], []
        used_pk = used_avg = 0.0
        for d in tm.devices:
            if not d.ref:
                continue
            on = [t for t in _sink_terms(d) if d.terms.get(t) == k]
            if not on or len(on) == len(_sink_terms(d)):
                continue  # not connected, or both S/D on the rail (no current)
            if d.uid in explicit:
                ip = explicit[d.uid][1]
                s_pk.append((d, ip))
                s_avg.append((d, ip * avg_scale[d.uid]))
                used_pk += ip
                used_avg += ip * avg_scale[d.uid]
            else:
                rest_dev.append(d)
        wsum = sum(_weight(d) for d in rest_dev)
        for lst, used in ((s_pk, used_pk), (s_avg, used_avg)):
            rest = max(0.0, inet - used)
            if rest > 0 and wsum > 0:
                lst += [(d, rest * _weight(d) / wsum) for d in rest_dev]
        supply = vsup.get(n.lower(), P["default_supply_v"])
        rec = _run(tm, k, s_avg, s_pk, [("pin", None)], supply, n)
        rec["role"] = role
        rec["annotated_current_mA"] = inet * 1e3
        rec["conservative_narrow_fraction"] = _conservative_width(tm, k, inet)
        rows.append(rec)
    # power-device S/D nets that are not rails
    for n, d, i in power_devs:
        if not i:
            problems.append(f"power device {n}: no current in annotation")
            continue
        for t in _sink_terms(d):
            k = d.terms.get(t)
            if not k or k in rail_keys:
                continue
            others = []
            for o in tm.devices:
                if o is d or not o.ref:
                    continue
                if any(o.terms.get(tt) == k for tt in _sink_terms(o)):
                    others.append(o)
            sc = avg_scale.get(d.uid, 1.0)
            if others:
                w = sum(_weight(o) for o in others)

                def share(ii, scale):
                    return [(o, ii * _weight(o) / w) if o.uid not in explicit
                            else (o, min(ii, explicit[o.uid][1] * scale)) for o in others]
                s_pk, s_avg = share(i, 1.0), share(i * sc, sc)
                srcs = [("dev", d)]
            else:
                s_pk, s_avg, srcs = [(d, i)], [(d, i * sc)], [("pin", None)]
            rec = _run(tm, k, s_avg, s_pk, srcs, vsup.get(k.split(".")[-1].lower(), P["default_supply_v"]),
                       f"{n}:{t}->{k}")
            rec["role"] = "power_device_net"
            rows.append(rec)
    meas = [r for r in rows if r.get("status") == "measured"]
    missing = [r for r in rows if r.get("status") != "measured"]
    if not rows or missing:
        # This branch is reached only when current analysis is required.  Do
        # not let other rails or the geometry-only conventions stand in for a
        # required current path that the resistor model could not represent.
        return {"score": None, "status": "partial" if meas or any(r.get("status") == "partial" for r in rows)
                else "unavailable", "subscores": {"conventions": conv_score, "current": None},
                "conventions": conv_rows, "nets": rows, "problems": problems,
                "reason": "Required current-path measurements are incomplete: " +
                          ("; ".join(r.get("net", "unknown") for r in missing) if missing else "no analysable path")}

    def agg(key):
        vals = [(r[key], r.get("total_current_mA", 1.0) or 1.0) for r in meas if r.get(key) is not None]
        return wmean(vals)

    subs = {"width": agg("width_score"), "vias": agg("via_score"), "ir": agg("ir_score")}
    sw = P["power_sub_weights"]
    current_score = wmean((subs[k], sw[k]) for k in sw)
    total = wmean([(conv_score, 0.5), (current_score, 0.5)])
    subs.update(conventions=conv_score, current=current_score)
    return {"score": total, "status": "measured", "subscores": subs, "nets": rows, "problems": problems,
            "conventions": conv_rows,
            "peak_scaled_devices": {explicit[l][0]: round(v, 4) for l, v in avg_scale.items() if v < 1},
            "em_limits_note": "EM: SkyWater tech LEF DC average at Tj=90C; li1 limit is an assumption "
                              "(no public value).  Annotated peak currents are scaled to the rail DC "
                              "current for EM and used as-is only for the dynamic IR drop."}
