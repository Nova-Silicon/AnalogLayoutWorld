"""Evaluate a frozen layout submission with trusted tools and task-specific benches.

No submitted Python or agent-authored report is executed or consulted. Individual
tool processes have bounded timeouts; the caller must contain this evaluator in
its own job with a budget appropriate to the task's case count. ``pipeline_completed``
means all applicable stages reached a terminal state, including explicit skips;
``tool_error`` and ``design_passed`` describe different outcomes.
``design_passed`` applies to the configured electrical evaluation cases; it does
not assert coverage of source requirements outside an explicit case selection.
"""
from __future__ import annotations

import argparse
from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import signal
import stat
import threading
import time
import traceback

from . import pex, postsim, verify
from .runtime import cleanup_on_termination, sha256, shared_output, load_runtime, work_env, run_command
from .scoring import summarize_cases
from analoglayoutworld.scoring import SCORING_VERSION, assess_shape, finite_number, score_submission
from .simulation_resources import verifier_cpu_budget


STAGES = ("drc", "lvs", "area", "quality", "pex", "postsim")
TIMEOUTS = {"drc": 180, "lvs": 180, "area": 180, "quality": 180, "pex": 180, "postsim": 600}


class SubmissionError(ValueError):
    """An incomplete or unsafe submission, rather than an infrastructure error."""


class VerifierBudgetExpired(BaseException):
    """The declared verifier budget expired; unlike SIGTERM, this is scoreable."""

    def __init__(self, *, expired_at_monotonic=None):
        super().__init__()
        # Cleanup can take time. Recovery must not count native executions that
        # only returned after the declared budget had already expired.
        self.expired_at_monotonic = (time.monotonic() if expired_at_monotonic is None
                                     else expired_at_monotonic)


class VerifierBudgetClock:
    def __init__(self):
        self.active = True

    def disarm(self):
        # Flip the flag first: a pending signal must not interrupt final scoring.
        self.active = False
        signal.setitimer(signal.ITIMER_REAL, 0)


@contextmanager
def verifier_budget():
    """Bound a verifier run without turning external interruption into a score.

    The signal interrupts synchronous native-tool waits. Their existing cleanup
    paths terminate and reap the command process groups before evaluate() marks
    the unfinished stage as budget-limited and finalizes completed stages.
    """
    raw = os.environ.get("ALB_VERIFIER_BUDGET_SEC")
    if raw is None:
        yield None
        return
    try:
        seconds = float(raw)
    except ValueError as error:
        raise ValueError("ALB_VERIFIER_BUDGET_SEC must be a positive finite number") from error
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("ALB_VERIFIER_BUDGET_SEC must be a positive finite number")
    if threading.current_thread() is not threading.main_thread():
        raise RuntimeError("The verifier budget must run on the main thread")
    if signal.getitimer(signal.ITIMER_REAL)[0] > 0:
        raise RuntimeError("The verifier budget cannot replace another active timer")
    previous = signal.getsignal(signal.SIGALRM)
    clock = VerifierBudgetClock()

    def expire(_signum, _frame):
        if clock.active:
            clock.disarm()
            raise VerifierBudgetExpired(expired_at_monotonic=deadline)

    signal.signal(signal.SIGALRM, expire)
    try:
        deadline = time.monotonic() + seconds
        signal.setitimer(signal.ITIMER_REAL, seconds)
        yield clock
    finally:
        clock.disarm()
        signal.signal(signal.SIGALRM, previous)


