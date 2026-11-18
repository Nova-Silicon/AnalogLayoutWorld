"""Docker-based evaluation of an existing submission; no model API is required."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import tomllib
import uuid


def repository_root(value: str | None = None) -> Path:
    root = Path(value).expanduser().resolve() if value else Path(__file__).resolve().parents[2]
    if not (root / "configs/paper-v1/tasks.json").is_file():
        raise ValueError("Use --repository with the checked-out AnalogLayoutWorld directory")
    return root


def task_rows(root: Path) -> dict:
    data = json.loads((root / "configs/paper-v1/tasks.json").read_text())
    return {row["task_id"]: row for row in data["tasks"]}


def task_base_image(task: Path) -> str:
    """Read the actual thin Dockerfile default, including its published digest."""
    text = (task / "environment/Dockerfile").read_text()
    values = re.findall(r"(?m)^ARG ALW_BASE_IMAGE=([^\s]+)\s*$", text)
    if len(values) != 1 or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/@+-]*", values[0]):
        raise ValueError("Task Dockerfile must declare one literal ALW_BASE_IMAGE default")
    from_values = [value.strip() for value in re.findall(r"(?im)^[ \t]*FROM[ \t]+([^\r\n]*)$", text)]
    if from_values != ["${ALW_BASE_IMAGE}"]:
        raise ValueError("Task Dockerfile must have exactly one active FROM ${ALW_BASE_IMAGE}")
    return values[0]


def copy_submission(source: Path, target: Path) -> None:
    """Copy formal artifacts without following links; missing artifacts are graded."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Submission must be a regular directory")
    if not hasattr(os, "O_NOFOLLOW") or not hasattr(os, "O_DIRECTORY"):
        raise ValueError("Submission snapshots require a Linux filesystem interface")

    def identity(value):
        return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns)

    def copy_file(directory_fd, name, destination, expected):
        flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
        with os.fdopen(os.open(name, flags, dir_fd=directory_fd), "rb") as handle:
            before = os.fstat(handle.fileno())
            if not stat.S_ISREG(before.st_mode):
                raise ValueError("Submission contains a nonregular file")
            if identity(before) != identity(expected):
                raise ValueError("Submission file changed before it was opened")
            with destination.open("xb") as output:
                shutil.copyfileobj(handle, output)
            after = os.fstat(handle.fileno())
            current = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if identity(before) != identity(after) or identity(after) != identity(current):
                raise ValueError("Submission changed while being copied")

    def copy_directory(directory_fd, destination):
        before = os.fstat(directory_fd)
        destination.mkdir()
        for name in sorted(os.listdir(directory_fd)):
            entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            if stat.S_ISDIR(entry.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory_fd)
                try:
                    if identity(entry) != identity(os.fstat(child)):
                        raise ValueError("Submission directory changed before it was opened")
                    copy_directory(child, destination / name)
                    if identity(os.fstat(child)) != identity(os.stat(
                            name, dir_fd=directory_fd, follow_symlinks=False)):
                        raise ValueError("Submission directory changed while being copied")
                finally:
                    os.close(child)
            elif stat.S_ISREG(entry.st_mode):
                copy_file(directory_fd, name, destination / name, entry)
            else:
                raise ValueError("Submission contains a link or nonregular file")
        if identity(before) != identity(os.fstat(directory_fd)):
            raise ValueError("Submission directory changed while being copied")

    directory_fd = os.open(source, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        target.mkdir()
        for name in ("layout.gds", "src", "README.md"):
            try:
                entry = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
            except FileNotFoundError:
                continue  # The verifier records absent/incomplete submissions.
            if name == "src" and stat.S_ISDIR(entry.st_mode):
                child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=directory_fd)
                try:
                    if identity(entry) != identity(os.fstat(child)):
                        raise ValueError("Submission directory changed before it was opened")
                    copy_directory(child, target / name)
                    if identity(os.fstat(child)) != identity(os.stat(
                            name, dir_fd=directory_fd, follow_symlinks=False)):
                        raise ValueError("Submission directory changed while being copied")
                finally:
                    os.close(child)
            elif name != "src" and stat.S_ISREG(entry.st_mode):
                copy_file(directory_fd, name, target / name, entry)
            else:
                raise ValueError("Submission contains a link, nonregular file, or invalid artifact type")
    finally:
        os.close(directory_fd)


