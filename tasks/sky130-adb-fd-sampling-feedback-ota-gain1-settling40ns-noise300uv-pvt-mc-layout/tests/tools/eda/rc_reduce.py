"""Resistance-preserving reduction of Magic ext2spice parasitic RC networks.

Magic's full-resolution RC extraction (``extresist`` threshold 0) writes tens
of thousands of milliohm-scale wire resistors.  ngspice has no built-in RC
reduction, so the post-layout netlist is reduced here before simulation.

Method (TICER, Sheehan, ICCAD 1999): an internal parasitic node is eliminated
by star-mesh transformation when it is a "quick" node, i.e. its time constant
``sum(C at node) / sum(G at node)`` does not exceed ``tau_s``:

* resistors are merged, never dropped: neighbours ``i, j`` of the eliminated
  node receive ``g_i * g_j / G`` (degree 2 is the series sum, degree 1 is an
  open-ended stub that carries no DC current); parallel resistors and
  capacitors are combined.  The conductance matrix restricted to the remaining
  nodes is the exact Schur complement, so DC node voltages are unchanged.
* each capacitor ``c`` from the node to ``x`` is moved to ``(m, x)`` for every
  resistive neighbour ``m`` with weight ``g_m / G``.  The neighbours belong to
  the same resistively connected net, so the total capacitance between any
  two nets, and from every net to ground/substrate, is conserved exactly.
  Only the within-net distribution changes (first-order accurate for
  frequencies well below ``1 / (2 pi tau_s)``).

Only plain numeric two-terminal ``R``/``C`` statements inside a ``.subckt``
are candidates.  Every other statement (X devices, R/C with a model or
parameters, sources, directives) is copied verbatim and all of its tokens are
protected nodes, as are the subcircuit ports, ``0``/``gnd`` and ``.global``
nodes.  Protected nodes are never eliminated.  Unchanged parasitic statements
are kept verbatim at their original position; merged elements are appended
before ``.ends``.  Node identity follows ngspice (case-insensitive) while the
original spelling is written.  The module is pure Python (stdlib only).

``max_degree`` bounds the number of distinct resistive neighbours of an
eliminated node.  Up to degree 3 a star-mesh step cannot add resistors
(d removed, d(d-1)/2 <= d added).  Above degree 3 a node is eliminated only if
the step does not increase the total number of parasitic R and C elements
(new neighbour pairs usually coincide with existing mesh edges and merge in
parallel), so a larger ``max_degree`` is an optional, more aggressive setting
with the same DC-exactness, capacitance conservation and ``tau_s`` bound.
"""
from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import math
from pathlib import Path
import re
import time

ALGORITHM = "ticer-star-mesh-v1"
DEFAULT_TAU_S = 1e-12
DEFAULT_MAX_DEGREE = 3
GUARD_FREE_DEGREE = 3
GROUND_NODES = frozenset({"0", "gnd"})
CONSERVATION_RTOL = 1e-9

# Same numeric grammar as eda.pex.number (the verifier's netlist inspector).
_NUMBER = re.compile(r"([-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)(meg|[afpnumkgt]?)", re.I)
_SCALE = {"": 1.0, "a": 1e-18, "f": 1e-15, "p": 1e-12, "n": 1e-9, "u": 1e-6,
          "m": 1e-3, "k": 1e3, "meg": 1e6, "g": 1e9, "t": 1e12}
# Token separators for protection: a superset of SPICE node positions, so
# expressions such as V={v(a,b)} also protect a and b.
_TOKENS = re.compile(r"[\s=(),{}'\"]+")
_NOT_A_NODE = re.compile(r"[=(),{}'\"]")


def parse_value(token: str) -> float | None:
    match = _NUMBER.fullmatch(token)
    if not match:
        return None
    value = float(match[1]) * _SCALE[match[2].lower()]
    return value if math.isfinite(value) else None


