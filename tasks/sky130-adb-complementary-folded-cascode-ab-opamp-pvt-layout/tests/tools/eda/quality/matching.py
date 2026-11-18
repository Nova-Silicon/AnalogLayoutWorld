"""Matching score (v3): placement (adjacent+aligned, common centroid,
mirror symmetry), environment consistency, dummy factor, orientation penalty.

v3 group score = placement * (env_floor + (1 - env_floor) * environment)
                 * dummy_factor * orientation_penalty
  placement (common-centroid / interdigitated intent)
      = max(Q_cc, adj_credit * Q_adj * g, glob_credit * Q_glob * far(gap))
        g = adj_glob_floor + (1 - adj_glob_floor) * Q_glob  (pairs only)
  placement (mirror-symmetric intent)
      = max(Q_sym * (mirror_compact_floor + (1 - floor) * compactness),
            adj_credit * Q_adj * g)
    Q_adj  = compactness (MST of edge-to-edge member gaps / device size,
             ramp adj_full..adj_zero) * (0.5 + 0.5 * aligned fraction)
    Q_glob = pair symmetric about the layout's fitted axis (far but symmetric)
  environment = consistency of the members' finger neighbourhoods (what each
      finger sees on both sides within ~1.5 pitches: array finger or dummy /
      foreign device / nothing; 1 - max total-variation distance between
      members), blended with the well/tap distance spread;
  dummy_factor = 1 - dummy_missing_penalty * (1 - end-treatment score):
      dummies only affect the array-end fingers, so missing them costs at most
      dummy_missing_penalty (0.15).
  A group is "dispersed" when placement < dispersed_placement (neither
  adjacent, common-centroid nor symmetric) -- used by the meaningless gate.

Earlier (v1/v2) definitions below are kept for the individual terms.

Definitions (s = sqrt of mean member footprint area; footprint = sum of the
member's finger bounding boxes including S/D or resistor heads):

* common centroid: every member (side) centroid c_i vs the area-weighted group
  centroid c_g, d_i = 2|c_i - c_g| / s, score = mean ramp(d_i; cc_full, cc_zero)
  (1 below cc_full, linear to 0 at cc_zero = 0.5 device sizes).  For two equal
  members d is the centroid distance over the device size.  Interdigitated
  intent: ramp score x mixing.
* mixing (interdigitation): fraction of nearest-neighbour finger pairs that
  belong to different members, divided by its random-mixing expectation
  1 - sum p_i^2, capped at 1.  N/A when every member has a single finger.
* mirror symmetry: pairs (A, B).  Local residual = best of vertical/horizontal
  axis through the pair midpoint (|yA - yB| or |xA - xB|) / s; global residual
  uses the single axis fitted (weighted median of midpoints, best orientation)
  over all mirror-symmetric pairs of the design.  Pair score =
  ramp(local) * (0.5 + 0.5 * ramp(global)) (sym_full, sym_zero).
* orientation: penalty only -- group score *= max(0, 1 - k * fraction of
  MOS/resistor fingers whose gate / body direction differs from the majority).
* dummy: for each row end of the group's MOS/resistor fingers, look outward up
  to ``dummy_search_pitches`` finger pitches in the flattened GDS for a parallel
  poly stripe.  Not part of any LVS-matched device -> dummy (1.0; dummy
  transistor if it crosses diffusion, dummy poly otherwise); gate/body of
  another matched device -> active neighbour (0.5, same litho environment but
  not a dummy); bare diffusion extension -> 0.5; nothing -> 0.  BJT groups:
  count BJT marker (82/44) structures that are not matched devices around the
  group.  Unmatched layout devices in the lvsdb are reported separately.
* environment: per finger, distance to the nearest nwell edge (inside for PMOS,
  outside for NMOS) clamped at the WPE range, and distance to the nearest tap
  clamped at env_tap_clamp; member means; geometric score = mean of
  exp(-spread/d0).  Environment = min(geometric, end-treatment score), the
  end-treatment score being the dummy score: array-end fingers without a
  dummy do not see the interior environment, whatever the well distances.
"""

