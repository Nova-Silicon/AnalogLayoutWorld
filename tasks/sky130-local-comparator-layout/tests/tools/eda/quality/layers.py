"""Infer anonymous lvsdb layer names (l11, l13, ...) for the SKY130 metal stack.

KLayout LVS databases store derived layers under anonymous names.  Only layers
that were read straight from GDS carry a ``'layer/datatype'`` annotation, e.g.
``L(l12 '67/44')`` for mcon.  The ``C(a b c ...)`` statements list which layers
are electrically connected to ``a``.  Starting from the annotated contact/via
layers we walk the stack upwards:

* mcon (67/44) touches exactly two conductors: li1 and met1.  li1 is the one
  that also touches licon (66/44); fallbacks use the li1/met1 label layers
  (67/5, 68/5) or via (68/44).
* via_k (68/44, 69/44, 70/44, 71/44) touches met_k, met_{k+1} and possibly a
  MIM top plate (capm 89/44 / cap2m 97/44); met_{k+1} is the remaining one.
* If via_k has no GDS annotation (seen for via4), a label layer (69/5..72/5)
  or a structural heuristic (self-connected layer touching met_k with exactly
  one further self-connected conductor) is used; otherwise the layer is
  reported as unresolved instead of guessed.
"""

from __future__ import annotations

import re
from pathlib import Path

_L = re.compile(r"^\s*L\((l\d+)(?:\s+'(\d+/\d+)')?\)")
_C = re.compile(r"^\s*C\(([^)]*)\)")

GDS = {
    "licon": "66/44", "mcon": "67/44", "via": "68/44", "via2": "69/44",
    "via3": "70/44", "via4": "71/44", "capm": "89/44", "cap2m": "97/44",
    "nwell": "64/20", "tap": "65/44",
}
LABEL = {"li1": "67/5", "met1": "68/5", "met2": "69/5", "met3": "70/5",
         "met4": "71/5", "met5": "72/5"}
METALS = ["li1", "met1", "met2", "met3", "met4", "met5"]
VIAS = ["mcon", "via", "via2", "via3", "via4"]  # VIAS[k] joins METALS[k], METALS[k+1]


def read_header(path: str | Path) -> tuple[dict[str, str | None], dict[str, set[str]]]:
    """Return ({lname: 'g/d' or None}, {lname: connected layers}) from an lvsdb."""
    layers: dict[str, str | None] = {}
    conn: dict[str, set[str]] = {}
    with open(path, encoding="utf-8", errors="replace") as fh:
        for line in fh:
            m = _L.match(line)
            if m:
                layers[m.group(1)] = m.group(2)
                continue
            m = _C.match(line)
            if m:
                items = m.group(1).split()
                conn.setdefault(items[0], set()).update(items[1:])
                continue
            s = line.lstrip()
            if s.startswith(("K(", "D(", "X(", "H(")) and conn:
                break
    return layers, conn


def infer_metal_layers(path: str | Path) -> dict:
    """Map li1/met1..met5 and contact/via layers to lvsdb layer names.

    Returns {"layers": {name: lname}, "method": {name: how}, "unresolved": [...]}.
    """
    gds, conn = read_header(path)
    by_gds = {v: k for k, v in gds.items() if v}
    nbr = {k: set(v) - {k} for k, v in conn.items()}
    selfc = {k for k, v in conn.items() if k in v}
    out: dict[str, str] = {}
    how: dict[str, str] = {}
    caps = {by_gds.get(GDS["capm"]), by_gds.get(GDS["cap2m"])} - {None}

    def cap_like(x: str, via: str) -> bool:
        return x in caps or nbr.get(x, set()) <= {via}

    def label_conductor(metal: str) -> str | None:
        lab = by_gds.get(LABEL[metal])
        if not lab:
            return None
        cands = [x for x in nbr.get(lab, ()) if x in selfc and x not in out.values()]
        # the conductor touches a via; label/pin helper layers do not touch vias
        vias = {by_gds.get(GDS[v]) for v in VIAS + ["licon"]} - {None}
        good = [x for x in cands if nbr.get(x, set()) & vias]
        return good[0] if len(good) == 1 else None

    mcon = by_gds.get(GDS["mcon"])
    if mcon:
        pair = sorted(nbr.get(mcon, set()) - caps)
        out["mcon"] = mcon
        how["mcon"] = "gds 67/44"
        licon = by_gds.get(GDS["licon"])
        li = [x for x in pair if licon and x in nbr.get(licon, set())]
        if len(pair) == 2 and len(li) == 1:
            out["li1"], how["li1"] = li[0], "mcon neighbour also touching licon"
            out["met1"] = next(x for x in pair if x != li[0])
            how["met1"] = "other mcon neighbour"
        elif len(pair) == 2:
            lab = label_conductor("li1")
            if lab in pair:
                out["li1"], how["li1"] = lab, "mcon neighbour with li1 label 67/5"
                out["met1"] = next(x for x in pair if x != lab)
                how["met1"] = "other mcon neighbour"
    for k in range(1, 5):
        lo, hi, vname = METALS[k], METALS[k + 1], VIAS[k]
        if lo not in out:
            break
        via = by_gds.get(GDS[vname])
        if via:
            out[vname], how[vname] = via, f"gds {GDS[vname]}"
            rest = [x for x in nbr.get(via, set()) - {out[lo]} if not cap_like(x, via)]
            rest = [x for x in rest if x not in out.values()]
            if len(rest) == 1:
                out[hi], how[hi] = rest[0], f"{vname} neighbour above {lo}"
                continue
        lab = label_conductor(hi)
        if lab:
            out[hi], how[hi] = lab, f"label layer {LABEL[hi]}"
            vs = [x for x in nbr.get(out[lo], set()) & nbr.get(lab, set()) if x in selfc]
            if len(vs) == 1 and vname not in out:
                out[vname], how[vname] = vs[0], "shared neighbour of metals"
            continue
        # structural heuristic for an unannotated via
        cands = []
        known_vias = {out.get(v) for v in VIAS} - {None}
        for x in nbr.get(out[lo], set()):
            if x in known_vias or x not in selfc:
                continue
            ups = [y for y in nbr.get(x, set()) - {out[lo]} if not cap_like(y, x)]
            if len(ups) == 1 and ups[0] in selfc and ups[0] not in out.values() \
                    and len(nbr.get(ups[0], set())) >= 2:
                cands.append((x, ups[0]))
        if len(cands) == 1:
            out[vname], out[hi] = cands[0]
            how[vname] = how[hi] = "structural heuristic (unannotated via)"
    unresolved = [m for m in METALS + VIAS if m not in out]
    return {"layers": out, "method": how, "unresolved": unresolved}


METAL_GDS = {"li1": (67, 20), "met1": (68, 20), "met2": (69, 20), "met3": (70, 20),
             "met4": (71, 20), "met5": (72, 20)}
LABEL_TO_METAL = {67: "li1", 68: "met1", 69: "met2", 70: "met3", 71: "met4", 72: "met5"}
