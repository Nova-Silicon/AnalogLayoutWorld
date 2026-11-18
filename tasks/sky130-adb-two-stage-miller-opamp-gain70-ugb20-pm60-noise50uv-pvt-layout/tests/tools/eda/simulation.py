"""Run an ngspice deck and retain its output, without task-specific scoring.

Decks can contain ngspice control commands. This utility is an execution tool,
not a security sandbox; the final verifier must supply its own trusted deck.
"""
from __future__ import annotations

import argparse
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
from threading import Event

try:
    from .runtime import load_runtime, run_command, shared_output
    from .simulation_resources import positive_integer, thread_initialization
    from .solver_policy import configure_solver, select_solver
except ImportError:
    from runtime import load_runtime, run_command, shared_output
    from simulation_resources import positive_integer, thread_initialization
    from solver_policy import configure_solver, select_solver


def parse_measurements(log: str, expected: list[str]) -> tuple[dict, dict]:
    """Parse scalar .meas/print output; duplicate or nonfinite values are invalid."""
    canonical = {key.lower(): key for key in expected}
    if len(canonical) != len(expected):
        raise ValueError("Duplicate expected measurement names")
    values, problems, seen = {}, {}, set()
    for line in log.splitlines():
        match = re.match(r"^\s*([^\s=]+)\s*=\s*(\S+)", line)
        if not match or match[1].lower() not in canonical:
            continue
        key = canonical[match[1].lower()]
        if key in seen:
            problems[key] = "duplicate measurement"
            values.pop(key, None)
            continue
        seen.add(key)
        try:
            value = float(match[2])
            if not math.isfinite(value):
                raise ValueError("non-finite")
            values[key] = value
        except ValueError:
            problems[key] = "non-finite or invalid measurement"
    for key in expected:
        if key not in values and key not in problems:
            problems[key] = "missing measurement"
    return values, problems


def run_deck(deck: Path, out: Path, timeout: float = 600,
             *, initialization: str = "set ngbehavior=hsa\nset num_threads=1\n",
             raw_output: Path | None = None, cancel_event=None,
             num_threads: int | None = None,
             solver_policy: str | None = None) -> dict:
    """Run the exact given deck with working directory ``out``.

    Relative include/write paths are resolved by ngspice with respect to out.
    Callers staging a testbench should make include paths absolute. The deck is
    not rewritten, and no thresholds, PVT conditions or source values are added.
    A trusted caller may explicitly select the solver policy for this run;
    otherwise ALB_VERIFIER_SOLVER_POLICY retains its historical opt-in behavior.
    """
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive and finite")
    if num_threads is not None:
        initialization = thread_initialization(initialization, num_threads)
    out = shared_output(out)
    out.mkdir(parents=True, exist_ok=True)
    deck = deck.resolve(strict=True)
    # Only trusted verification opts into the analysis-aware solver policy.
    # Ordinary native-tool use retains its supplied initialization unchanged.
    requested_solver = (solver_policy if solver_policy is not None
                        else os.environ.get("ALB_VERIFIER_SOLVER_POLICY"))
    solver = None
    if requested_solver is not None:
        solver = select_solver(deck, initialization, requested=requested_solver, cwd=out)
        solver["configuration_source"] = ("explicit_run_argument" if solver_policy is not None
                                          else "environment")
        initialization = configure_solver(initialization, solver["solver"])
    (out / "tmp").mkdir(exist_ok=True)
    (out / ".spiceinit").write_text(initialization)
    runtime = load_runtime()
    env = dict(os.environ, TMPDIR=str(out / "tmp"), SPICE_USERINIT_DIR=str(out),
               OMP_NUM_THREADS=str(num_threads if num_threads is not None else 1),
               OPENBLAS_NUM_THREADS="1")
    argv = [runtime["ngspice_bin"], "-b"]
    if raw_output is not None:
        raw_output = raw_output.resolve()
        if raw_output.parent != out:
            raise ValueError("Raw waveform output must be in the simulation working directory")
        argv += ["-r", str(raw_output)]
    argv.append(str(deck))
    cancellation = {} if cancel_event is None else {"cancel_event": cancel_event}
    command = {"argv": argv, **run_command(argv, cwd=out, env=env, timeout=timeout, **cancellation)}
    log = Path(command["log_path"]).read_text(errors="replace")
    # A .control block can print earlier measurements and call `quit` after an
    # analysis aborts. ngspice then exits zero; that is not a successful run.
    # Convergence warnings alone are recoverable and must not fail a run.
    analysis_errors = [line for line in log.splitlines() if re.search(
        r"^\s*(?:(?:run|op|tran|ac|dc|noise)\s+simulation\(s\)\s+aborted\b|"
        r"doAnalyses:|Simulation interrupted due to error\b)", line, re.I)]
    result = {"status": "completed" if command["status"] == "completed" and command["returncode"] == 0 and not analysis_errors else "tool_error",
              "deck": str(deck), "working_directory": str(out), "command": command,
              "execution_resources": {"num_threads": num_threads,
                                      "OMP_NUM_THREADS": env["OMP_NUM_THREADS"],
                                      "OPENBLAS_NUM_THREADS": env["OPENBLAS_NUM_THREADS"]},
              "analysis_errors": analysis_errors,
              "warnings": [line for line in log.splitlines() if re.search(r"warning|error|failed|singular matrix", line, re.I)],
              "outputs": [str(p.relative_to(out)) for p in sorted(out.rglob("*")) if p.is_file() and "tmp" not in p.relative_to(out).parts]}
    if solver is not None:
        solver["observed_solvers"] = sorted(set(re.findall(
            r"Using (KLU|SPARSE 1\.3) as Direct Linear Solver", log)))
        result["solver_policy"] = solver
    # An unavailable include/model is a configuration/dependency problem. A
    # convergence failure or timeout has no automatic infrastructure attribution.
    missing_dependency = re.search(r"could not find a valid modelname|unknown subckt|can't open|could not open|could not find include|error while loading shared libraries|version [^\n]+ not found|cannot execute binary file", log, re.I)
    if missing_dependency:
        result.update(status="tool_error", error_kind="environment_error")
    elif result["status"] != "completed":
        result["error_kind"] = command["status"] if command["status"] in {"timeout", "cancelled"} else "execution_error"
    return result


