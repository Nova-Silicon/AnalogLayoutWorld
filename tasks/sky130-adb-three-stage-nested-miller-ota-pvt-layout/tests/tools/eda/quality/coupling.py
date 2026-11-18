"""Coupling between aggressor and victim nets, critical-net routing and
differential-pair matching.

Capacitance model (all coefficients from constants.py, i.e. the open_pdks
Magic tech file):

* same-layer sidewall coupling: KLayout ``separation_check`` with projection
  metrics finds facing edges of the two nets closer than the Magic side halo
  (8 um); each facing segment of length L at spacing s contributes
  ``coef * L / (s + offset)``.  A facing gap at least ``shield_fraction``
  covered by metal of any third net on that layer counts as shielded.
* layer-to-layer overlap: ``OVERLAP_CAP * area`` for adjacent layers, and for
  next-but-one layers only where no intermediate-layer metal (any net) lies in
  between.  Areas inside MIM capacitor plates (capm/cap2m) are excluded: they
  are designed capacitors, not parasitics.
* victim total capacitance: wire area + perimeter cap to substrate, sidewall
  and overlap coupling to every other net, plus device loading (gate oxide
  Cox*W*L, S/D junction Cj*AS/AD, MIM Cmim*A) -- the device terms are
  assumptions (constants.py [ASSUME]).

coupling ratio rho(v) = sum over aggressors C_c(a, v) / C_total(v),
score = soft(rho, coupling_rho0); capped at unprotected_cap when the victim
has an unshielded same-layer facing run with an aggressor closer than
protect_spacing_x times the layer's minimum spacing (no shield, not spaced).

Routing: routed length = sum of polygon centre-line lengths over li1..met5;
lower bound = rectilinear MST over the centres of every finger/segment of the
devices on the net and its pin labels (floor mst_floor_um).
li1/met1 inside device footprints are device-internal straps and excluded.
detour ratio = routed / MST; the first ``route_tol_um`` of excess length is
free (ratio_eff = 1 + max(0, routed - MST - tol) / MST); score 1 up to
``detour_free`` then soft(ratio_eff - detour_free, detour_half).

Differential pairs: routed-length mismatch / max(longer route, route_floor_um)
and wire-capacitance mismatch / total node capacitance (incl. device load),
each scored soft(delta, diff_d0), averaged.
"""

from __future__ import annotations

import math
import statistics

import klayout.db as kdb

from . import constants as K
from .constants import P
from .geom import centerline_length, rect_mst_length, soft, wmean
from .layers import METALS

UM = 1e-6