def numeric_parasitic(words: list[str]):
    """Return (kind, a, b, value) for a reducible R/C statement, else None.

    Exactly ``Rname a b value`` or ``Cname a b value`` with a plain number;
    anything else (model names, parameters, expressions, zero/negative R,
    negative C, self-loops) is a protected, verbatim statement.
    """
    if len(words) != 4:
        return None
    kind = words[0][0].lower()
    if kind not in "rc":
        return None
    a, b = words[1], words[2]
    if _NOT_A_NODE.search(a) or _NOT_A_NODE.search(b) or a.casefold() == b.casefold():
        return None
    value = parse_value(words[3])
    if value is None or (kind == "r" and value <= 0) or (kind == "c" and value < 0):
        return None
    return kind, a, b, value


def _edge(a: int, b: int) -> int:
    return (a << 32) | b if a < b else (b << 32) | a


class _Block:
    """One .subckt scope: its ports, protected tokens and parasitic graph."""

    def __init__(self, name: str, ports: list[str]):
        self.name = name
        self.ports = ports
        self.port_spelling = {port.casefold(): port for port in ports}
        self.ends_line: int | None = None
        self.protected: set[str] = set()
        self.names: set[str] = set()
        self.other_statements = 0
        self.ids: dict[str, int] = {}
        self.spelling: list[str] = []
        self.radj: list[dict[int, float]] = []
        self.cadj: list[dict[int, float]] = []
        # Edge -> first physical line of the single original statement it equals.
        self.original_r: dict[int, int] = {}
        self.original_c: dict[int, int] = {}
        self.statement_lines: list[int] = []
        self.continuations: dict[int, list[int]] = {}
        self.r_before = self.c_before = self.zero_capacitors = self.parallel_merges = 0

    def node(self, name: str) -> int:
        key = name.casefold()
        found = self.ids.get(key)
        if found is None:
            found = self.ids[key] = len(self.spelling)
            self.spelling.append(self.port_spelling.get(key, name))
            self.radj.append({})
            self.cadj.append({})
        return found

    def add(self, kind: str, a: str, b: str, value: float, indices: list[int]) -> None:
        first = indices[0]
        self.statement_lines.append(first)
        if len(indices) > 1:
            self.continuations[first] = indices[1:]
        if kind == "r":
            self.r_before += 1
            adjacency, original, weight = self.radj, self.original_r, 1.0 / value
        else:
            self.c_before += 1
            if value == 0.0:
                self.zero_capacitors += 1  # electrically absent; dropping it is exact
                return
            adjacency, original, weight = self.cadj, self.original_c, value
        ia, ib = self.node(a), self.node(b)
        key = _edge(ia, ib)
        previous = adjacency[ia].get(ib)
        if previous is None:
            original[key] = first
            total = weight
        else:
            self.parallel_merges += 1
            original.pop(key, None)
            total = previous + weight
        adjacency[ia][ib] = adjacency[ib][ia] = total


def _logical_lines(lines: list[str]):
    """Same continuation/comment convention as eda.pex.logical_lines."""
    current = None
    for index, raw in enumerate(lines):
        line = raw.split(";", 1)[0].strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            if current is None:
                raise ValueError("Orphan SPICE continuation")
            current[0].append(index)
            current[1] += " " + line[1:]
        else:
            if current is not None:
                yield current
            current = [[index], line]
    if current is not None:
        yield current


def _parse(lines: list[str]):
    blocks: list[_Block] = []
    stack: list[_Block] = []
    global_nodes: set[str] = set()
    top_level_statements = 0
    for indices, text in _logical_lines(lines):
        words = text.split()
        head = words[0].lower()
        if head == ".subckt":
            if len(words) < 2:
                raise ValueError("Invalid .subckt declaration")
            ports = []
            for word in words[2:]:
                if "=" in word or word.lower() == "params:":
                    break
                ports.append(word)
            block = _Block(words[1], ports)
            blocks.append(block)
            stack.append(block)
            continue
        if head == ".ends":
            if not stack:
                raise ValueError("Unmatched .ends")
            stack.pop().ends_line = indices[0]
            continue
        if head == ".global":
            global_nodes.update(word.casefold() for word in words[1:])
        if not stack:
            top_level_statements += 1  # visible to the including deck: untouched
            continue
        block = stack[-1]
        parasitic = numeric_parasitic(words)
        if parasitic is not None:
            block.add(*parasitic, indices)
            continue
        block.other_statements += 1
        if not head.startswith("."):
            block.names.add(words[0].casefold())
        block.protected.update(token.casefold() for token in _TOKENS.split(text)[1:] if token)
    if stack:
        raise ValueError("Unterminated .subckt")
    return blocks, global_nodes, top_level_statements