@contextmanager
def ordered_deck_runs(requests, runner, workers: int = 1):
    """Run only native commands concurrently, yielding results in input order.

    Each request is ``(context, run_deck_keyword_arguments)``. The caller's
    generator prepares each deck on the main thread. At most ``workers``
    requests are prepared/submitted ahead, and processing/aggregation stays in
    the caller. The context manager also cancels active native process groups
    when deck preparation, result processing or the caller itself fails.
    """
    positive_integer(workers, "Simulation workers")
    if workers == 1:
        yield ((context, runner(**options)) for context, options in requests)
        return
    cancellation = Event()
    pending = deque()
    source = iter(requests)
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="ngspice")

    def results():
        exhausted = False
        while pending or not exhausted:
            while len(pending) < workers and not exhausted:
                try:
                    context, options = next(source)
                except StopIteration:
                    exhausted = True
                    break
                pending.append((context, pool.submit(runner, **options,
                                                     cancel_event=cancellation)))
            if pending:
                context, future = pending.popleft()
                yield context, future.result()

    try:
        yield results()
    finally:
        cancellation.set()
        for _, future in pending:
            future.cancel()
        pool.shutdown(wait=True, cancel_futures=True)


SOLVER_RECHECK_POLICY = "klu-failure-sparse-recheck-v3"
SOLVER_RECHECK_DIRECTORY = "solver_sparse"
# Scale the optional per-command timeout, preserving its existing semantics.
# This factor is not a runtime estimate and never prevents a recheck starting.
# The caller's overall verifier budget remains authoritative.
SOLVER_RECHECK_TIMEOUT_FACTOR = 5
_RECHECK_DESCRIPTION = {
    "trigger": "primary solver KLU selected by policy and analysis not passed "
               "(failed predicate, missing/invalid measurement, execution error or timeout)",
    "recheck": "same testbench bytes and .spiceinit with only the matrix-solver option "
               "replaced by SPARSE, in case_xxxx/" + SOLVER_RECHECK_DIRECTORY,
    "adoption": "SPARSE result is adopted only if its own verdict passes; "
                "otherwise the primary KLU result remains authoritative",
    "not_triggered_for": "native deck solver selection, environment errors and cancellation",
}