class CapModel:
    def __init__(self, tm):
        self.tm = tm
        self.dbu = tm.dbu
        self._all = {}
        self._wire = {}
        mim = (tm.gds["capm"] + tm.gds["cap2m"]).merged()
        self.mim = mim

    def layer_all(self, m):
        if m not in self._all:
            r = self.tm.layer_region(m)
            f = kdb.Region()
            if r is not None:
                f.insert(r)  # flat copy of the (deep) layer of all nets
                f.merge()
            self._all[m] = f
        return self._all[m]

    def reg(self, key, m):
        return self.tm.net_region(key, m)

    # ---------------------------------------------------------------- pieces
    def sidewall(self, a_key, v_key, m, collect=None, shield=True, others_override=None):
        A = self.reg(a_key, m) if others_override is None else others_override
        V = self.reg(v_key, m)
        if A.is_empty() or V.is_empty():
            return 0.0
        coef, off = K.SIDEWALL[m]
        d = int(round(K.SIDEHALO_UM / self.dbu))
        eps = A.separation_check(V, d, False, kdb.Metrics.Projection)
        if eps.is_empty():
            return 0.0
        third = None
        if shield and others_override is None:
            third = self.layer_all(m) - A - V
        tot = 0.0
        seen = set()
        for ep in eps.each():
            sig = (str(ep.first), str(ep.second))
            if sig in seen:
                continue
            seen.add(sig)
            s = ep.distance() * self.dbu
            L = 0.5 * (ep.first.length() + ep.second.length()) * self.dbu
            if L <= 0:
                continue
            if third is not None and not third.is_empty():
                poly = kdb.Region(ep.polygon(0))
                pa = poly.area()
                if pa > 0 and (poly & third).area() >= P["shield_fraction"] * pa:
                    continue
            c = coef * L / (s + off)
            tot += c
            if collect is not None:
                e1, e2 = ep.first, ep.second
                collect.append({"layer": m, "c_aF": c, "s_um": round(s, 3), "len_um": round(L, 3),
                                "e1": [e1.p1.x * self.dbu, e1.p1.y * self.dbu, e1.p2.x * self.dbu, e1.p2.y * self.dbu],
                                "e2": [e2.p1.x * self.dbu, e2.p1.y * self.dbu, e2.p2.x * self.dbu, e2.p2.y * self.dbu]})
        return tot

    def overlap(self, a_key, v_key, collect=None, a_override=None):
        tot = 0.0
        d2 = self.dbu * self.dbu
        for (up, lo), cap in K.OVERLAP_CAP.items():
            i_up, i_lo = METALS.index(up), METALS.index(lo)
            for x, y in ((a_key, v_key), (v_key, a_key)):
                X = (a_override[up] if (a_override is not None and x == a_key) else self.reg(x, up))
                Y = (a_override[lo] if (a_override is not None and y == a_key) else self.reg(y, lo))
                if X.is_empty() or Y.is_empty():
                    continue
                ov = X & Y
                if ov.is_empty():
                    continue
                for mid in METALS[i_lo + 1:i_up]:
                    ov = ov - self.layer_all(mid)
                if up in ("met4", "met5") or lo in ("met3", "met4"):
                    ov = ov - self.mim
                a = ov.area() * d2
                if a > 0:
                    tot += cap * a
                    if collect is not None:
                        collect.append({"layers": f"{up}/{lo}", "area_um2": round(a, 3), "c_aF": cap * a})
        return tot

    def wire_sub(self, key):
        if key in self._wire:
            return self._wire[key]
        tot = 0.0
        for m in METALS:
            r = self.reg(key, m)
            if r.is_empty():
                continue
            tot += K.AREA_CAP[m] * r.area() * self.dbu ** 2 + K.PERIM_CAP[m] * r.perimeter() * self.dbu
        self._wire[key] = tot
        return tot

    def device_load(self, key):
        """Device capacitance on a net in aF (assumed coefficients)."""
        tot = 0.0
        for d in self.tm.devices:
            if not d.ref:
                continue
            for t, n in d.terms.items():
                if n != key:
                    continue
                p = d.params
                if d.cls == "MOS":
                    if t == "G":
                        tot += K.COX_F_PER_UM2 * (p.get("W", 0) * UM) * (p.get("L", 0) * UM) * 1e18
                    elif t == "S":
                        tot += K.CJ_F_PER_UM2 * p.get("AS", 0) * UM * UM * 1e18
                    elif t == "D":
                        tot += K.CJ_F_PER_UM2 * p.get("AD", 0) * UM * UM * 1e18
                elif d.cls == "CAP" and t in ("A", "B"):
                    tot += K.CMIM_F_PER_UM2 * p.get("A", 0) * UM * UM * 1e18
        return tot

    def coupling_to_all(self, key):
        tot = 0.0
        for m in METALS:
            V = self.reg(key, m)
            if V.is_empty():
                continue
            others = self.layer_all(m) - V
            if others.is_empty():
                continue
            coef, off = K.SIDEWALL[m]
            d = int(round(K.SIDEHALO_UM / self.dbu))
            seen = set()
            for ep in others.separation_check(V, d, False, kdb.Metrics.Projection).each():
                sig = (str(ep.first), str(ep.second))
                if sig in seen:
                    continue
                seen.add(sig)
                s = ep.distance() * self.dbu
                L = 0.5 * (ep.first.length() + ep.second.length()) * self.dbu
                tot += coef * L / (s + off)
        d2 = self.dbu ** 2
        for (up, lo), cap in K.OVERLAP_CAP.items():
            if (up, lo) not in (("met1", "li1"), ("met2", "met1"), ("met3", "met2"), ("met4", "met3"), ("met5", "met4")):
                continue
            Vu, Vl = self.reg(key, up), self.reg(key, lo)
            if not Vu.is_empty():
                tot += cap * ((Vu & (self.layer_all(lo) - Vl)) - self.mim).area() * d2
            if not Vl.is_empty():
                tot += cap * ((Vl & (self.layer_all(up) - Vu)) - self.mim).area() * d2
        return tot

    def total(self, key):
        return self.wire_sub(key) + self.coupling_to_all(key) + self.device_load(key)


