"""Choose an ngspice 46 matrix solver for a trusted verifier deck.

KLU and Sparse use the same device models and analysis tolerances. This policy
does not rewrite a deck, simplify RC, change convergence settings, or prefer a
solver because it produces a passing score. Unknown constructs retain Sparse.

References: ngspice-46 manual sections 1.1.2 and 11.1.1; release-46 sources
spicelib/analysis/{noisean,pzan,cktsens}.c and devices/{numd,nbjt,numos}.
"""
from __future__ import annotations

from collections import Counter, OrderedDict
import hashlib
from pathlib import Path
import re
import shlex
from threading import Lock


POLICY_VERSION = "ngspice46-analysis-v2"
SUPPORTED_ANALYSES = frozenset({"op", "dc", "ac", "tran", "tf"})
UNSUPPORTED_ANALYSES = frozenset({"noise", "pz"})
# ngspice 46 contains sensitivity/CIDER KLU support, but those paths have not
# been qualified for this verifier. Sparse here is a conservative policy, not
# a claim that every such analysis is unsupported by the native simulator.
CONSERVATIVE_ANALYSES = frozenset({"sens"})
OTHER_ANALYSES = frozenset({"disto", "pss", "sp", "hb"})
CIDER_MODELS = frozenset({"numd", "nbjt", "numos"})
COMPACT_MODELS = frozenset({"nmos", "pmos", "npn", "pnp", "d", "r", "c",
                            "sw", "csw", "l"})
CONTROL_COMMANDS = frozenset({
    "alter", "alterparam", "destroy", "echo", "end", "else", "foreach",
    "fourier", "if", "let", "listing", "meas", "measure", "option", "options",
    "print", "quit", "reset", "run", "save", "set", "setplot", "show", "showmod",
    "wrdata", "write", "unset", "while", "dowhile", "repeat", "break", "continue",
    "linearize", "fft", "spec", "rusage", "display", "version",
    # optran only selects a transient-based operating-point search before
    # op/ac/tran; it adds no analysis type of its own (verified on the LDO
    # benches: KLU and SPARSE results agree bit for bit).
    "optran",
})
DIRECTIVES = frozenset({
    ".param", ".csparam", ".func", ".global", ".temp", ".options", ".option",
    ".save", ".print", ".plot", ".meas", ".measure", ".ic", ".nodeset",
    ".subckt", ".ends", ".end", ".title", ".width",
})
_FACT_CACHE = OrderedDict()
_CACHE_LOCK = Lock()


def _logical_lines(text: str):
    pending = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("*"):
            continue
        if line.startswith("+"):
            pending += " " + line[1:].lstrip()
        else:
            if pending:
                yield pending
            pending = line
    if pending:
        yield pending


def _tokens(line: str) -> list[str]:
    # Semicolon is an ngspice inline comment. Do not strip $&vectors or $vars
    # used by the control language; shlex does not expand them.
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.commenters = ";"
    return list(lexer)


def _solver_option_spans(line: str) -> list[tuple[str, int, int]]:
    """Locate solver option items, never words inside strings or other values.

    Keep lexical spans instead of reserializing tokens: ngspice accepts both
    ``sparse=1`` and ``sparse = 1``, and unrelated options may contain quoted
    strings or a value such as ``plotname=klu``.
    """
    token = re.compile(r'''"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|;[^\r\n]*|[^\s=;"']+|=''')
    tokens = list(token.finditer(line))
    if not tokens or tokens[0][0].lower() not in {"option", "options", ".option", ".options"}:
        return []
    spans = []
    index = 1
    while index < len(tokens):
        name = tokens[index]
        if name[0].startswith(';'):
            break
        end = name.end()
        next_index = index + 1
        if next_index < len(tokens) and tokens[next_index][0] == '=':
            value_index = next_index + 1
            if value_index >= len(tokens) or tokens[value_index][0].startswith(';'):
                if name[0].lower() in {'klu', 'sparse'}:
                    raise ValueError('Matrix solver assignment is missing a value')
                break
            end = tokens[value_index].end()
            next_index = value_index + 1
        if name[0].lower() in {'klu', 'sparse'}:
            spans.append((name[0].lower(), name.start(), end))
        index = next_index
    return spans


def _solver_options(line: str) -> set[str]:
    return {name for name, _start, _end in _solver_option_spans(line)}