def _file_sha256(path: Path) -> str | None:
    try:
        return hashlib.sha256(Path(path).read_bytes()).hexdigest()
    except OSError:
        return None


def solver_recheck_skip_reason(execution: dict) -> str | None:
    """Why a failed primary analysis gets no SPARSE recheck; None if eligible."""
    policy = execution.get("solver_policy")
    if not isinstance(policy, dict):
        return "solver_policy_not_applied"
    if policy.get("solver") != "klu":
        return "primary_solver_" + str(policy.get("solver"))
    if policy.get("native_deck_solver") is not None:
        # Native deck options are authoritative and the deck is never rewritten.
        return "native_deck_solver_selection"
    kind = execution.get("error_kind")
    if kind in {"environment_error", "cancelled"}:
        return "primary_" + kind
    return None


def sparse_recheck_arguments(options: dict) -> dict:
    """Name the existing retry inputs/outputs without creating or running them."""
    target = Path(options['out']) / SOLVER_RECHECK_DIRECTORY
    recheck = dict(options, deck=target / Path(options['deck']).name, out=target,
                   solver_policy='sparse',
                   timeout=options['timeout'] * SOLVER_RECHECK_TIMEOUT_FACTOR)
    if options.get('raw_output') is not None:
        recheck['raw_output'] = target / Path(options['raw_output']).name
    return recheck


def sparse_recheck_options(options: dict) -> dict:
    """run_deck arguments for the same deck in a separate SPARSE directory.

    The testbench bytes, initialization, thread allocation and raw-output
    request are unchanged; only the solver policy and the scaled timeout differ.
    """
    recheck = sparse_recheck_arguments(options)
    target = recheck['out']
    target.mkdir()
    deck = recheck['deck']
    shutil.copyfile(options["deck"], deck)
    return recheck


def _solver_attempt(index: int, role: str, options: dict, execution: dict | None,
                    outcome: dict) -> dict:
    execution = execution or {}
    policy = execution.get("solver_policy") or {}
    command = execution.get("command") or {}
    init = Path(options["out"]) / ".spiceinit"
    try:
        spiceinit = init.read_text()
    except OSError:
        spiceinit = None
    return {"attempt": index, "role": role,
            "solver": policy.get("solver", "sparse" if role == "sparse_recheck" else None),
            "observed_solvers": policy.get("observed_solvers"),
            "solver_reason": policy.get("reason"),
            "working_directory": str(options["out"]),
            "deck_sha256": _file_sha256(options["deck"]),
            "spiceinit": spiceinit,
            "timeout_seconds": options["timeout"],
            "execution_status": execution.get("status"),
            "error_kind": execution.get("error_kind"),
            "returncode": command.get("returncode"),
            "seconds": command.get("seconds"),
            **outcome["evidence"]}


def primary_analysis_checkpoint(options: dict, execution: dict, outcome: dict) -> dict:
    """Retain the primary verdict before an eligible recheck starts.

    A verifier interruption must not erase a completed primary analysis while
    SPARSE is still running. ``pending`` never claims that a recheck completed
    or passed; normal recheck admission and adoption remain unchanged.
    """
    attempt = _solver_attempt(1, "primary", options, execution, outcome)
    reason = solver_recheck_skip_reason(execution)
    decision = ({"status": "not_needed"} if outcome["passed"] else
                {"status": "skipped", "reason": reason} if reason is not None else
                {"status": "pending"})
    return {"solver_attempts": [attempt], "solver_disagreement": False,
            "adopted_solver": attempt["solver"], "solver_recheck": decision}