def net_rects(tm, key):
    """Connection targets of a net as degenerate boxes: the centre of every
    finger / segment of each device on the net (so that finger-to-finger hops
    inside a multi-finger device are part of the lower bound) plus pin labels.
    Resistors: the centre between the two heads (where the wires connect),
    not the centre of a folded body."""
    rects = []
    for d in tm.devices:
        if not d.ref or key not in d.terms.values():
            continue
        for f in d.fingers:
            if d.cls == "RES":
                b = f.term_span
                x, y = (b[0] + b[2]) / 2, (b[1] + b[3]) / 2
            else:
                x, y = f.center
            rects.append((x, y, x, y))
    rects += [(x, y, x, y) for x, y, _ in tm.port_points(key)]
    return list(dict.fromkeys(rects))


def _footprints(tm):
    if not hasattr(tm, "_dev_fp"):
        from .geom import boxes_region
        # resistors keep the head-span box (the geometry used before the body
        # was sourced): the bbox of a folded body would swallow the routing
        # that crosses it
        tm._dev_fp = boxes_region([f.term_span if d.cls == "RES" else f.full
                                   for d in tm.devices for f in d.fingers], tm.dbu).merged()
    return tm._dev_fp


def route_length(tm, key, *, diagnostics=None):
    """Routed length: centre-line length per layer; li1/met1 inside device
    footprints (S/D and gate straps) are device-internal and excluded."""
    per = {}
    fp = _footprints(tm)
    for m in METALS:
        r = tm.net_region(key, m)
        if m in ("li1", "met1") and not r.is_empty():
            r = r - fp
        per[m] = centerline_length(r, tm.dbu)
    length = sum(per.values())
    if length != 0 or not math.isfinite(length):
        return length, per
    # An unrelated device's bounding box can cover this net's interconnect.
    # Recover only the formerly undefined zero case; positive legacy lengths
    # and their scores keep the exact same calculation.
    raw = {m: tm.net_region(key, m) for m in METALS}
    raw_area = sum(r.area() for r in raw.values()) * tm.dbu ** 2
    if diagnostics is not None:
        diagnostics.update(method="global_device_footprints", raw_metal_area_um2=raw_area)
    if raw_area <= 0:
        return length, per
    from .geom import boxes_region
    connected = [d for d in tm.devices if key in d.terms.values()]
    if not connected:
        return length, per  # incomplete identity must not masquerade as a route
    own = boxes_region([f.term_span if d.cls == "RES" else f.full
                        for d in connected for f in d.fingers], tm.dbu).merged()
    recovered = {m: centerline_length(r - own if m in ("li1", "met1") else r, tm.dbu)
                 for m, r in raw.items()}
    recovered_length = sum(recovered.values())
    if math.isfinite(recovered_length) and recovered_length > 0:
        if diagnostics is not None:
            diagnostics.update(method="net_connected_device_footprints",
                               original_route_um=length,
                               reason="Unrelated device bounding boxes covered this net's metal")
        return recovered_length, recovered
    return length, per


def _rect_dist(a, b):
    dx = max(0.0, max(a[0], b[0]) - min(a[2], b[2]))
    dy = max(0.0, max(a[1], b[1]) - min(a[3], b[3]))
    return dx + dy