def _file_facts(path: str, section: str | None, root: bool) -> dict:
    """Cache bounded metadata, not the possibly large PEX/model text."""
    raw = Path(path).read_bytes()
    # Content identity matters: shared filesystems can report the same mtime
    # and size for two rapid edits. Never reuse facts from a different circuit.
    identity = (path, hashlib.sha256(raw).hexdigest(), section, root)
    with _CACHE_LOCK:
        if identity in _FACT_CACHE:
            _FACT_CACHE.move_to_end(identity)
            return _FACT_CACHE[identity]
    text = raw.decode(errors="replace")
    if root:
        # SPICE always treats the first physical line as a title.
        text = "\n".join(text.splitlines()[1:])
    analyses, models, features, explicit, unknown = set(), set(), set(), set(), set()
    includes, kinds = [], Counter()
    in_control = False
    active = section is None
    found_section = section is None
    for line in _logical_lines(text):
        tokens = _tokens(line)
        if not tokens:
            continue
        command = tokens[0].lower()
        if command == ".lib" and len(tokens) == 2:
            active = section is None or tokens[1].lower() == section.lower()
            found_section |= active
            continue
        if command in {".endl", ".endlb"}:
            active = section is None
            continue
        if not active:
            continue
        if command == ".control":
            in_control = True
            continue
        if command == ".endc":
            in_control = False
            continue
        if command in {".include", ".inc"} or (command == ".lib" and len(tokens) >= 3):
            if len(tokens) < 2:
                unknown.add("incomplete include")
                continue
            includes.append((tokens[1], tokens[2] if command == ".lib" else None))
            continue
        if command in {"option", "options", ".option", ".options"}:
            explicit.update(_solver_options(line))
        analysis = command if in_control else command.removeprefix(".") if command.startswith(".") else ""
        if analysis in SUPPORTED_ANALYSES | UNSUPPORTED_ANALYSES | CONSERVATIVE_ANALYSES | OTHER_ANALYSES:
            analyses.add(analysis)
            continue
        if in_control:
            if command not in CONTROL_COMMANDS:
                unknown.add("control:" + command)
            continue
        if command == ".model":
            if len(tokens) < 3:
                unknown.add("incomplete .model")
                continue
            model = tokens[2].split("(", 1)[0].lower()
            models.add(model)
            if model in CIDER_MODELS:
                features.add("cider")
            elif model not in COMPACT_MODELS:
                unknown.add("model:" + model)
            continue
        if command.startswith("."):
            if command not in DIRECTIVES:
                unknown.add("directive:" + command)
            continue
        kind = command[0]
        kinds[kind] += 1
        if kind == "a":
            features.add("xspice")
        elif kind == "b":
            # B sources have KLU bindings, but the manual recommends Sparse
            # for behavioral-model circuits. This is preference, not rejection.
            features.add("behavioral")
        elif kind not in "rclviegfhdqmxksw":
            unknown.add("device:" + kind)
        elif kind in "eg" and re.search(r"\b(?:value|table|poly|laplace)\b", line, re.I):
            features.add("behavioral")
    if not found_section:
        unknown.add("missing library section:" + str(section))
    result = {"sha256": identity[1], "analyses": sorted(analyses), "model_types": sorted(models),
              "features": sorted(features), "explicit_solvers": sorted(explicit),
              "unknown": sorted(unknown), "includes": tuple(includes),
              "device_kinds": dict(kinds)}
    with _CACHE_LOCK:
        _FACT_CACHE[identity] = result
        if len(_FACT_CACHE) > 256:
            _FACT_CACHE.popitem(last=False)
    return result