def _components(count: int, radj: list[dict[int, float]]) -> list[int]:
    parent = list(range(count))

    def find(node):
        root = node
        while parent[root] != root:
            root = parent[root]
        while parent[node] != root:
            parent[node], node = root, parent[node]
        return root

    for a in range(count):
        for b in radj[a]:
            if b > a:
                ra, rb = find(a), find(b)
                if ra != rb:
                    parent[max(ra, rb)] = min(ra, rb)
    return [find(node) for node in range(count)]


def _net_capacitance(cadj: list[dict[int, float]], net: list[int]) -> dict[tuple[int, int], float]:
    totals: dict[tuple[int, int], float] = {}
    for a, neighbours in enumerate(cadj):
        for b, value in neighbours.items():
            if b <= a or net[a] == net[b]:
                continue
            key = (net[a], net[b]) if net[a] < net[b] else (net[b], net[a])
            totals[key] = totals.get(key, 0.0) + value
    return totals


def _fresh_names(prefix: str, taken: set[str]):
    index = 0
    while True:
        name = f"{prefix}{index}"
        index += 1
        if name.casefold() not in taken:
            yield name


def _reduce_block(block: _Block, lines: list[str], global_nodes: set[str],
                  tau_s: float, max_degree: int):
    protected_keys = (block.protected | set(block.port_spelling) | global_nodes | GROUND_NODES)
    radj, cadj, spelling = block.radj, block.cadj, block.spelling
    original_r, original_c = block.original_r, block.original_c
    count = len(spelling)
    protected = [key in protected_keys for key in block.ids]  # ids are in node-id order
    net = _components(count, radj)
    capacitance_before = _net_capacitance(cadj, net)

    eliminated = [False] * count
    by_degree: dict[int, int] = {}
    guarded_skips = 0
    heap = [(len(radj[n]), n) for n in range(count) if radj[n] and not protected[n]]
    heapq.heapify(heap)
    while heap:
        degree, n = heapq.heappop(heap)
        if eliminated[n]:
            continue
        resistive = radj[n]
        actual = len(resistive)
        if actual != degree:
            if actual:
                heapq.heappush(heap, (actual, n))
            continue
        if degree > max_degree:
            continue
        g_total = sum(resistive.values())
        capacitive = cadj[n]
        if capacitive and sum(capacitive.values()) > tau_s * g_total:
            continue
        neighbours = list(resistive.items())
        if degree > GUARD_FREE_DEGREE:
            added = sum(1 for i in range(degree) for j in range(i + 1, degree)
                        if neighbours[j][0] not in radj[neighbours[i][0]])
            new_caps = {_edge(m, x) for m, _ in neighbours for x in capacitive
                        if m != x and x not in cadj[m]}
            if added + len(new_caps) > degree + len(capacitive):
                guarded_skips += 1
                continue
        for m, _ in neighbours:
            del radj[m][n]
            original_r.pop(_edge(m, n), None)
        for x in capacitive:
            del cadj[x][n]
            original_c.pop(_edge(x, n), None)
        for i in range(degree):
            mi, gi = neighbours[i]
            row = radj[mi]
            for j in range(i + 1, degree):
                mj, gj = neighbours[j]
                total = row.get(mj, 0.0) + gi * gj / g_total
                row[mj] = radj[mj][mi] = total
                original_r.pop(_edge(mi, mj), None)
        for x, value in capacitive.items():
            for m, g in neighbours:
                if m == x:
                    continue  # within-net share of a capacitor to a resistive neighbour
                row = cadj[m]
                total = row.get(x, 0.0) + value * g / g_total
                row[x] = cadj[x][m] = total
                original_c.pop(_edge(m, x), None)
        radj[n] = {}
        cadj[n] = {}
        eliminated[n] = True
        by_degree[degree] = by_degree.get(degree, 0) + 1
        for m, _ in neighbours:
            if not protected[m]:
                heapq.heappush(heap, (len(radj[m]), m))

    if any(eliminated[n] and protected[n] for n in range(count)):
        raise AssertionError("A protected node was eliminated")
    capacitance_after = _net_capacitance(cadj, net)
    worst = 0.0
    for key in capacitance_before.keys() | capacitance_after.keys():
        before, after = capacitance_before.get(key, 0.0), capacitance_after.get(key, 0.0)
        scale = max(abs(before), abs(after))
        if scale:
            difference = abs(before - after) / scale
            if difference > CONSERVATION_RTOL:
                raise ValueError(f"Net-to-net capacitance not conserved in {block.name}")
            worst = max(worst, difference)

    kept = set(original_r.values()) | set(original_c.values())
    removed = set(block.statement_lines) - kept
    for first, more in block.continuations.items():
        if first not in kept:
            removed.update(more)
    taken = set(block.names) | {lines[index].split(None, 1)[0].casefold() for index in kept}
    r_names, c_names = _fresh_names("Rrc", taken), _fresh_names("Crc", taken)
    appended = []
    r_after = c_after = 0
    for a in range(count):
        for b, g in radj[a].items():
            if b > a:
                r_after += 1
                if _edge(a, b) not in original_r:
                    appended.append(f"{next(r_names)} {spelling[a]} {spelling[b]} {1.0 / g!r}")
    for a in range(count):
        for b, value in cadj[a].items():
            if b > a:
                c_after += 1
                if _edge(a, b) not in original_c:
                    appended.append(f"{next(c_names)} {spelling[a]} {spelling[b]} {value!r}")
    stats = {
        "subckt": block.name, "ports": len(block.ports),
        "resistors_before": block.r_before, "resistors_after": r_after,
        "capacitors_before": block.c_before, "capacitors_after": c_after,
        "parasitic_nodes_before": count,
        "parasitic_nodes_after": sum(1 for n in range(count) if radj[n] or cadj[n]),
        "eliminated_nodes": sum(eliminated),
        "eliminated_by_degree": {str(k): by_degree[k] for k in sorted(by_degree)},
        "protected_parasitic_nodes": sum(protected),
        "unchanged_statements_kept": len(kept),
        "merged_statements_written": len(appended),
        "parallel_merges": block.parallel_merges,
        "zero_value_capacitors_dropped": block.zero_capacitors,
        "growth_guard_skips": guarded_skips,
        "non_parasitic_statements_untouched": block.other_statements,
        "net_capacitance_check": {"net_pairs": len(capacitance_before),
                                  "max_relative_difference": worst},
    }
    eliminated_names = [spelling[n] for n in range(count) if eliminated[n]]
    return removed, appended, stats, eliminated_names