from __future__ import annotations

import math
import statistics

import numpy as np
import klayout.db as kdb
from shapely.geometry import box as sbox

from .constants import P
from .geom import region_to_shapely, boxes_region, soft, wmean, ramp
from .names import stem


class Member:
    def __init__(self, names, devices):
        self.names = list(names)
        self.devices = list(devices)

    @property
    def fingers(self):
        return [(f, d) for d in self.devices for f in d.fingers]

    @property
    def area(self):
        return sum(f.area for f, _ in self.fingers)

    @property
    def center(self):
        a = self.area or 1.0
        return (sum(f.center[0] * f.area for f, _ in self.fingers) / a,
                sum(f.center[1] * f.area for f, _ in self.fingers) / a)

    @property
    def label(self):
        return "+".join(self.names)


def _members(resolved):
    seen, out = {}, []
    for name, devs in resolved:
        key = tuple(sorted(d.uid for d in devs))
        if key in seen:
            seen[key].names.append(name)
            continue
        m = Member([name], devs)
        seen[key] = m
        out.append(m)
    return out


def _sides(group, members):
    """Return (sides, pairs) where sides are merged Members for CC/ID analysis
    and pairs are (A, B) Members for mirror-symmetry analysis."""
    n = len(members)
    if n == 2:
        return members, [(members[0], members[1])]
    stems = {}
    for m in members:
        stems.setdefault(stem(m.names[0]), []).append(m)
    if group.get("kind") == "pair" and len(stems) == 2 and len({len(v) for v in stems.values()}) == 1:
        sides = [Member(sum((x.names for x in v), []), sum((x.devices for x in v), []))
                 for v in stems.values()]
        a, b = list(stems.values())
        return sides, list(zip(a, b))
    pairs = [(members[i], members[i + 1]) for i in range(0, n - 1, 2)]
    return members, pairs


def _cc(sides):
    tot = sum(s.area for s in sides) or 1.0
    cg = (sum(s.center[0] * s.area for s in sides) / tot, sum(s.center[1] * s.area for s in sides) / tot)
    size = math.sqrt(statistics.mean(s.area for s in sides)) or 1.0
    ds = [2 * math.dist(s.center, cg) / size for s in sides]
    return statistics.mean(ramp(d, P["cc_full"], P["cc_zero"]) for d in ds), {
        "group_centroid": cg, "size_um": size, "member_offsets": [round(d, 3) for d in ds]}


def _mixing(sides):
    labels, pts = [], []
    for i, s in enumerate(sides):
        for f, _ in s.fingers:
            labels.append(i)
            pts.append(f.center)
    if len(pts) < 3 or all(len(s.fingers) == 1 for s in sides):
        return None, "single-finger members: interdigitation not applicable"
    P_ = np.array(pts)
    D = np.hypot(P_[:, None, 0] - P_[None, :, 0], P_[:, None, 1] - P_[None, :, 1])
    np.fill_diagonal(D, np.inf)
    k = min(2, len(pts) - 1)
    diff = tot = 0
    for i in range(len(pts)):
        for j in np.argsort(D[i])[:k]:
            tot += 1
            diff += labels[i] != labels[j]
    counts = np.bincount(labels)
    p = counts / counts.sum()
    expected = 1 - float((p ** 2).sum())
    if expected <= 0:
        return None, "single member"
    frac = diff / tot
    return min(1.0, frac / expected), f"neighbour mixing {frac:.2f} vs random {expected:.2f}"