def rect_mst(rects):
    """Rectilinear MST over rectangles (distance between boxes, 0 if touching).
    Returns (length, edges as centre-to-centre segments for drawing)."""
    n = len(rects)
    if n < 2:
        return 0.0, []
    inf = float("inf")
    best, par, used = [inf] * n, [-1] * n, [False] * n
    best[0] = 0.0
    tot, edges = 0.0, []
    for _ in range(n):
        i = min((k for k in range(n) if not used[k]), key=lambda k: best[k])
        used[i] = True
        tot += best[i]
        if par[i] >= 0:
            a, b = rects[par[i]], rects[i]
            edges.append((((a[0] + a[2]) / 2, (a[1] + a[3]) / 2), ((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)))
        for k in range(n):
            if not used[k]:
                dd = _rect_dist(rects[i], rects[k])
                if dd < best[k]:
                    best[k], par[k] = dd, i
    return tot, edges


def score_coupling(tm, annotation) -> dict:
    nets = annotation.get("nets") or {}
    cm = CapModel(tm)
    problems = []

    def resolve(lst):
        out = []
        for n in lst or []:
            k, how = tm.resolve_net(n)
            if k is None:
                problems.append(f"{n}: {how}")
            else:
                out.append((n, k))
        return out

    aggr, vict = resolve(nets.get("aggressors")), resolve(nets.get("victims"))
    crit = resolve(nets.get("critical"))
    dps = []
    for p in nets.get("diff_pairs") or []:
        r = resolve(p)
        if len(r) == 2:
            dps.append(r)
    # ------------------------------------------------------------ coupling
    coupling = {"score": None, "status": "unavailable", "reason": "no aggressor or victim nets"}
    hotspots = []
    # net pairs joined by a schematic capacitor (e.g. a feed-forward MIM):
    # their coupling is designed, not parasitic, so it is not scored
    designed = set()
    for d in tm.devices:
        if d.ref and d.cls == "CAP":
            a, b = d.terms.get("A"), d.terms.get("B")
            if a and b and a != b:
                designed.add(frozenset((a, b)))
    if aggr and vict:
        rows = []
        for vn, vk in vict:
            dev = cm.device_load(vk)
            geo_tot = cm.wire_sub(vk) + cm.coupling_to_all(vk) + dev
            geo_cc, per_aggr = 0.0, {}
            close = []  # unshielded same-layer facing runs closer than 3x min spacing
            for an, ak in aggr:
                if ak == vk:
                    continue
                if frozenset((ak, vk)) in designed:
                    per_aggr[an] = {"excluded": "designed capacitor between these nets"}
                    continue
                coll = []
                c = sum(cm.sidewall(ak, vk, m, collect=coll) for m in METALS)
                c += cm.overlap(ak, vk)
                per_aggr[an] = {"geom_aF": round(c, 3), "pex_aF": None}
                geo_cc += c
                for h in coll:
                    h.update(aggressor=an, victim=vn)
                    if h["s_um"] < P["protect_spacing_x"] * K.MIN_SPACE[h["layer"]]:
                        close.append(h)
                hotspots += coll
            rho = geo_cc / geo_tot if geo_tot > 0 else None
            row = {"victim": vn, "device_load_fF": round(dev / 1000, 4),
                   "geom": {"c_total_fF": round(geo_tot / 1000, 4), "c_couple_fF": round(geo_cc / 1000, 5), "rho": rho},
                   "per_aggressor": per_aggr}
            row["source"] = "geometry (no PEX matrix)"
            row["rho"] = rho
            row["score"] = soft(rho, P["coupling_rho0"]) if rho is not None else None
            # no shield and not spaced >= 3x minimum spacing -> capped
            row["unprotected_runs"] = len(close)
            row["unprotected_len_um"] = round(sum(h["len_um"] for h in close), 2)
            # v4 penalty basis: only the capacitance of the unshielded close
            # runs, relative to the victim's total capacitance
            c_close = sum(h["c_aF"] for h in close)
            row["unprotected_c_fF"] = round(c_close / 1000, 5)
            row["rho_close"] = c_close / geo_tot if geo_tot > 0 else None
            if close and row["score"] is not None:
                row["score"] = min(row["score"], P["unprotected_cap"])
                row["capped"] = True
            rows.append(row)
        sc = [r["score"] for r in rows if r["score"] is not None]
        mean_sc = statistics.mean(sc) if sc else None
        if mean_sc is not None and any(r.get("capped") for r in rows):
            mean_sc = min(mean_sc, P["unprotected_cap"])  # no victim may be left unshielded and close
        sev = [min(1.0, (r["rho_close"] or 0.0) / P["cpl_pen_rho_full"]) for r in rows
               if r.get("unprotected_runs") and r.get("rho_close") is not None]
        worst = max(sev) if sev else 0.0
        coupling_penalty = P["cpl_pen_max"] * worst
        coupling = {"score": mean_sc, "penalty": coupling_penalty, "worst_severity": worst,
                    "status": "measured" if sc else "unavailable", "victims": rows,
                    "source": "geometric estimate"}
    hotspots.sort(key=lambda h: -h["c_aF"])
    # ------------------------------------------------------------ routing
    routing_rows = []
    for n, k in crit:
        measurement = {}
        L, per = route_length(tm, k, diagnostics=measurement)
        rects = net_rects(tm, k)
        mst, edges = rect_mst(rects)
        unavailable = None
        if len(rects) < 2:
            unavailable = "fewer_than_two_targets"
        elif not math.isfinite(L):
            unavailable = "non_finite_route_length"
        elif L < 0:
            unavailable = "negative_route_length"
        elif L == 0:
            unavailable = ("no_metal_geometry" if measurement.get("raw_metal_area_um2", 0) <= 0
                           else "zero_external_route_after_device_exclusion")
        if unavailable:
            routing_rows.append({"net": n, "status": "unavailable", "score": None,
                                 "reason": unavailable, "route_um": L if math.isfinite(L) else None,
                                 "targets": len(rects), "measurement": measurement})
            continue
        mst_eff = max(mst, P["mst_floor_um"])
        ratio = L / mst_eff
        # absolute tolerance: the first route_tol_um of excess length is free
        excess = max(0.0, L - mst_eff - P["route_tol_um"])
        ratio_eff = 1.0 + excess / mst_eff
        sc = 1.0 if ratio_eff <= P["detour_free"] else soft(ratio_eff - P["detour_free"], P["detour_half"])
        routing_rows.append({"net": n, "route_um": round(L, 2), "per_layer_um": {m: round(v, 2) for m, v in per.items() if v},
                             "mst_um": round(mst, 2), "targets": len(rects), "ratio": round(ratio, 3),
                             "ratio_eff": round(ratio_eff, 3), "score": sc,
                             "mst_edges": edges, **({"measurement": measurement} if measurement else {})})
    rs = [r["score"] for r in routing_rows if r.get("score") is not None]
    routing = {"score": statistics.mean(rs) if rs else None,
               "status": "measured" if rs else "unavailable", "nets": routing_rows}
    # ------------------------------------------------------------ diff pairs
    dp_rows = []
    for (pn, pk), (nn, nk) in dps:
        Lp, Ln = route_length(tm, pk)[0], route_length(tm, nk)[0]
        Cp = cm.wire_sub(pk) + cm.coupling_to_all(pk)
        Cn = cm.wire_sub(nk) + cm.coupling_to_all(nk)
        Tp, Tn = Cp + cm.device_load(pk), Cn + cm.device_load(nk)
        # length mismatch relative to the longer route (floor route_floor_um);
        # wire-capacitance mismatch relative to the total node capacitance
        dL = abs(Lp - Ln) / max(Lp, Ln, P["route_floor_um"])
        dC = abs(Cp - Cn) / max(Tp, Tn) if max(Tp, Tn) > 0 else None
        parts = [soft(x, P["diff_d0"]) for x in (dL, dC) if x is not None]
        dp_rows.append({"pair": [pn, nn], "len_um": [round(Lp, 2), round(Ln, 2)], "cap_source": "geometry",
                        "wire_c_fF": [round(Cp / 1000, 4), round(Cn / 1000, 4)],
                        "total_c_fF": [round(Tp / 1000, 4), round(Tn / 1000, 4)],
                        "d_len": dL, "d_cap": dC, "score": statistics.mean(parts) if parts else None})
    ds = [r["score"] for r in dp_rows if r["score"] is not None]
    diff = {"score": statistics.mean(ds) if ds else None,
            "status": "measured" if ds else "unavailable", "pairs": dp_rows}
    sw = P["coupling_sub_weights"]
    subs = {"coupling": coupling["score"], "routing": routing["score"], "diff_pairs": diff["score"]}
    total = wmean((subs[k], sw[k]) for k in sw)
    return {"score": total, "status": "measured" if total is not None else "unavailable",
            "subscores": subs, "coupling": coupling, "routing": routing, "diff_pairs": diff,
            "hotspots": hotspots[:40], "problems": problems,
            "pex_matrix": False,
            "model": "geometric estimate using recorded Magic coefficients; no named PEX matrix consumed"}