def _check_parameters(tau_s: float, max_degree: int) -> None:
    if (not isinstance(tau_s, (int, float)) or isinstance(tau_s, bool)
            or not math.isfinite(tau_s) or tau_s < 0):
        raise ValueError("tau_s must be a finite non-negative number of seconds")
    if not isinstance(max_degree, int) or isinstance(max_degree, bool) or max_degree < 0:
        raise ValueError("max_degree must be a non-negative integer")


_TOTALS = ("resistors_before", "resistors_after", "capacitors_before", "capacitors_after",
           "parasitic_nodes_before", "parasitic_nodes_after", "eliminated_nodes",
           "protected_parasitic_nodes", "zero_value_capacitors_dropped")


def _reduce_lines(lines: list[str], tau_s: float, max_degree: int):
    _check_parameters(tau_s, max_degree)
    blocks, global_nodes, top_level = _parse(lines)
    removed: set[int] = set()
    inserted: dict[int, list[str]] = {}
    block_stats, eliminated = [], {}
    for block in blocks:
        gone, appended, stats, names = _reduce_block(block, lines, global_nodes, tau_s, max_degree)
        removed |= gone
        if appended:
            inserted[block.ends_line] = [
                f"* rc_reduce {ALGORITHM}: {len(appended)} merged parasitic elements "
                f"(tau_s={tau_s!r}, max_degree={max_degree})", *appended]
        block_stats.append(stats)
        eliminated[block.name] = names
    totals = {key: sum(stats[key] for stats in block_stats) for key in _TOTALS}
    output = [
        f"* rc_reduce {ALGORITHM}: DC-exact TICER star-mesh reduction of numeric parasitic R/C",
        f"* parameters: tau_s={tau_s!r} max_degree={max_degree} "
        f"(degree>{GUARD_FREE_DEGREE} only without element growth)",
        f"* numeric R {totals['resistors_before']} -> {totals['resistors_after']}, "
        f"numeric C {totals['capacitors_before']} -> {totals['capacitors_after']}, "
        f"eliminated nodes {totals['eliminated_nodes']}",
        "* protected: subcircuit ports, 0/gnd/.global nodes and every token of non-numeric statements",
    ]
    for index, raw in enumerate(lines):
        if index in inserted:
            output.extend(inserted[index])
        if index not in removed:
            output.append(raw)
    stats = {"algorithm": ALGORITHM,
             "parameters": {"tau_s": tau_s, "max_degree": max_degree,
                            "growth_guard_above_degree": GUARD_FREE_DEGREE},
             **totals, "top_level_statements_untouched": top_level,
             "subcircuits": block_stats}
    return output, stats, eliminated


