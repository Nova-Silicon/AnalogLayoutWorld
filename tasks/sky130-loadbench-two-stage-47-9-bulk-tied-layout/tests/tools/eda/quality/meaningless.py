"""Gate for meaningless layouts ("devices dropped anywhere, wires pulled
across"): such layouts get only the gate score; area and craft are not scored.

Features (annotation-free unless noted):
  fill_ratio      legacy feature argument, unused by the morphology verdict;
                  the scorer owns raw effective-area and aspect thresholds
  aspect          long / short side of the layout bbox
  dispersed       weight fraction of matched groups whose placement is below
                  P['dispersed_placement'] (needs the annotation; else None)
  detour_total    sum(routed length) / sum(MST lower bound) over signal nets
  detour_median   median per-net routed / MST
  long_wire_frac  (no device-size floor) length of straight metal segments spanning >= half the
                  layout (in their direction) / total routed signal length
Signal nets = LVS nets except body-tie rails (a net that is the body terminal
of >= half of the NMOS or PMOS devices).  The annotation is deliberately not
used, so the verdict does not depend on how a task was annotated.

The morphology check combines four features:
  bus_nets       distinct signal nets owning a long straight segment
                 (>= half the layout and >= 3x the median device size) in the
                 dominant direction (rows of parallel bus lines)
  drops          perpendicular segments (>= max(5 um, 15 % of the layout
                 height)) of the same nets
  largest_row_fraction  share of devices in the largest device row along the
                 bus direction (rows by >= 30 % extent overlap)
  row_elongation length / thickness of that row (a row of 2-3 big devices
                 side by side is not 'strung out')
All four features must meet their thresholds for this check to trigger.
The scorer applies the separate effective-area and aspect limits.
"""

from __future__ import annotations

import statistics

from .constants import P
from .coupling import net_rects, rect_mst, route_length
from .layers import METALS


def supply_nets(tm, annotation=None) -> set:
    rails = set()
    for pol in ("n", "p"):
        devs = [d for d in tm.devices if d.ref and d.cls == "MOS" and d.polarity == pol]
        if not devs:
            continue
        cnt = {}
        for d in devs:
            b = d.terms.get("B")
            if b:
                cnt[b] = cnt.get(b, 0) + 1
        for net, c in cnt.items():
            if c >= 0.5 * len(devs):
                rails.add(net)
    for role in ("power", "ground"):
        for n in ((annotation or {}).get("nets") or {}).get(role) or []:
            k, _ = tm.resolve_net(n)
            if k:
                rails.add(k)
    return rails