def write_json(path: Path, value: dict) -> None:
    # Atomic replacement keeps already completed stages readable if interrupted.
    temporary = path.with_name(path.name + ".new")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def freeze_file(source: Path, destination: Path) -> str:
    """Copy a regular file without following symlinks; detect concurrent edits."""
    with os.fdopen(os.open(source, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK), "rb") as handle:
        before = os.fstat(handle.fileno())
        if not stat.S_ISREG(before.st_mode):
            raise ValueError(f"Not a regular file: {source.name}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        with destination.open("xb") as target:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                target.write(chunk)
        after = os.fstat(handle.fileno())
        current = source.lstat()
        identity = lambda item: (item.st_dev, item.st_ino, item.st_size, item.st_mtime_ns, item.st_ctime_ns)
        if identity(before) != identity(after) or identity(after) != identity(current):
            raise ValueError(f"Input changed during snapshot: {source.name}")
    destination.chmod(0o444)
    return digest.hexdigest()


def freeze_tree(source: Path, destination: Path) -> dict[str, str]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError(f"Expected a regular directory: {source.name}")
    destination.mkdir(parents=True, exist_ok=False)
    hashes = {}
    for item in sorted(source.iterdir()):
        target = destination / item.name
        if item.is_symlink():
            raise ValueError(f"Symlink is not a snapshot input: {item.name}")
        if item.is_dir():
            hashes.update({f"{item.name}/{name}": digest
                           for name, digest in freeze_tree(item, target).items()})
        else:
            hashes[item.name] = freeze_file(item, target)
    return hashes


def require_artifact(path: Path, expected_hash: str | None = None) -> str:
    if path.is_symlink() or not path.is_file() or not path.stat().st_size:
        raise RuntimeError(f"Missing or empty stage artifact: {path.name}")
    actual = sha256(path)
    if expected_hash is not None and actual != expected_hash:
        raise RuntimeError(f"Stage artifact hash mismatch: {path.name}")
    return actual


def run_stage(name: str, out: Path, gds: Path, task: Path, top: str,
              profile: str, input_hashes: dict, netlist: Path | None = None,
              *, lvs_result_path: Path | None = None) -> dict:
    """Run trusted tools and retain their reports without hashing transformed views.

    The task/submission snapshots are immutable inputs. In particular the LVS
    reference may legitimately be rewritten by the qualified reference adapter;
    its bytes must not be compared to those of the original SPICE file.
    """
    started = time.monotonic()
    result_file = out / ("result.json" if name in ("drc", "lvs", "area") else "metrics.json")
    parameters = {"out": str(out), "task": str(task), "timeout": TIMEOUTS[name]}
    if name in ("drc", "lvs", "area", "pex"):
        parameters.update(gds=str(gds), top=top)
    if name in ("drc", "lvs", "area"):
        function = "eda.verify.verify"
        parameters["mode"] = name
        if name == "area":
            parameters["lvs_result_path"] = str(lvs_result_path) if lvs_result_path else None
    elif name == "pex":
        function = "eda.pex.extract"
        parameters["mode"] = "rc"
    else:
        function = "eda.postsim.simulate"
        parameters.update(netlist=str(netlist), profile=profile)
    stage = {"status": "error", "value": None, "reason": None,
             "invocation": {"function": function, "parameters": parameters},
             "result_file": str(result_file), "tool_result": None}
    try:
        if name in ("drc", "lvs", "area"):
            if name == "area":
                result = verify.verify(name, gds, top, task, out, TIMEOUTS[name],
                                       lvs_result_path=lvs_result_path)
            else:
                result = verify.verify(name, gds, top, task, out, TIMEOUTS[name])
        else:
            out.mkdir(parents=True, exist_ok=False)
            if name == "pex":
                result = pex.extract(gds, top, task, out, "rc", TIMEOUTS[name])
            else:
                require_artifact(netlist, input_hashes["netlist"])
                # Share the actual allocated CPUs between independent native
                # simulations and each process's OpenMP model evaluation.
                cpus = verifier_cpu_budget()
                # Post-layout only: a policy-selected KLU failure is rechecked
                # once with SPARSE; both attempts stay in the evidence.
                parameters.update(workers=cpus, cpu_budget=cpus, solver_recheck=True)
                result = postsim.simulate(task, netlist, out, profile, TIMEOUTS[name],
                                         workers=cpus, cpu_budget=cpus,
                                         solver_recheck=True)
            write_json(result_file, result)
        if not isinstance(result, dict):
            raise RuntimeError("Stage returned a non-object result")
        json.dumps(result, allow_nan=False)
        stage["tool_result"] = result
        status = result.get("status")
        allowed = ({"passed", "failed", "error"} if name in ("drc", "lvs") else
                   {"measured", "failed", "error"} if name == "area" else
                   {"completed", "failed", "tool_error"} if name == "pex" else
                   {"completed", "measurement_failed", "tool_error"})
        if status not in allowed:
            raise RuntimeError(f"Unexpected terminal stage status: {status!r}")
        require_artifact(result_file)
        stage.update(status="error" if status in ("error", "tool_error") else status,
                     reason=result.get("reason", result.get("error")),
                     error_kind=result.get("error_kind"))
        if name == "postsim" and "solver_recheck" in result:
            stage.update(solver_disagreement=bool(result.get("solver_disagreement")),
                         solver_recheck=result["solver_recheck"])
        if status in ("error", "tool_error"):
            # Timeout/execution failure is not proof that the image or model
            # installation is broken. Preserve that distinction and raw logs.
            if result.get("error_kind") in ("execution_error", "timeout", "design_error"):
                stage["status"] = "measurement_failed" if name == "postsim" else "failed"
                if name == "postsim":
                    require_artifact(netlist, input_hashes["netlist"])
                    cases = summarize_cases(postsim.expected_cases(task, "full"), result)
                    stage["case_summary"] = cases
                    stage["value"] = False
            return stage
        if name in ("drc", "lvs", "area"):
            if status == "passed":
                backend = json.loads((task / "constraints.json").read_text()).get("lvs_backend", "klayout")
                if name == "lvs" and backend == "magic_netgen":
                    if result.get("backend") != backend:
                        raise RuntimeError("LVS result does not use the task's trusted backend")
                    for artifact in ("netgen/report.json", "netgen/report.out", "extracted.spice"):
                        require_artifact(out / artifact)
                else:
                    require_artifact(out / ("report.lyrdb" if name == "drc" else "report.lvsdb"))
            if name == "area" and status == "measured":
                value = result.get("area_um2")
                if not finite_number(value) or value <= 0:
                    raise RuntimeError("Area measurement is not positive and finite")
                stage["value"] = value
                expected_area = verify.extracted_area_metrics(gds, top, task, value,
                                                               lvs_result_path)
                if any(result.get(key) != expected for key, expected in expected_area.items()):
                    raise RuntimeError("Area utilization differs from the trusted task definition")
            elif name != "area":
                stage["value"] = status == "passed"
        elif name == "pex" and status == "completed":
            extracted = out / "extracted.spice"
            if result.get("mode") != "rc" or Path(result.get("netlist_path", "")) != extracted:
                raise RuntimeError("PEX returned a different mode or output path")
            require_artifact(extracted, result.get("netlist_sha256"))
            stage["value"] = True
        elif name == "postsim" and status in ("completed", "measurement_failed"):
            # The reported cases are independently reduced against trusted task
            # limits later; a missing measurement is not an infrastructure error.
            require_artifact(netlist, input_hashes["netlist"])
            cases = summarize_cases(postsim.expected_cases(task, "full"), result)
            requested_ids = postsim.expected_cases(task, profile)
            stage["value"] = all(cases["case_results"][key]["passed"] for key in requested_ids)
            stage["case_summary"] = cases
    except Exception as error:
        out.mkdir(parents=True, exist_ok=True)
        (out / "exception.log").write_text(traceback.format_exc())
        stage.update(status="error", value=None, reason=f"{type(error).__name__}: {error}",
                     error_kind="verifier_error")
        if name in ("pex", "postsim") and stage["tool_result"] is None:
            if result_file.exists():
                shutil.copyfile(result_file, out / "partial_metrics.json")
            write_json(result_file, {"status": "tool_error", "error_kind": "verifier_error",
                                     "error": stage["reason"]})
    finally:
        stage["seconds"] = round(time.monotonic() - started, 3)
        stage["logs"] = [{"path": str(path)} for path in sorted(out.rglob("*.log"))
                         if path.is_file() and not path.is_symlink()]
        write_json(out / "stage.json", stage)
    return stage


def run_quality_stage(gds: Path, task: Path, out: Path, task_name: str,
                      lvs_result: Path, area_result: Path) -> dict:
    """Collect trusted geometry facts in a bounded, separately reaped process."""
    started = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    argv = [load_runtime()["python_bin"], "-m", "eda.quality", "--gds", str(gds),
            "--lvs-result", str(lvs_result), "--task", str(task),
            "--task-name", task_name, "--out", str(out)]
    if area_result.is_file():
        argv.extend(("--area-report", str(area_result)))
    env = work_env(out)
    cpus = str(verifier_cpu_budget())
    env.update(OMP_NUM_THREADS=cpus, OPENBLAS_NUM_THREADS=cpus, MKL_NUM_THREADS=cpus)
    # This is the frozen tools tree, never the Agent workspace.
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1])
    stage = {"status": "error", "value": None, "tool_result": None,
             "result_file": str(out / "result.json"),
             "invocation": {"function": "eda.quality.collect", "command": argv,
                            "timeout": TIMEOUTS["quality"]}}
    try:
        command = run_command(argv, cwd=out, env=env, timeout=TIMEOUTS["quality"])
        stage["command"] = command
        if command["status"] != "completed" or command["returncode"] not in (0, 2):
            stage.update(reason="Quality process did not complete", error_kind=command["status"])
        else:
            path = out / "result.json"
            require_artifact(path)
            result = json.loads(path.read_text())
            if result.get("status") not in ("completed", "policy_credit", "partial", "error"):
                raise ValueError("Invalid quality collection status")
            stage.update(tool_result=result, value=result["status"] in ("completed", "policy_credit"),
                         status=("completed" if result["status"] in ("completed", "policy_credit") else
                                 "measurement_failed" if result["status"] == "partial" else "error"),
                         reason=result.get("reason"), result_sha256=sha256(path))
    except Exception as error:
        stage.update(reason=f"{type(error).__name__}: {error}", error_kind="quality_collection_error")
        (out / "exception.log").write_text(traceback.format_exc())
    finally:
        stage["seconds"] = round(time.monotonic() - started, 3)
        stage["logs"] = [{"path": str(path)} for path in sorted(out.rglob("*.log"))
                         if path.is_file() and not path.is_symlink()]
        write_json(out / "stage.json", stage)
    return stage