def reduce_text(text: str, *, tau_s: float = DEFAULT_TAU_S, max_degree: int = DEFAULT_MAX_DEGREE,
                return_eliminated: bool = False):
    """Return (reduced netlist text, statistics[, eliminated node names per subckt])."""
    output, stats, eliminated = _reduce_lines(text.splitlines(), tau_s, max_degree)
    reduced = "\n".join(output) + "\n"
    return (reduced, stats, eliminated) if return_eliminated else (reduced, stats)


def reduce_file(source: Path, destination: Path, *, tau_s: float = DEFAULT_TAU_S,
                max_degree: int = DEFAULT_MAX_DEGREE) -> dict:
    """Reduce one netlist file; the source is read-only and never modified."""
    started = time.monotonic()
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError("Reduction output must differ from its input")
    data = source.read_bytes()
    input_sha256 = hashlib.sha256(data).hexdigest()
    lines = data.decode("utf-8").splitlines()
    input_bytes = len(data)
    del data
    output, stats, _ = _reduce_lines(lines, tau_s, max_degree)
    del lines
    encoded = ("\n".join(output) + "\n").encode("utf-8")
    del output
    destination.write_bytes(encoded)
    stats.update(input_path=str(source), input_sha256=input_sha256, input_bytes=input_bytes,
                 output_path=str(destination), output_sha256=hashlib.sha256(encoded).hexdigest(),
                 output_bytes=len(encoded), seconds=round(time.monotonic() - started, 3))
    return stats


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("input", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tau-s", type=float, default=DEFAULT_TAU_S,
                        help="node time-constant limit C/G in seconds (default 1e-12)")
    parser.add_argument("--max-degree", type=int, default=DEFAULT_MAX_DEGREE,
                        help="largest number of resistive neighbours of an eliminated node (default 3); "
                             f"nodes above degree {GUARD_FREE_DEGREE} are eliminated only without element growth")
    args = parser.parse_args(argv)
    print(json.dumps(reduce_file(args.input, args.output, tau_s=args.tau_s, max_degree=args.max_degree),
                     indent=1, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
