"""Small geometry helpers shared by the metric modules."""

from __future__ import annotations

import math

import klayout.db as kdb
from shapely.geometry import Polygon, MultiPolygon, box as sbox
from shapely.ops import unary_union


def region_to_shapely(region: kdb.Region, dbu: float):
    polys = []
    for p in region.each_merged():
        hull = [(pt.x * dbu, pt.y * dbu) for pt in p.each_point_hull()]
        holes = [[(pt.x * dbu, pt.y * dbu) for pt in p.each_point_hole(h)] for h in range(p.holes())]
        if len(hull) >= 3:
            polys.append(Polygon(hull, holes))
    if not polys:
        return MultiPolygon()
    return unary_union(polys)


def to_box(b, dbu: float) -> kdb.Box:
    x1, y1, x2, y2 = b
    return kdb.Box(round(x1 / dbu), round(y1 / dbu), round(x2 / dbu), round(y2 / dbu))


def boxes_region(boxes, dbu: float) -> kdb.Region:
    r = kdb.Region()
    for b in boxes:
        r.insert(to_box(b, dbu))
    return r


def centerline_length(region: kdb.Region, dbu: float) -> float:
    """Approximate total centre-line length of merged polygons (um).

    Each polygon is treated as a strip: with area A and perimeter P, a strip of
    length l and width w satisfies l + w = P/2, l * w = A.  Branched polygons
    give roughly the sum of their arm lengths; compact blobs give sqrt(A).
    """
    tot = 0.0
    for p in region.each_merged():
        a = p.area() * dbu * dbu
        per = p.perimeter() * dbu
        half = per / 2.0
        disc = half * half - 4.0 * a
        tot += (half + math.sqrt(disc)) / 2.0 if disc > 0 else math.sqrt(a)
    return tot


def rect_mst_length(points) -> float:
    """Rectilinear (Manhattan) minimum spanning tree length over points (Prim)."""
    pts = list({(round(x, 3), round(y, 3)) for x, y in points})
    n = len(pts)
    if n < 2:
        return 0.0
    inf = float("inf")
    best = [inf] * n
    used = [False] * n
    best[0] = 0.0
    tot = 0.0
    for _ in range(n):
        i = min((k for k in range(n) if not used[k]), key=lambda k: best[k])
        used[i] = True
        tot += best[i]
        xi, yi = pts[i]
        for k in range(n):
            if not used[k]:
                d = abs(pts[k][0] - xi) + abs(pts[k][1] - yi)
                if d < best[k]:
                    best[k] = d
    return tot


def soft(d: float, d0: float) -> float:
    """1 at d=0, 0.5 at d=d0, decaying as 1/(1+(d/d0)^2)."""
    if d0 <= 0:
        return 1.0 if d <= 0 else 0.0
    return 1.0 / (1.0 + (d / d0) ** 2)


def ramp(d: float, full: float, zero: float) -> float:
    """1 for d <= full, linear down to 0 at d >= zero."""
    if d is None:
        return None
    if d <= full:
        return 1.0
    if d >= zero:
        return 0.0
    return (zero - d) / (zero - full)


def wmean(pairs):
    """Weighted mean of (value, weight) skipping None values; None if empty."""
    num = den = 0.0
    for v, w in pairs:
        if v is None or w <= 0:
            continue
        num += v * w
        den += w
    return num / den if den > 0 else None


__all__ = ["region_to_shapely", "to_box", "boxes_region", "centerline_length",
           "rect_mst_length", "soft", "ramp", "wmean", "sbox"]