def _axis_fit(pairs_w):
    """pairs_w: list of (A, B, weight).  Returns {'V': x0, 'H': y0, 'best': o}.

    For each orientation the axis is placed at the pair midpoint (candidate)
    minimising the weighted total residual, i.e. the axis shared by most of the
    weight; the orientation with the lower total residual is 'best'.
    """
    if not pairs_w:
        return None
    out, res = {}, {}
    for o, k in (("V", 0), ("H", 1)):
        cands = [(a.center[k] + b.center[k]) / 2 for a, b, _ in pairs_w]
        best = min(cands, key=lambda x0: sum(w * _sym_res(a, b, o, x0) for a, b, w in pairs_w))
        out[o] = best
        res[o] = sum(w * _sym_res(a, b, o, best) for a, b, w in pairs_w)
    out["best"] = min(res, key=res.get)
    return out


def _sym_res(a, b, o, axis):
    s = math.sqrt((a.area + b.area) / 2) or 1.0
    (xa, ya), (xb, yb) = a.center, b.center
    if o == "V":
        return math.hypot(xa + xb - 2 * axis, ya - yb) / s
    return math.hypot(ya + yb - 2 * axis, xa - xb) / s


def _orientation(members):
    by_cls = {}
    for m in members:
        for f, d in m.fingers:
            if d.cls in ("MOS", "RES") and f.orient:
                by_cls.setdefault(d.cls, []).append(f.orient)
    if not by_cls:
        return None, "no MOS/resistor fingers"
    vals = []
    for cls, ors in by_cls.items():
        maj = max(set(ors), key=ors.count)
        vals.append(ors.count(maj) / len(ors))
    return statistics.mean(vals), {c: {"V": o.count("V"), "H": o.count("H")} for c, o in by_cls.items()}


class Context:
    """Per-trial geometry caches used by the matching analysis."""

    def __init__(self, tm):
        self.tm = tm
        dbu = tm.dbu
        self.dbu = dbu
        self.poly = tm.gds["poly"]
        self.diff = tm.gds["diff"]
        self.nwell_s = region_to_shapely(tm.gds["nwell"], dbu)
        self.nwell_b = self.nwell_s.boundary if not self.nwell_s.is_empty else None
        self.tap_s = region_to_shapely(tm.gds["tap"], dbu)
        matched = [d for d in tm.devices if d.ref]
        self.mos_core = boxes_region([f.core for d in matched if d.cls == "MOS" for f in d.fingers], dbu).merged()
        self.res_core = boxes_region([f.core for d in matched if d.cls == "RES" for f in d.fingers], dbu).merged()
        self.core_owner = []  # (box, device) for matched MOS/RES fingers
        for d in matched:
            if d.cls in ("MOS", "RES"):
                for f in d.fingers:
                    self.core_owner.append((f.core, d))
        self.bjt_boxes = [f.full for d in matched if d.cls == "BJT" for f in d.fingers]


def _rows(fingers, orient):
    """Cluster finger cores into rows along the array axis."""
    k_par = 1 if orient == "V" else 0  # coordinate along the stripe
    rows = []
    for f, d in sorted(fingers, key=lambda fd: fd[0].center[k_par]):
        lo, hi = f.core[k_par], f.core[k_par + 2]
        for r in rows:
            olap = min(hi, r["hi"]) - max(lo, r["lo"])
            if olap > 0.5 * min(hi - lo, r["hi"] - r["lo"]):
                r["f"].append((f, d))
                r["lo"], r["hi"] = min(lo, r["lo"]), max(hi, r["hi"])
                break
        else:
            rows.append({"lo": lo, "hi": hi, "f": [(f, d)]})
    return rows