def select_solver(deck: Path, initialization: str = "", *, requested: str = "auto",
                  cwd: Path | None = None) -> dict:
    """Audit include/lib closure and select a solver without changing the deck.

    Native .options in the deck are authoritative; auto preserves an explicit
    compatible selection. An incompatible, unqualified or conflicting KLU
    request is reported as invalid rather than silently changing the solver.
    ``requested='sparse'`` supports an explicit baseline run of the same input.
    ``cwd`` is the native process working directory. For a relative include,
    ngspice first searches there, then beside the including file. Direct
    callers omitting ``cwd`` retain the default of the deck's own directory.
    """
    if requested not in {"auto", "sparse", "klu"}:
        raise ValueError("Solver policy must be auto, sparse or klu")
    deck = Path(deck).resolve(strict=True)
    cwd = deck.parent if cwd is None else Path(cwd).resolve(strict=True)
    if not cwd.is_dir():
        raise ValueError("ngspice working directory must be a directory")
    analyses, models, features, explicit, unknown, seen = set(), set(), set(), set(), set(), set()
    kinds = Counter()
    files = []
    pending = [(deck, None, True)]
    while pending:
        path, section, root = pending.pop()
        identity = (str(path), section)
        if identity in seen:
            continue
        seen.add(identity)
        try:
            facts = _file_facts(str(path), section, root)
        except (OSError, UnicodeError, ValueError) as exc:
            unknown.add(f"unreadable include:{path} ({type(exc).__name__})")
            continue
        files.append({"path": str(path), "section": section, "sha256": facts["sha256"]})
        analyses.update(facts["analyses"])
        models.update(facts["model_types"])
        features.update(facts["features"])
        explicit.update(facts["explicit_solvers"])
        unknown.update(facts["unknown"])
        kinds.update(facts["device_kinds"])
        for filename, include_section in facts["includes"]:
            if any(token in filename for token in ("$", "{", "__MODEL_LIB__", "__DUT_NETLIST__")):
                unknown.add("dynamic include:" + filename)
                continue
            child = Path(filename)
            if not child.is_absolute():
                # ngspice 46 inp_pathresolve_at tries process cwd before the
                # including file's directory, including for nested .lib use.
                current_candidate = cwd / child
                child = current_candidate if current_candidate.is_file() else path.parent / child
            pending.append((child.resolve(), include_section, False))

    for line in _logical_lines(initialization):
        tokens = _tokens(line)
        if tokens and tokens[0].lower() not in {"set", "unset", "option", "options", "echo"}:
            unknown.add("initialization:" + tokens[0].lower())
    blocked = sorted(analyses & UNSUPPORTED_ANALYSES)
    if blocked:
        reason = "analysis_requires_sparse:" + ",".join(blocked)
    elif analyses & CONSERVATIVE_ANALYSES:
        reason = "sensitivity_not_qualified_keep_sparse"
    elif analyses & OTHER_ANALYSES:
        reason = "unqualified_analysis_keep_sparse:" + ",".join(sorted(analyses & OTHER_ANALYSES))
    elif "cider" in features:
        reason = "cider_not_qualified_keep_sparse"
    elif unknown:
        reason = "unqualified_constructs_keep_sparse"
    elif "xspice" in features:
        reason = "xspice_not_qualified_keep_sparse"
    elif "behavioral" in features:
        reason = "official_behavioral_preference_sparse"
    elif not analyses:
        reason = "no_explicit_supported_analysis"
    else:
        reason = "supported_analog_analysis_prefer_klu"
    candidate = "klu" if reason == "supported_analog_analysis_prefer_klu" else "sparse"
    unqualified = bool(blocked or analyses & (OTHER_ANALYSES | CONSERVATIVE_ANALYSES)
                       or "cider" in features or unknown or "xspice" in features or not analyses)
    if len(explicit) > 1:
        raise ValueError("Conflicting native KLU/Sparse options in trusted deck/include closure")
    native = next(iter(explicit), None)
    if native == "klu" and unqualified:
        raise ValueError("Native KLU selection conflicts with ngspice 46 policy: " + reason)
    if requested == "klu" and unqualified:
        raise ValueError("KLU is not qualified for this deck: " + reason)
    if requested != "auto" and native is not None and native != requested:
        raise ValueError("Requested solver conflicts with native deck selection; deck is not rewritten")
    selected = native or (candidate if requested == "auto" else requested)
    decision = ("native_deck_selection" if native else
                "explicit_baseline" if requested == "sparse" else
                "explicit_compatible_klu" if requested == "klu" else reason)
    initial_choices = sorted({solver for line in _logical_lines(initialization)
                              for solver in _solver_options(line)})
    return {"policy_version": POLICY_VERSION, "solver": selected, "reason": decision,
            "automatic_reason": reason, "requested": requested,
            "working_directory": str(cwd),
            "analyses": sorted(analyses), "model_types": sorted(models),
            "features": sorted(features), "unknown": sorted(unknown),
            "device_kinds": dict(sorted(kinds.items())), "files": files,
            "native_deck_solver": native, "initialization_solvers_before": initial_choices}


def configure_solver(initialization: str, solver: str) -> str:
    """Set only the native matrix-solver option; preserve all other settings."""
    if solver not in {"klu", "sparse"}:
        raise ValueError("Matrix solver must be klu or sparse")
    lines = []
    for line in initialization.splitlines(keepends=True):
        spans = _solver_option_spans(line)
        if spans:
            for _name, start, end in reversed(spans):
                line = line[:start] + line[end:]
            if re.fullmatch(r"\s*\.?options?\s*(?:;[^\r\n]*)?[\r\n]*", line, re.I):
                if ';' in line:
                    # Preserve the complete comment; prevent a now-argumentless
                    # option command from printing unrelated option tables.
                    lines.append(re.sub(r'(?i)\.?options?', '*', line, count=1))
                continue
        lines.append(line)
    result = ''.join(lines)
    if result and not result.endswith(('\n', '\r')):
        result += '\n'
    return result + "option " + solver + "\n"
