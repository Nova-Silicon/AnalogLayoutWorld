#!/usr/bin/env python3
"""Create a standard Harbor 0.24 job for one or all paper-v1 tasks."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def job_config(task: str, agent: str, model: str | None, concurrency: int,
               name: str, jobs_dir: Path, agent_version: str | None = None,
               attempts: int = 3) -> dict:
    manifest = json.loads((ROOT / "configs/paper-v1/tasks.json").read_text())
    task_ids = [row["task_id"] for row in manifest["tasks"]]
    if task != "all" and task not in task_ids:
        raise ValueError("Task is not part of the paper-v1 release")
    if concurrency < 1:
        raise ValueError("Concurrency must be at least one")
    if type(attempts) is not int or attempts < 1:
        raise ValueError("Attempts must be a positive integer")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", name):
        raise ValueError("Use a simple, new job name")
    if agent not in ("nop", "oracle") and not model:
        raise ValueError("Specify --model for a model-based agent")
    selected = task_ids if task == "all" else [task]
    configured_agent = {"name": agent}
    if model:
        configured_agent["model_name"] = model
    if agent_version:
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9.+_-]*", agent_version):
            raise ValueError("Use an explicit harness release version")
        configured_agent["kwargs"] = {"version": agent_version}
    return {
        "job_name": name, "jobs_dir": str(jobs_dir), "n_attempts": attempts,
        "n_concurrent_trials": concurrency, "retry": {"max_retries": 0},
        "environment": {"type": "docker", "delete": True},
        "verifier": {"env": {"ALB_VERIFIER_NO_TIMEOUT": "1",
            "ALB_VERIFIER_BUDGET_SEC": "3300", "ALB_VERIFIER_RECOVER_COMPLETED": "1",
            "ALB_VERIFIER_SOLVER_POLICY": "auto"}},
        "agents": [configured_agent],
        "tasks": [{"path": str(ROOT / "tasks" / task_id)} for task_id in selected],
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--task", required=True, help="Stable task id, or all")
    parser.add_argument("--agent", default="opencode", help="A native Harbor agent name")
    parser.add_argument("--model", help="Model identifier accepted by the selected agent")
    parser.add_argument("--agent-version", help="Pin the selected installed harness release")
    parser.add_argument("--attempts", type=int, default=3,
                        help="Independent attempts per task (default: 3; use 1 for a diagnostic)")
    parser.add_argument("--concurrency", type=int, default=1)
    parser.add_argument("--job-name", default="paper-v1-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
    parser.add_argument("--jobs-dir", type=Path, default=ROOT / "jobs")
    parser.add_argument("--dry-run", action="store_true", help="Write and print the nonsecret job config only")
    args = parser.parse_args(argv)
    try:
        jobs = args.jobs_dir.expanduser().resolve()
        config = job_config(args.task, args.agent, args.model, args.concurrency, args.job_name,
                            jobs, args.agent_version, attempts=args.attempts)
        if (jobs / args.job_name).exists():
            raise ValueError("Job directory already exists; choose a new job name")
        jobs.mkdir(parents=True, exist_ok=True)
        path = jobs / (args.job_name + ".json")
        with path.open("x") as handle:
            json.dump(config, handle, indent=2)
            handle.write("\n")
        if args.dry_run:
            print(json.dumps(config, indent=2))
            return 0
        if shutil.which("harbor") is None:
            raise ValueError("Install the pinned Harbor extra: pip install -e '.[harbor]'")
        print("Job config:", path)
        return subprocess.run(["harbor", "run", "--config", str(path)], check=False,
                              env=dict(os.environ, HARBOR_TELEMETRY="0")).returncode
    except (OSError, ValueError) as error:
        parser.exit(2, str(error) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())