def _end_probe(ctx, row, orient, side, group_ids, cls):
    """Classify what lies beyond one end of a row. Returns dict."""
    dbu = ctx.dbu
    k = 0 if orient == "V" else 1  # array axis coordinate index
    fs = sorted(row["f"], key=lambda fd: fd[0].center[k])
    f_end, d_end = fs[0] if side < 0 else fs[-1]
    width_core = f_end.core[k + 2] - f_end.core[k]
    full_w = f_end.full[k + 2] - f_end.full[k]
    # finger pitch of the end device itself (not the spacing between members)
    own = sorted(f.center[k] for f, d in fs if d.uid == d_end.uid)
    steps = [b - a for a, b in zip(own, own[1:]) if b - a > 1e-6]
    pitch = statistics.median(steps) if steps else full_w + 0.3
    search = max(P["dummy_search_pitches"] * pitch, 1.5)
    near = max(pitch, 1.0)  # an active neighbour counts only at about one pitch
    edge = f_end.core[k] if side < 0 else f_end.core[k + 2]
    lo, hi = row["lo"], row["hi"]
    span = hi - lo
    if side < 0:
        a, b = edge - search, edge - 1e-3
    else:
        a, b = edge + 1e-3, edge + search
    win = (a, lo, b, hi) if orient == "V" else (lo, a, hi, b)
    wreg = kdb.Region(kdb.Box(*(round(v / dbu) for v in win)))
    point = ((a + b) / 2, (lo + hi) / 2) if orient == "V" else ((lo + hi) / 2, (a + b) / 2)
    cand = (ctx.poly & wreg)
    best = None
    for poly in cand.each_merged():
        bb = poly.bbox()
        x1, y1, x2, y2 = bb.left * dbu, bb.bottom * dbu, bb.right * dbu, bb.top * dbu
        along = (y2 - y1) if orient == "V" else (x2 - x1)
        across = (x2 - x1) if orient == "V" else (y2 - y1)
        if along < 0.5 * span or across > 3 * max(width_core, 0.15) + 0.5:
            continue  # not a parallel finger-like stripe
        dist = (edge - (x2 if orient == "V" else y2)) if side < 0 else ((x1 if orient == "V" else y1) - edge)
        dist = max(dist, 0.0)
        preg = kdb.Region(poly)
        owners = [d for (bx, d) in ctx.core_owner
                  if not (bx[2] <= x1 or bx[0] >= x2 or bx[3] <= y1 or bx[1] >= y2)]
        owners = [d for d in owners if d.uid not in group_ids]
        if owners and dist > near:
            continue
        if owners:
            kind, score = f"active neighbour {owners[0].ref}", P["dummy_active_neighbour"]
        elif cls == "MOS" and not (preg & ctx.diff).is_empty():
            kind, score = "dummy transistor (poly over diffusion, not an LVS device)", 1.0
        elif cls == "MOS":
            kind, score = "dummy poly stripe", 1.0
        else:
            kind, score = "dummy resistor stripe", 1.0
        if best is None or dist < best["dist"]:
            best = {"kind": kind, "score": score, "dist": round(dist, 3),
                    "stripe": [round(v, 3) for v in (x1, y1, x2, y2)]}
    if best is None and cls == "MOS":
        dreg = ctx.diff & wreg
        if not dreg.is_empty():
            bb = dreg.bbox()
            ext = (edge - bb.left * dbu) if side < 0 else (bb.right * dbu - edge)
            sd = (full_w - width_core) / 2
            if ext > sd + 0.5 * pitch:
                best = {"kind": "diffusion extension without dummy gate", "score": P["dummy_diff_extension"], "dist": 0.0}
    if best is None:
        best = {"kind": "none", "score": 0.0, "dist": None}
    best["point"] = [round(v, 3) for v in point]
    best["window"] = [round(v, 3) for v in win]
    return best