def _bus_analysis(tm, nets, w, h):
    """Long straight signal segments per direction and the perpendicular
    drops of the same nets.  'H' = horizontal lines stacked in y.  A line is
    long if it spans >= half the layout AND >= 3x the median device size in
    that direction (compact layouts have no 'long' lines)."""
    dbu = tm.dbu
    dw = sorted(d.bbox[2] - d.bbox[0] for d in tm.devices if d.ref and d.fingers) or [0.0]
    dh = sorted(d.bbox[3] - d.bbox[1] for d in tm.devices if d.ref and d.fingers) or [0.0]
    min_h = max(0.5 * w, P["meaningless"]["line_dev_x"] * dw[len(dw) // 2])
    min_v = max(0.5 * h, P["meaningless"]["line_dev_x"] * dh[len(dh) // 2])
    segs = {"H": [], "V": []}   # (net, layer, perp_coord, length, box)
    perp = {"H": [], "V": []}   # all perpendicular-ish segments: (net, length)
    plain = {"H": 0.0, "V": 0.0}  # length of lines >= half the layout (no device-size floor)
    for k in nets:
        for m in METALS[1:]:
            for poly in tm.net_region(k, m).each_merged():
                for tz in poly.decompose_trapezoids():
                    b = tz.bbox()
                    bw, bh = b.width() * dbu, b.height() * dbu
                    if bw >= bh:
                        if bw >= 0.5 * w and bw >= 10 * bh:
                            plain["H"] += bw
                        if bw >= min_h and bw >= 10 * bh:
                            segs["H"].append((k, m, b.center().y * dbu, bw))
                        perp["V"].append((k, bw))
                    else:
                        if bh >= 0.5 * h and bh >= 10 * bw:
                            plain["V"] += bh
                        if bh >= min_v and bh >= 10 * bw:
                            segs["V"].append((k, m, b.center().x * dbu, bh))
                        perp["H"].append((k, bh))
    out = {}
    for o in ("H", "V"):
        coords = sorted(c for _, _, c, _ in segs[o])
        stacked = 0
        last = None
        for c in coords:
            if last is None or c - last > 1.0:
                stacked += 1
            last = c
        bus_nets = {n for n, _, _, _ in segs[o]}
        dim_perp = h if o == "H" else w
        drop_min = max(5.0, 0.15 * dim_perp)
        drops = sum(1 for n, L in perp[o] if n in bus_nets and L >= drop_min)
        out[o] = {"long_lines": len(segs[o]), "stacked_lines": stacked, "bus_nets": len(bus_nets),
                  "drops": drops, "long_len_um": round(sum(L for *_, L in segs[o]), 1),
                  "long_len_plain_um": round(plain[o], 1)}
    return out


def _device_rows(tm, o):
    """Rows of devices along direction o ('H': rows stacked in y); the
    largest row counts as a device line only if it is elongated along o."""
    boxes = []
    for d in tm.devices:
        if d.ref and d.fingers:
            boxes.append(d.bbox)
    if not boxes:
        return {"rows": 0, "largest_row_fraction": None, "dispersion": None}
    k = 1 if o == "H" else 0
    rows = []
    for b in sorted(boxes, key=lambda b: (b[k] + b[k + 2]) / 2):
        lo, hi = b[k], b[k + 2]
        for r in rows:
            ol = min(hi, r["hi"]) - max(lo, r["lo"])
            if ol >= 0.3 * min(hi - lo, r["hi"] - r["lo"]):
                r["n"] += 1
                r["lo"], r["hi"] = min(lo, r["lo"]), max(hi, r["hi"])
                break
        else:
            rows.append({"lo": lo, "hi": hi, "n": 1})
    centres = [(b[k] + b[k + 2]) / 2 for b in boxes]
    ext = sorted(b[k + 2] - b[k] for b in boxes)
    med = ext[len(ext) // 2] or 1.0
    big = max(rows, key=lambda r: r["n"])
    members = [b for b in boxes if min(b[k + 2], big["hi"]) - max(b[k], big["lo"]) >= 0.3 * (b[k + 2] - b[k])]
    j = 1 - k  # coordinate along the row
    length = max(b[j + 2] for b in members) - min(b[j] for b in members)
    thick = big["hi"] - big["lo"] or 1.0
    return {"rows": len(rows), "largest_row_fraction": big["n"] / len(boxes),
            "row_elongation": round(length / thick, 2),
            "dispersion": round(statistics.pstdev(centres) / med, 3)}


def features(tm, fill_ratio, annotation=None, matching=None) -> dict:
    x1, y1, x2, y2 = tm.bbox or tm.gds_top_bbox
    w, h = x2 - x1, y2 - y1
    aspect = max(w, h) / max(min(w, h), 1e-6)
    # annotation-free on purpose: only body-tie rails are excluded.  Nets an
    # annotation lists as 'power' for current reasons (an LDO / charge-pump
    # output) are drawn like signals and stay in the bus-line count; using
    # the annotation here made the verdict depend on how a task was annotated.
    rails = supply_nets(tm, None)
    nets = [k for k, v in tm.nets.items() if v.ref and k not in rails]
    tot_L = tot_M = 0.0
    ratios = []
    for k in nets:
        rects = net_rects(tm, k)
        if len(rects) < 2:
            continue
        L, _ = route_length(tm, k)
        mst, _ = rect_mst(rects)
        mst = max(mst, P["mst_floor_um"])
        if L <= 0:
            continue
        tot_L += L
        tot_M += mst
        ratios.append(L / mst)
    bus = _bus_analysis(tm, nets, w, h)
    o = max(("H", "V"), key=lambda d: (bus[d]["bus_nets"], bus[d]["long_len_um"]))
    rows = _device_rows(tm, o)
    long_len = bus["H"]["long_len_plain_um"] + bus["V"]["long_len_plain_um"]
    disp = (matching or {}).get("dispersed_weight_fraction") if matching else None
    return {"fill_ratio": fill_ratio, "aspect": aspect, "dispersed": disp,
            "detour_total": tot_L / tot_M if tot_M > 0 else None,
            "detour_median": statistics.median(ratios) if ratios else None,
            "long_wire_frac": long_len / tot_L if tot_L > 0 else None,
            "long_wire_count": bus["H"]["long_lines"] + bus["V"]["long_lines"],
            "bus_direction": o, "stacked_lines": bus[o]["stacked_lines"], "bus_nets": bus[o]["bus_nets"],
            "drops": bus[o]["drops"], "bus": bus,
            "device_rows": rows["rows"], "largest_row_fraction": rows["largest_row_fraction"],
            "row_elongation": rows.get("row_elongation"),
            "row_dispersion": rows["dispersion"],
            "signal_nets": len(ratios), "supply_nets": sorted(rails),
            "signal_route_um": round(tot_L, 1), "signal_mst_um": round(tot_M, 1)}


def judge(f: dict) -> dict:
    """Only the reviewed compound bus/drop/single-row morphology rule.

    Raw effective-area and aspect thresholds belong to the parameterized
    scorer. No old footprint/target threshold is carried into this collector.
    """
    c = P["meaningless"]
    sl, dr = f.get("bus_nets") or 0, f.get("drops") or 0
    row = f.get("largest_row_fraction")
    one_row = (row is not None and row >= c["row_fraction"]
               and (f.get("row_elongation") or 0) >= c["row_elongation"])
    hit = sl >= c["bus_lines"] and dr >= c["drops"] and one_row
    return {"meaningless": bool(hit), "rule": "parallel signal nets + drops + elongated device row" if hit else None,
            "hits": ([f"{sl} long parallel signal nets, {dr} drops, row share {row:.3f}, "
                      f"row elongation {f.get('row_elongation'):.3f}"] if hit else []),
            "thresholds": {k: c[k] for k in ("bus_lines", "drops", "row_fraction", "row_elongation")}}