def valid_metrics(metrics: dict) -> None:
    """Do not turn malformed or interrupted execution evidence into a low score."""
    if not isinstance(metrics, dict):
        raise ValueError("Verifier metrics must be an object")
    if (metrics.get("score_valid") is not True
            or metrics.get("evaluation_error") is not False
            or metrics.get("pipeline_completed") is not True):
        raise ValueError("Verifier did not produce valid terminal scoring evidence")
    score = metrics.get("score")
    if type(score) not in (int, float) or not math.isfinite(score) or not 0 <= score <= 1:
        raise ValueError("Verifier score must be finite and in [0, 1]")
    if type(metrics.get("design_passed")) is not bool:
        raise ValueError("Verifier design_passed must be a Boolean")
    if ("score_is_lower_bound" in metrics
            and type(metrics["score_is_lower_bound"]) is not bool):
        raise ValueError("Verifier score_is_lower_bound must be a Boolean")


def verify(args) -> int:
    root = repository_root(args.repository)
    if args.task not in task_rows(root):
        raise ValueError("Task is not in the frozen paper-v1 release")
    if (type(args.cpus) not in (int, float) or not math.isfinite(args.cpus)
            or args.cpus <= 0 or int(args.cpus) != args.cpus):
        raise ValueError("CPUs must be a positive integer")
    if not re.fullmatch(r"[1-9][0-9]*(?:[mMgG])", args.memory):
        raise ValueError("Memory must use a positive integer with m or g suffix")
    if shutil.which("docker") is None:
        raise ValueError("Docker CLI and a working Docker service are required")
    source = Path(args.submission).expanduser().absolute()
    if source.is_symlink() or not source.is_dir():
        raise ValueError("Submission must be a regular directory")
    source = source.resolve(strict=True)
    out = Path(args.out).expanduser().absolute()
    if out.exists() or out.is_symlink():
        raise ValueError("Output directory must be new")
    out = out.resolve()
    if out == source or source in out.parents:
        raise ValueError("Output directory must be outside the submission")
    task = root / "tasks" / args.task
    config = tomllib.loads((task / "task.toml").read_text())
    base_image = args.base_image or task_base_image(task)
    out.mkdir(parents=True)
    run_id = "alw-verify-" + uuid.uuid4().hex[:16]
    image = "local/analoglayoutworld-task:" + run_id
    owner_label = "org.analoglayoutworld.run"
    container_id = None
    create_attempted = False
    build_attempted = False
    started = time.monotonic()
    outcome = {"protocol": "paper-v1", "task_id": args.task,
               "base_image": base_image,
               "cpus": int(args.cpus), "memory": args.memory,
               "status": "error", "verifier_returncode": None,
               "cleanup_complete": False, "container_name": run_id}
    runtime_errors = []
    cleanup_errors = []

    def command(argv, name, timeout=180, *, check=True):
        with (out / name).open("w") as log:
            proc = subprocess.run(["docker", *argv], stdin=subprocess.DEVNULL,
                                  stdout=log, stderr=subprocess.STDOUT, timeout=timeout)
        if check and proc.returncode:
            raise RuntimeError(f"Docker operation failed; see {name}")
        return proc.returncode

    def inspect_owned(kind: str, name: str, log_name: str):
        """Inspect only this run's unique reference; return owned, absent or unknown."""
        try:
            proc = subprocess.run([
                "docker", kind, "inspect", "--format",
                '{{.Id}}|{{index .Config.Labels "' + owner_label + '"}}', name,
            ], text=True, capture_output=True, timeout=30)
        except (OSError, subprocess.TimeoutExpired) as error:
            (out / log_name).write_text(type(error).__name__ + "\n")
            return "unknown", None
        stdout, stderr = proc.stdout or "", proc.stderr or ""
        (out / log_name).write_text(stdout + stderr)
        if proc.returncode:
            # A daemon/connection failure is not evidence that a resource is absent.
            missing = (f"No such {kind}: {name}", f"No such object: {name}")
            if any(value in stderr for value in missing):
                return "absent", None
            return "unknown", None
        fields = stdout.strip().split("|")
        if (len(fields) != 2 or not re.fullmatch(r"(?:sha256:)?[0-9a-f]{64}", fields[0])
                or fields[1] != run_id):
            return "unknown", None
        return "owned", fields[0]

    def collect_and_remove_container():
        nonlocal container_id
        state, identity = inspect_owned("container", container_id or run_id,
                                        "inspect-container-before-stop.log")
        if state == "absent":
            if container_id:
                runtime_errors.append("Own container disappeared before report collection")
            return
        if state != "owned":
            cleanup_errors.append("Could not confirm own container identity; no stop/remove attempted")
            return
        container_id = identity
        # Use immutable ID after checking the label, so a reused name is never stopped.
        try:
            if command(["stop", "--time", "10", container_id], "stop.log", 45, check=False):
                runtime_errors.append("Could not stop own container; see stop.log")
        except (OSError, subprocess.TimeoutExpired) as error:
            runtime_errors.append("Could not stop own container: " + type(error).__name__)
        # Collection is attempted even if exec or stop failed, before removing evidence.
        try:
            if command(["cp", container_id + ":/logs/verifier", str(out / "verifier")],
                       "collect.log", check=False):
                runtime_errors.append("Could not collect verifier reports; see collect.log")
        except (OSError, subprocess.TimeoutExpired) as error:
            runtime_errors.append("Could not collect verifier reports: " + type(error).__name__)
        state, identity = inspect_owned("container", container_id,
                                        "inspect-container-before-remove.log")
        if state == "absent":
            return
        if state != "owned":
            cleanup_errors.append("Could not reconfirm own container identity for removal")
            return
        try:
            if command(["rm", "--force", identity], "cleanup-container.log", 60, check=False):
                cleanup_errors.append("Could not remove own container")
        except (OSError, subprocess.TimeoutExpired) as error:
            cleanup_errors.append("Could not remove own container: " + type(error).__name__)

    def remove_task_image():
        state, identity = inspect_owned("image", image, "inspect-image-before-remove.log")
        if state == "absent":
            return
        if state != "owned":
            cleanup_errors.append("Could not confirm own task image identity; no removal attempted")
            return
        outcome["task_image_id"] = identity
        try:
            if command(["image", "rm", "--no-prune", image], "cleanup-image.log", 60, check=False):
                cleanup_errors.append("Could not remove own task image")
        except (OSError, subprocess.TimeoutExpired) as error:
            cleanup_errors.append("Could not remove own task image: " + type(error).__name__)

    try:
        with tempfile.TemporaryDirectory(prefix="alw-submission-") as temporary:
            fixture = Path(temporary) / "submission"
            copy_submission(source, fixture)
            command(["info", "--format", "{{.ServerVersion}}"], "docker-info.log", 30)
            build = ["build", "--file", str(task / "environment/Dockerfile"), "--tag", image,
                     "--label", owner_label + "=" + run_id]
            if args.base_image:
                build += ["--build-arg", "ALW_BASE_IMAGE=" + args.base_image]
            build_attempted = True
            command([*build, str(task / "environment")], "build.log", 900)
            create = ["create", "--name", run_id, "--network", "none", "--cpus", str(args.cpus),
                      "--memory", args.memory, "--label", owner_label + "=" + run_id]
            for key, value in config["environment"].get("env", {}).items():
                create += ["--env", key + "=" + str(value)]
            # A timeout can happen after the daemon has created the resource.
            create_attempted = True
            command([*create, image], "create.log")
            state, container_id = inspect_owned("container", run_id, "inspect-created-container.log")
            if state != "owned":
                raise RuntimeError("Could not confirm the created container's identity")
            command(["start", container_id], "start.log")
            command(["cp", str(task / "tests") + "/.", container_id + ":/tests"], "deliver-tests.log")
            command(["cp", str(fixture) + "/.", container_id + ":/alb-workspace/submission"], "deliver-submission.log")
            env = {"ALB_VERIFIER_CPUS": str(int(args.cpus)), "ALB_VERIFIER_NO_TIMEOUT": "1",
                   "ALB_VERIFIER_BUDGET_SEC": "3300", "ALB_VERIFIER_RECOVER_COMPLETED": "1",
                   "ALB_VERIFIER_SOLVER_POLICY": "auto"}
            execute = ["exec"]
            for key, value in env.items():
                execute += ["--env", key + "=" + value]
            try:
                rc = command([*execute, container_id, "bash", "/tests/test.sh"],
                             "verifier.log", 3600, check=False)
            except subprocess.TimeoutExpired:
                rc = 124
                runtime_errors.append("Outer verifier time limit reached")
            outcome["verifier_returncode"] = rc
            if rc not in (0, 1):
                runtime_errors.append(f"Verifier execution returned {rc}; see verifier.log")
    except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired) as error:
        runtime_errors.append(str(error))
    except BaseException:
        # Preserve the external interruption while still attempting scoped cleanup.
        runtime_errors.append("Execution interrupted before a normal verifier result")
        raise
    finally:
        if create_attempted:
            collect_and_remove_container()
        if build_attempted:
            remove_task_image()
        metrics_path = out / "verifier/evaluation/metrics.json"
        if metrics_path.is_file():
            outcome["metrics"] = "verifier/evaluation/metrics.json"
        if not runtime_errors and outcome["verifier_returncode"] in (0, 1):
            try:
                metrics = json.loads(metrics_path.read_text())
                valid_metrics(metrics)
                outcome.update(status="evaluated", score=metrics["score"],
                               design_passed=metrics["design_passed"],
                               score_is_lower_bound=metrics.get("score_is_lower_bound", False))
            except (OSError, ValueError) as error:
                runtime_errors.append(str(error))
        if runtime_errors:
            outcome["reason"] = "; ".join(runtime_errors)
        outcome["cleanup_complete"] = not cleanup_errors
        if cleanup_errors:
            outcome["cleanup_errors"] = cleanup_errors
        outcome["elapsed_seconds"] = round(time.monotonic() - started, 3)
        (out / "summary.json").write_text(json.dumps(outcome, indent=2, allow_nan=False) + "\n")
    print(json.dumps(outcome, indent=2, allow_nan=False))
    if outcome["status"] != "evaluated" or cleanup_errors:
        return 2
    return 0 if outcome["design_passed"] else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", help="Release checkout (default: source checkout)")
    subs = parser.add_subparsers(dest="command", required=True)
    p = subs.add_parser("list", help="List the frozen 40 tasks")
    p = subs.add_parser("verify", help="Evaluate an existing formal submission using Docker")
    p.add_argument("--task", required=True)
    p.add_argument("--submission", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--cpus", type=int, default=6)
    p.add_argument("--memory", default="32g")
    p.add_argument("--base-image", help="Override the default EDA image for development")
    args = parser.parse_args(argv)
    try:
        if args.command == "list":
            for task_id, row in task_rows(repository_root(args.repository)).items():
                print(f'{row["number"]:02d}\t{task_id}\t{row["title"]}')
            return 0
        from eda.runtime import cleanup_on_termination
        with cleanup_on_termination():
            return verify(args)
    except (OSError, ValueError, RuntimeError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