def _dummy(ctx, members):
    group_ids = {d.uid for m in members for d in m.devices}
    fingers = [(f, d) for m in members for f, d in m.fingers]
    ends = []
    for cls in ("MOS", "RES"):
        for orient in ("V", "H"):
            fs = [(f, d) for f, d in fingers if d.cls == cls and f.orient == orient]
            if not fs:
                continue
            for row in _rows(fs, orient):
                for side in (-1, 1):
                    e = _end_probe(ctx, row, orient, side, group_ids, cls)
                    e["class"] = cls
                    ends.append(e)
    bjts = [(f, d) for f, d in fingers if d.cls == "BJT"]
    bjt_detail = None
    if bjts:
        # BJT dummies: BJT marker structures (82/44) near the group that are
        # not matched devices.  Matched BJT boxes are excluded.
        tm = ctx.tm
        xs1, ys1, xs2, ys2 = zip(*(f.full for f, _ in bjts))
        size = max(f.full[2] - f.full[0] for f, _ in bjts)
        reach = 2.5 * size
        win = (min(xs1) - reach, min(ys1) - reach, max(xs2) + reach, max(ys2) + reach)
        g = kdb.Layout()
        g.read(str(tm.gds_path))
        top = max(g.top_cells(), key=lambda c: c.dbbox().area())
        li = g.find_layer(82, 44)
        found = 0
        if li is not None:
            reg = kdb.Region(top.begin_shapes_rec(li)).merged()
            wreg = kdb.Region(kdb.Box(*(round(v / ctx.dbu) for v in win)))
            matched = boxes_region([f.full for d in tm.devices if d.ref and d.cls == "BJT" for f in d.fingers], ctx.dbu)
            for p in (reg & wreg).each_merged():
                if (kdb.Region(p) & matched).is_empty():
                    found += 1
        unmatched = [d for d in tm.unmatched_layout_devices if d.cls == "BJT"]
        bjt_detail = {"unmatched_marker_structures": found, "unmatched_lvsdb_bjts": len(unmatched),
                      "window": [round(v, 2) for v in win]}
        ends.append({"class": "BJT", "kind": f"{found} non-device BJT structures nearby",
                     "score": min(1.0, (found + len(unmatched)) / 8.0), "point": None})
    if not ends:
        return None, {"ends": [], "note": "no MOS/resistor/BJT fingers (capacitors only)"}
    return statistics.mean(e["score"] for e in ends), {"ends": ends, "bjt": bjt_detail}


def _environment(ctx, sides):
    wc, tc = P["env_well_clamp_um"], P["env_tap_clamp_um"]
    well_vals, tap_vals = [], []
    for s in sides:
        wv, tv = [], []
        for f, d in s.fingers:
            g = sbox(*f.core)
            if d.cls == "MOS" and ctx.nwell_b is not None:
                dist = g.distance(ctx.nwell_b) if d.polarity == "p" else g.distance(ctx.nwell_s)
                wv.append(min(dist, wc))
            elif d.cls == "MOS":
                wv.append(wc)
            if d.cls in ("MOS", "RES") and not ctx.tap_s.is_empty:
                tv.append(min(g.distance(ctx.tap_s), tc))
        if wv:
            well_vals.append(statistics.mean(wv))
        if tv:
            tap_vals.append(statistics.mean(tv))
    parts, det = [], {}
    if len(well_vals) >= 2:
        spread = max(well_vals) - min(well_vals)
        parts.append(math.exp(-spread / P["env_well_d0_um"]))
        det["well_dist_um"] = [round(v, 3) for v in well_vals]
    if len(tap_vals) >= 2:
        spread = max(tap_vals) - min(tap_vals)
        parts.append(math.exp(-spread / P["env_tap_d0_um"]))
        det["tap_dist_um"] = [round(v, 3) for v in tap_vals]
    if not parts:
        return None, {"note": "no MOS/resistor members to compare"}
    return statistics.mean(parts), det


def _gap(a, b):
    """Edge-to-edge distance of two boxes (Chebyshev; 0 if overlapping)."""
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return max(dx, dy)


def _side_box(side):
    xs1, ys1, xs2, ys2 = zip(*(f.full for f, _ in side.fingers))
    return (min(xs1), min(ys1), max(xs2), max(ys2))