def completed_solver_recheck(options: dict, execution: dict, outcome: dict,
                             recheck: dict, second: dict, second_outcome: dict):
    """Apply the unchanged adoption rule to two already evaluated attempts.

    No commands are launched here. The same operation can finalize a completed
    retry receipt during interruption cleanup without admitting any new work.
    """
    info = primary_analysis_checkpoint(options, execution, outcome)
    attempts = info['solver_attempts']
    attempts[0].update(outcome.get('detail', {}))
    attempts.append(_solver_attempt(2, 'sparse_recheck', recheck, second, second_outcome))
    attempts[1].update(second_outcome.get('detail', {}))
    adopted = bool(second_outcome['passed'])
    info.update(solver_disagreement=adopted,
                adopted_solver='sparse' if adopted else attempts[0]['solver'],
                solver_recheck={'status': 'completed', 'adopted': adopted})
    return (second_outcome if adopted else outcome), info, second


def recheck_failed_analysis(runner, options: dict, execution: dict, outcome: dict,
                            evaluate) -> tuple[dict, dict, dict | None]:
    """KLU-failure SPARSE recheck of one post-layout analysis.

    ``outcome`` is the caller's own verdict for ``execution``: a mapping with
    Boolean ``passed``, JSON ``evidence`` (always recorded), optional JSON
    ``detail`` (recorded for both attempts when a recheck runs) and the
    caller's ``payload``. ``evaluate(execution, directory)`` returns the same
    kind of verdict for the recheck. Returns ``(adopted_outcome, info,
    recheck_execution)``. ``info`` contains ``solver_attempts``,
    ``solver_disagreement``, ``adopted_solver`` and ``solver_recheck``. Both
    attempts remain recorded; a SPARSE pass never silently replaces evidence.
    Eligible rechecks start without predicting runtime from a failed primary.
    The caller's verifier budget can interrupt them through normal cleanup.
    """
    info = primary_analysis_checkpoint(options, execution, outcome)
    attempts = info["solver_attempts"]
    if outcome["passed"]:
        info["solver_recheck"] = {"status": "not_needed"}
        return outcome, info, None
    reason = solver_recheck_skip_reason(execution)
    if reason is not None:
        info["solver_recheck"] = {"status": "skipped", "reason": reason}
        return outcome, info, None
    attempts[0].update(outcome.get("detail", {}))
    recheck = dict(options, out=Path(options["out"]) / SOLVER_RECHECK_DIRECTORY,
                   timeout=options["timeout"] * SOLVER_RECHECK_TIMEOUT_FACTOR)
    try:
        recheck = sparse_recheck_options(options)
        second = runner(**recheck)
    except (OSError, ValueError) as exc:
        # A recheck that cannot run leaves the primary verdict authoritative.
        error = f"{type(exc).__name__}: {exc}"
        attempts.append(_solver_attempt(2, "sparse_recheck", recheck, None, {"evidence": {
            "verdict": "error", "passed": False, "error": error}}))
        info["solver_recheck"] = {"status": "error", "error": error}
        return outcome, info, None
    second_outcome = evaluate(second, recheck["out"])
    return completed_solver_recheck(options, execution, outcome, recheck, second, second_outcome)


def solver_recheck_summary(infos: dict) -> dict:
    """Metrics-level account of every per-analysis recheck decision."""
    def ids(predicate):
        return [key for key, info in infos.items() if predicate(info)]
    return {"policy": SOLVER_RECHECK_POLICY, "enabled": True, "recheck_solver": "sparse",
            "timeout_factor": SOLVER_RECHECK_TIMEOUT_FACTOR, **_RECHECK_DESCRIPTION,
            "rechecked_case_ids": ids(lambda i: i["solver_recheck"]["status"] in {"completed", "error"}),
            "adopted_case_ids": ids(lambda i: i["solver_recheck"].get("adopted") is True),
            "disagreement_case_ids": ids(lambda i: i["solver_disagreement"]),
            "skipped": {key: info["solver_recheck"]["reason"] for key, info in infos.items()
                        if info["solver_recheck"]["status"] == "skipped"}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deck", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=600)
    args = parser.parse_args(argv)
    out = shared_output(args.out)
    out.mkdir(parents=True, exist_ok=False)
    try:
        result = run_deck(args.deck, out, args.timeout)
    except (OSError, ValueError, KeyError) as exc:
        result = {"status": "tool_error", "error_kind": "invalid_input", "error": str(exc)}
    (out / "metrics.json").write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps(result, allow_nan=False))
    return 0 if result["status"] == "completed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