def frozen_task_name(snapshot: Path) -> str:
    """Read the task identifier from the verifier's input snapshot."""
    identity = snapshot / "identity.json"
    if not identity.is_file():
        raise ValueError("A standalone verifier requires a trusted task identity")
    value = json.loads(identity.read_text())
    if (not isinstance(value, dict) or value.get("schema_version") != 1
            or set(value) != {"schema_version", "task_name"}):
        raise ValueError("Invalid trusted task identity")
    name = value["task_name"]
    if (not isinstance(name, str) or not name or name in ("task", "tests")
            or any(character not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
                   for character in name)):
        raise ValueError("A standalone verifier requires a trusted task identity")
    return name


def evaluate(submission_dir: Path, task: Path, out: Path, profile: str = "full",
             *, budget: VerifierBudgetClock | None = None) -> dict:
    started = time.monotonic()
    result = {"schema_version": 3, "scoring_version": SCORING_VERSION,
              "status": "running", "profile": profile,
              "pipeline_completed": False, "tool_error": False, "evaluation_error": False,
              "design_passed": False,
              "electrical_scope": None, "evaluation_case_ids": None,
              "electrical_coverage": None, "original_spec_passed": None,
              "unassessed_requirements": [],
              "requested_profile_passed": False, "electrical_eligible": False,
              "submission_present": False, "artifact_contract_complete": False,
              "input_integrity_error": False, "extraction_qualification": "provisional",
              "nf_audit": "not_implemented",
              "source_regeneration_checked": False, "snapshot_hashes": {},
              "artifact_issues": [], "stages": {}, "reward": None, "score": None,
              "score_valid": False,
              "limitations": [pex.LIMITATION,
                              "LVS does not independently audit nf or original logical-instance grouping.",
                              "Source is archived, not executed; regeneration is not verified.",
                              "Raw extracted-device-area ratio is retained; scored area credit is capped at its target. "
                              "TT is not full-specification coverage."],
              "timeout_policy": {"per_tool_seconds": TIMEOUTS}}
    created = False
    expected_cases = None
    active_stage = None
    task_copy = None
    submission_copy = None
    task_hashes = None
    gds_hash = None
    frozen_ready = False
    expected = {}
    task_name = task.parent.parent.name if task.parent.name == "tests" else None

    def save():
        result["seconds"] = round(time.monotonic() - started, 3)
        write_json(out / "metrics.json", result)
        # Stage tool failures retain independent credit and their diagnostics.
        # Fatal evaluation/input errors must still not publish invented scores.
        if result["score_valid"]:
            write_json(out / "reward.json", {"reward": result["score"]})

    def skip(name: str, reason: str):
        directory = out / "stages" / name
        directory.mkdir(parents=True, exist_ok=False)
        stage = {"status": "skipped", "value": None, "reason": reason,
                 "seconds": 0, "invocation": None, "result_file": None,
                 "tool_result": None, "logs": []}
        result["stages"][name] = stage
        write_json(directory / "stage.json", stage)

    def check_frozen_inputs():
        for root, manifest in ((task_copy, task_hashes),
                               (submission_copy, {"layout.gds": gds_hash})):
            for filename, digest in manifest.items():
                try:
                    unchanged = not (root / filename).is_symlink() and sha256(root / filename) == digest
                except OSError:
                    unchanged = False
                if not unchanged:
                    result["input_integrity_error"] = True
                    raise RuntimeError(f"Frozen input changed: {filename}")
        pex_stage = result["stages"].get("pex", {})
        if pex_stage.get("status") == "completed":
            try:
                require_artifact(out / "stages/pex/extracted.spice",
                                 expected.get("netlist"))
            except RuntimeError:
                result["input_integrity_error"] = True
                raise

    def budget_limited_stage(name: str):
        directory = out / "stages" / name
        directory.mkdir(parents=True, exist_ok=True)
        previous = directory / "stage.json"
        try:
            prior = json.loads(previous.read_text()) if previous.is_file() else {}
        except (OSError, ValueError):
            prior = {}
        stage = {"status": "measurement_failed" if name == "postsim" else "failed",
                 "value": False if name != "area" else None,
                 "reason": "Declared verifier wall-clock budget exhausted",
                 "error_kind": "verifier_budget",
                 "seconds": prior.get("seconds", 0),
                 "invocation": prior.get("invocation"),
                 "result_file": prior.get("result_file"),
                 "tool_result": None,
                 "logs": [{"path": str(path)} for path in sorted(directory.rglob("*.log"))
                          if path.is_file() and not path.is_symlink()]}
        if name == "postsim":
            stage["case_summary"] = summarize_cases(expected_cases, None)
            progress = directory / "metrics.json"
            if progress.is_file() and not progress.is_symlink():
                try:
                    require_artifact(out / "stages/pex/extracted.spice", expected.get("netlist"))
                    partial = json.loads(progress.read_text())
                    if not isinstance(partial, dict):
                        raise ValueError("Partial simulation report must be an object")
                    stage["case_summary"] = summarize_cases(expected_cases, partial)
                    stage.update(tool_result=partial, result_file=str(progress),
                                 partial_evidence_retained=True)
                except Exception as error:
                    stage.update(partial_evidence_error=f"{type(error).__name__}: {error}")
                    # An altered extracted DUT cannot receive partial credit.
                    try:
                        require_artifact(out / "stages/pex/extracted.spice", expected.get("netlist"))
                    except Exception:
                        result.update(input_integrity_error=True, tool_error=True)
        result["stages"][name] = stage
        write_json(previous, stage)

    try:
        out = shared_output(out)
        if any(out.is_relative_to(source.resolve()) for source in (submission_dir, task)):
            raise ValueError("Evaluation output must be outside submission and task directories")
        out.mkdir(parents=True, exist_ok=False)
        created = True
        if profile not in ("tt", "full"):
            raise ValueError("profile must be tt or full")
        task_copy = out / "snapshot" / "task"
        task_hashes = freeze_tree(task, task_copy)
        result["snapshot_hashes"]["task"] = task_hashes
        task_name = frozen_task_name(task_copy)
        result["task_name"] = task_name
        constraints = json.loads((task_copy / "constraints.json").read_text())
        top = constraints["top"]
        verify.task_contract(task_copy, top)
        required_cases = postsim.expected_cases(task_copy, "full")
        summarize_cases(required_cases, None)  # Validate the trusted scoring denominator.
        expected_cases = required_cases
        selection = postsim.measurement_settings(task_copy).get("evaluation_case_ids")
        result["evaluation_case_ids"] = selection
        result["electrical_scope"] = (
            "diagnostic" if profile != "full" else
            "selected_evaluation" if selection is not None else "full_source_plan")
        if selection is not None:
            result["limitations"].append(
                "Electrical scoring covers the explicitly selected public testbench cases. "
                "A passing benchmark score does not establish the untested original SPEC.")
        pex.load_task(task_copy)
        result["limitations"].extend(constraints.get("audit_limitations", []))
        submission_copy = out / "snapshot" / "submission"
        submission_copy.mkdir()
        original_gds, gds = submission_dir / "layout.gds", submission_copy / "layout.gds"
        if not original_gds.exists() and not original_gds.is_symlink():
            result["status"] = "missing_submission"
            result["artifact_issues"].append("Required submission/layout.gds is missing")
        else:
            try:
                gds_hash = freeze_file(original_gds, gds)
            except (OSError, ValueError) as error:
                raise SubmissionError(f"Cannot freeze layout.gds: {error}") from error
            result["submission_present"] = True
            result["snapshot_hashes"]["submission"] = {"layout.gds": gds_hash}
            frozen_ready = True
            hashes = result["snapshot_hashes"]["submission"]
            # Source is archived for inspection. README is optional and has no
            # effect on acceptance; the submitted GDS is the graded artifact.
            artifact_names = ["src"]
            if (submission_dir / "README.md").exists() or (submission_dir / "README.md").is_symlink():
                artifact_names.append("README.md")
            for name in artifact_names:
                try:
                    if name == "src":
                        sources = freeze_tree(submission_dir / name, submission_copy / name)
                        hashes.update({f"src/{filename}": digest for filename, digest in sources.items()})
                        if not any(filename.endswith(".py") for filename in sources):
                            raise ValueError("src/ contains no Python source")
                    else:
                        hashes[name] = freeze_file(submission_dir / name, submission_copy / name)
                        if not (submission_copy / name).stat().st_size:
                            raise ValueError("README.md is empty")
                except (OSError, ValueError) as error:
                    result["artifact_issues"].append(f"{name}: {error}")
            result["artifact_contract_complete"] = not result["artifact_issues"]
            expected = {**task_hashes, "gds": gds_hash}
            for name in ("drc", "lvs", "area"):
                active_stage = name
                area_evidence = ({"lvs_result_path": out / "stages/lvs/result.json"
                                  if result["stages"].get("lvs", {}).get("status") == "passed"
                                  else None} if name == "area" else {})
                result["stages"][name] = run_stage(name, out / "stages" / name, gds,
                                                  task_copy, top, profile, expected, **area_evidence)
                active_stage = None
                save()
            shape = assess_shape(
                result["stages"]["area"].get("tool_result") or {},
                task_name=task_name,
            )
            # Collect electrical evidence independently of the current shape
            # threshold: q_max is a scoring parameter that reports may preview
            # later, so it must not decide whether PEX/post-simulation evidence
            # exists. DRC is a scored fact; LVS establishes electrical identity.
            electrical_prerequisites_pass = result["stages"]["lvs"]["status"] == "passed"
            if electrical_prerequisites_pass:
                active_stage = "quality"
                result["stages"]["quality"] = run_quality_stage(
                    gds, task_copy, out / "stages/quality", task_name,
                    out / "stages/lvs/result.json", out / "stages/area/result.json")
                active_stage = None
                save()
            else:
                skip("quality", "LVS must pass before engineering-quality collection")
            if electrical_prerequisites_pass:
                active_stage = "pex"
                result["stages"]["pex"] = run_stage("pex", out / "stages/pex", gds,
                                                   task_copy, top, profile, expected)
                active_stage = None
                save()
            else:
                skip("pex", "LVS must pass before PEX/post-simulation")
            if result["stages"]["pex"]["status"] == "completed":
                expected["netlist"] = sha256(out / "stages/pex/extracted.spice")
                active_stage = "postsim"
                result["stages"]["postsim"] = run_stage(
                    "postsim", out / "stages/postsim", gds, task_copy, top, profile,
                    expected, out / "stages/pex/extracted.spice")
                active_stage = None
            else:
                skip("postsim", "PEX did not complete successfully")
            # Recheck all consumed frozen inputs after every applicable stage has finished.
            check_frozen_inputs()
            result["status"] = "evaluated"
        for name in STAGES:
            if name not in result["stages"]:
                skip(name, "Submission GDS is unavailable")
        result["pipeline_completed"] = True
        if budget is not None:
            budget.disarm()
    except VerifierBudgetExpired:
        if budget is not None:
            budget.disarm()
        result.update(status="budget_exhausted", verifier_budget_exhausted=True,
                      reason="Declared verifier wall-clock budget exhausted")
        if not frozen_ready:
            result.update(tool_error=True, reason="Verifier budget expired before inputs were frozen")
        else:
            try:
                check_frozen_inputs()
            except Exception as error:
                result.update(tool_error=True, reason=f"{type(error).__name__}: {error}")
            for name in STAGES:
                if name not in result["stages"]:
                    if name == active_stage or (out / "stages" / name).exists():
                        # The timer may also interrupt skip() after mkdir but
                        # before that skipped stage is recorded in memory.
                        budget_limited_stage(name)
                    else:
                        skip(name, "Verifier budget exhausted before this stage")
            # A signal can land between skip() updating memory and its atomic
            # stage write. Make the finalized stage snapshots match the score.
            for name, stage in result["stages"].items():
                write_json(out / "stages" / name / "stage.json", stage)
            result["pipeline_completed"] = True
    except SystemExit as error:
        if budget is not None:
            budget.disarm()
        # An external verifier timeout is not an electrical failure or a valid
        # partial score. Retain completed stages without publishing a reward.
        result.update(status="interrupted", tool_error=True,
                      reason=f"Verifier interrupted with exit code {error.code}")
        raise
    except SubmissionError as error:
        if budget is not None:
            budget.disarm()
        result.update(status="invalid_submission", reason=str(error), pipeline_completed=True)
        result["artifact_issues"].append(str(error))
        for name in STAGES:
            if name not in result["stages"]:
                skip(name, "Submission GDS could not be snapshotted")
    except Exception as error:
        if budget is not None:
            budget.disarm()
        result.update(status="tool_error", tool_error=True, reason=f"{type(error).__name__}: {error}")
        if created:
            (out / "exception.log").write_text(traceback.format_exc())
    finally:
        if budget is not None:
            budget.disarm()
        stages = result["stages"]
        # Before aggregation, tool_error denotes an outer evaluation failure.
        # A caught error inside one tool stage must not cancel other stages.
        result["evaluation_error"] = result["tool_error"] or result["input_integrity_error"]
        result["tool_error"] = result["tool_error"] or any(s["status"] == "error" for s in stages.values())
        simulation = stages.get("postsim", {})
        cases = simulation.get("case_summary")
        if cases is None and expected_cases:
            # Skipped/error stages retain the complete task denominator.
            cases = summarize_cases(expected_cases, None)
        if cases is None:
            cases = {"required_case_count": 0, "passed_case_count": 0, "pass_fraction": 0.0,
                     "all_passed": False, "case_results": {}}
        result["postsim_group_cases"] = cases
        # Keep the old grouped verdict for diagnostics. The new fraction uses
        # the fixed required analyses, not one Boolean wrapper per PVT group.
        if task_copy is not None and frozen_ready:
            from .postsim_fraction import summarize as summarize_fraction
            try:
                # A structurally rejected report cannot regain electrical
                # credit through the new leaf-level reader. Ordinary timeouts
                # still retain analyses completed before the interruption.
                report = (None if simulation.get("error_kind") == "verifier_error"
                          else simulation.get("tool_result"))
                cases = summarize_fraction(task_copy, report, profile="full")
            except Exception as error:
                result.update(evaluation_error=True, tool_error=True,
                              reason=f"Invalid post-simulation scoring evidence: {type(error).__name__}: {error}")
                cases = {"required_case_count": len(expected_cases or {}),
                         "passed_case_count": 0, "pass_fraction": 0.0, "coverage": 0.0,
                         "all_passed": False, "case_results": {}}
        result["postsim_cases"] = cases
        scored = score_submission(submission_present=result["submission_present"], stages=stages,
                                  cases=cases, profile=profile,
                                  evaluation_error=result["evaluation_error"],
                                  scoring_version=SCORING_VERSION,
                                  task_name=task_name)
        result.update(scored)
        simulation_report = simulation.get("tool_result") or {}
        result["electrical_coverage"] = simulation_report.get("coverage")
        result["unassessed_requirements"] = simulation_report.get(
            "unassessed_requirements",
            (simulation_report.get("source_evidence") or {}).get("unassessed_requirements", []))
        # Only an unselected source plan with explicit complete-measurement
        # evidence can claim original-SPEC coverage. Selected success must not
        # be promoted to such a claim, even if a tool report says "all passed".
        if (result["electrical_scope"] == "full_source_plan"
                and simulation_report.get("original_spec_fully_measured") is True):
            result["original_spec_passed"] = bool(
                cases["all_passed"] and result["electrical_eligible"]
                and not result["tool_error"] and not result["input_integrity_error"])
        result["reward"] = {"reward": result["score"]} if result["score_valid"] else None
        simulation["eligible"] = result["electrical_eligible"]
        area = stages.get("area", {})
        area["utilization_eligible"] = result["area_eligible"]
        requested = (simulation.get("status") in ("completed", "measurement_failed")
                     and simulation.get("value") is True)
        result["requested_profile_passed"] = bool(result["electrical_eligible"] and requested
                                                   and not result["tool_error"])
        result["diagnostics"]["postsim_requested_pass"] = int(
            result["electrical_eligible"] and requested)
        if created:
            if "area" in stages:
                write_json(out / "stages/area/stage.json", area)
            if "postsim" in stages:
                write_json(out / "stages/postsim/stage.json", simulation)
            save()
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--submission-dir", type=Path, required=True)
    parser.add_argument("--task", type=Path, required=True, help="Trusted public task input directory")
    parser.add_argument("--out", type=Path, required=True, help="New output directory inside the configured report root")
    parser.add_argument("--profile", choices=("tt", "full"), default="full")
    args = parser.parse_args(argv)
    with cleanup_on_termination():
        with verifier_budget() as budget:
            result = evaluate(args.submission_dir, args.task, args.out, args.profile,
                              budget=budget)
    print(json.dumps(result, indent=2, allow_nan=False))
    if result["evaluation_error"] or (args.profile == "full" and not result["score_valid"]):
        return 2
    return 0 if result["requested_profile_passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