def _adjacency(sides):
    """Compactness/alignment of the members: MST over member boxes with
    edge-to-edge gaps.  Returns (Q_adj, detail)."""
    boxes = [_side_box(sd) for sd in sides]
    size = math.sqrt(statistics.mean(sd.area for sd in sides)) or 1.0
    n = len(boxes)
    used, best, par = [False] * n, [float("inf")] * n, [-1] * n
    best[0] = 0.0
    edges = []
    for _ in range(n):
        i = min((k for k in range(n) if not used[k]), key=lambda k: best[k])
        used[i] = True
        if par[i] >= 0:
            edges.append((par[i], i, best[i]))
        for k in range(n):
            if not used[k]:
                g = _gap(boxes[i], boxes[k])
                if g < best[k]:
                    best[k], par[k] = g, i
    max_gap = max((e[2] for e in edges), default=0.0)

    def aligned(a, b):
        ox = min(a[2], b[2]) - max(a[0], b[0])
        oy = min(a[3], b[3]) - max(a[1], b[1])
        return (ox >= 0.5 * min(a[2] - a[0], b[2] - b[0])) or (oy >= 0.5 * min(a[3] - a[1], b[3] - b[1]))

    al = statistics.mean(1.0 if aligned(boxes[i], boxes[j]) else 0.0 for i, j, _ in edges) if edges else 1.0
    compact = ramp(max_gap / size, P["adj_full"], P["adj_zero"])
    return compact * (0.5 + 0.5 * al), {"max_gap_um": round(max_gap, 3), "gap_over_size": round(max_gap / size, 3),
                                       "aligned_fraction": round(al, 3), "compactness": round(compact, 3)}


def _neighbour_hist(ctx, sides, group_ids):
    """Per member, histogram of what each finger sees on both sides along the
    array axis within ~1.5 finger pitches: 'array' (finger of a group member or
    a dummy stripe), 'foreign' (finger of another device), 'none'."""
    hists = []
    for sd in sides:
        cnt = {"array": 0, "foreign": 0, "none": 0}
        fingers = [(f, d) for f, d in sd.fingers if d.cls in ("MOS", "RES") and f.orient]
        if not fingers:
            hists.append(None)
            continue
        for f, d in fingers:
            k = 0 if f.orient == "V" else 1          # array axis
            q = 1 - k                                 # along-stripe axis
            own = sorted(g.center[k] for g in d.fingers if g.orient == f.orient)
            steps = [b - a for a, b in zip(own, own[1:]) if b - a > 1e-6]
            pitch = statistics.median(steps) if steps else (f.full[k + 2] - f.full[k]) + 0.3
            reach = 1.5 * pitch
            lo, hi = f.core[q], f.core[q + 2]
            for side in (-1, 1):
                edge = f.core[k] if side < 0 else f.core[k + 2]
                kind, best = "none", None
                for bx, owner in ctx.core_owner:
                    if bx == f.core:
                        continue
                    olap = min(hi, bx[q + 2]) - max(lo, bx[q])
                    if olap < 0.5 * (hi - lo):
                        continue
                    dist = (edge - bx[k + 2]) if side < 0 else (bx[k] - edge)
                    if dist < -1e-6 or dist > reach:
                        continue
                    if best is None or dist < best:
                        best = dist
                        kind = "array" if owner.uid in group_ids else "foreign"
                if best is None:
                    # a poly stripe that is not an LVS device = dummy (array-like)
                    a, b = (edge - reach, edge) if side < 0 else (edge, edge + reach)
                    win = (a, lo, b, hi) if k == 0 else (lo, a, hi, b)
                    wreg = kdb.Region(kdb.Box(*(round(v / ctx.dbu) for v in win)))
                    if not (ctx.poly & wreg).is_empty() and (ctx.mos_core & wreg).is_empty() \
                            and (ctx.res_core & wreg).is_empty():
                        kind = "array"
                cnt[kind] += 1
        tot = sum(cnt.values())
        hists.append({k: v / tot for k, v in cnt.items()})
    return hists


def _consistency(hists):
    hs = [h for h in hists if h is not None]
    if len(hs) < 2:
        return None
    worst = 0.0
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            tv = 0.5 * sum(abs(hs[i][k] - hs[j][k]) for k in hs[i])
            worst = max(worst, tv)
    return 1.0 - worst


def score_matching(tm, annotation) -> dict:
    groups = annotation.get("matched_groups") or []
    if not groups:
        return {"score": None, "status": "unavailable", "reason": "no matched_groups in annotation"}
    ctx = Context(tm)
    prepared = []
    for g in groups:
        resolved, problems = tm.resolve_group(g["devices"])
        # any member that cannot be resolved makes the whole group unavailable
        # (no guessing: a partial group would be scored as something else)
        failed = [x for x in problems if ": note: " not in x]
        members = [] if failed else _members(resolved)
        prepared.append((g, members, problems))
    # global symmetry axis: mirror-symmetric pairs (fallback: all 2-member groups)
    sym_pairs, any_pairs = [], []
    for g, members, _ in prepared:
        if len(members) >= 2:
            sides, pairs = _sides(g, members)
            w = float(g.get("weight", 1))
            if g.get("intent") == "mirror_symmetric":
                sym_pairs += [(a, b, w) for a, b in pairs]
            if len(sides) == 2:
                any_pairs.append((sides[0], sides[1], w))
    # the circuit's symmetry axis is fitted over every two-member group
    gaxis = _axis_fit(any_pairs or sym_pairs) if (any_pairs or sym_pairs) else None
    out_groups = []
    for g, members, problems in prepared:
        rec = {"name": g.get("name"), "kind": g.get("kind"), "intent": g.get("intent"),
               "weight": g.get("weight", 1), "devices": g.get("devices"), "problems": problems,
               "members": [{"names": m.names, "center": [round(c, 3) for c in m.center],
                            "fingers": len(m.fingers), "area_um2": round(m.area, 3)} for m in members]}
        failed = [x for x in problems if ": note: " not in x]
        if failed:
            rec.update(score=None, status="unavailable",
                       reason="unresolved member(s): " + "; ".join(failed))
            out_groups.append(rec)
            continue
        if len(members) < 2:
            rec.update(score=None, status="unavailable",
                       reason="fewer than two distinct layout devices (members share one combined device)")
            out_groups.append(rec)
            continue
        sides, pairs = _sides(g, members)
        sub, det = {}, {}
        intent = g.get("intent")
        group_ids = {d.uid for m in members for d in m.devices}
        q_adj, det["adjacency"] = _adjacency(sides)
        gap_s = det["adjacency"]["gap_over_size"]
        compact = det["adjacency"]["compactness"]
        q_glob = None
        if gaxis and len(sides) == 2:
            q_glob = ramp(_sym_res(sides[0], sides[1], gaxis["best"], gaxis[gaxis["best"]]),
                          P["sym_full"], P["sym_zero"])
        # adjacency counts fully only when the pair also sits on the circuit's
        # symmetry axis (multi-member groups: adjacency alone)
        g_fac = 1.0 if q_glob is None else P["adj_glob_floor"] + (1 - P["adj_glob_floor"]) * q_glob
        q_adj_sym = q_adj * g_fac
        # far apart but symmetric about the axis: credit decays with distance
        q_far = (q_glob or 0.0) * ramp(gap_s, P["far_full"], P["far_zero"])
        if intent == "mirror_symmetric":
            pscores = []
            for a, b in pairs:
                loc = {o: _sym_res(a, b, o, ((a.center[0] + b.center[0]) / 2 if o == "V"
                                             else (a.center[1] + b.center[1]) / 2)) for o in ("V", "H")}
                lo_o = min(loc, key=loc.get)
                glob = _sym_res(a, b, gaxis["best"], gaxis[gaxis["best"]]) if gaxis else None
                f_loc = ramp(loc[lo_o], P["sym_full"], P["sym_zero"])
                f_glob = ramp(glob, P["sym_full"], P["sym_zero"]) if glob is not None else f_loc
                s_ = f_loc * (0.5 + 0.5 * f_glob)
                pscores.append(s_)
                det.setdefault("pairs", []).append({
                    "a": a.label, "b": b.label, "local_axis": lo_o, "local_residual": round(loc[lo_o], 3),
                    "global_residual": None if glob is None else round(glob, 3), "score": round(s_, 3)})
            q_sym = statistics.mean(pscores) * (P["mirror_compact_floor"] + (1 - P["mirror_compact_floor"]) * compact)
            placement = max(q_sym, P["adj_credit"] * q_adj_sym)
            det["placement_terms"] = {"symmetry_x_compact": round(q_sym, 3), "adjacent_on_axis": round(q_adj_sym, 3)}
        else:
            cc, ccd = _cc(sides)
            mix, mixd = _mixing(sides)
            det["centroid"] = ccd
            det["mixing"] = {"value": mix, "note": mixd}
            q_cc = cc * mix if (intent == "interdigitated" and mix is not None) else cc
            placement = max(q_cc, P["adj_credit"] * q_adj_sym, P["glob_credit"] * q_far)
            det["placement_terms"] = {"common_centroid": round(q_cc, 3), "adjacent": round(q_adj, 3),
                                      "global_symmetric": None if q_glob is None else round(q_glob, 3),
                                      "adjacent_on_axis": round(q_adj_sym, 3), "far_symmetric": round(q_far, 3)}
        sub["placement"] = placement
        orient_frac, det["orientation"] = _orientation(members)
        end_score, det["dummy"] = _dummy(ctx, members)
        sub["dummy"] = end_score
        hists = _neighbour_hist(ctx, sides, group_ids)
        cons = _consistency(hists)
        geo_env, det["environment"] = _environment(ctx, sides)
        det["environment"]["neighbour_histograms"] = hists
        det["environment"]["consistency"] = cons
        parts = [(cons, P["env_consistency_weight"]), (geo_env, 1.0 - P["env_consistency_weight"])]
        sub["environment"] = wmean(parts)
        dummy_factor = 1.0 - P["dummy_missing_penalty"] * (1.0 - end_score) if end_score is not None else 1.0
        sub["dummy_factor"] = dummy_factor
        env = sub["environment"]
        base = placement * (P["env_floor"] + (1 - P["env_floor"]) * env) if env is not None else placement
        penalty = 1.0
        if orient_frac is not None:
            penalty = max(0.0, 1.0 - P["orient_penalty_k"] * (1.0 - orient_frac))
        sub["orientation_penalty"] = penalty
        score = base * dummy_factor * penalty if base is not None else None
        rec.update(score=score, status="measured", subscores=sub, detail=det,
                   dispersed=bool(placement < P["dispersed_placement"]),
                   sides=[sd.label for sd in sides],
                   side_centers=[[round(c, 3) for c in sd.center] for sd in sides])
        out_groups.append(rec)
    total = wmean((r["score"], float(r["weight"])) for r in out_groups)
    keys = ["placement", "environment", "dummy", "dummy_factor", "orientation_penalty"]
    subs = {k: wmean((r.get("subscores", {}).get(k), float(r["weight"])) for r in out_groups) for k in keys}
    meas = [r for r in out_groups if r.get("status") == "measured"]
    wsum = sum(float(r["weight"]) for r in meas)
    disp = sum(float(r["weight"]) for r in meas if r.get("dispersed")) / wsum if wsum else None
    return {"score": total, "status": "measured" if total is not None else "unavailable",
            "subscores": subs, "global_axis": gaxis, "groups": out_groups,
            "dispersed_weight_fraction": disp,
            "unmatched_layout_devices": [d.lname for d in tm.unmatched_layout_devices],
            "unmatched_reference_devices": tm.unmatched_ref_devices}
