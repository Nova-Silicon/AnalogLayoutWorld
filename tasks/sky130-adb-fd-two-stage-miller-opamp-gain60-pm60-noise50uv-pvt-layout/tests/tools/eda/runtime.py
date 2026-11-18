"""Fixed runtime manifests and task-local command execution.

Published tasks carry runtime.json next to the eda package in the verifier's
separate tools copy. The image manifest is the fallback for installed use.
Executable paths never come from environment variables or submission files. Output validation is not a security sandbox.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import math
import os
from pathlib import Path
import signal
import subprocess
import time

PROJECT = Path(__file__).resolve().parents[1]
MANIFEST = Path("/opt/analog-layout/runtime.json")
TASK_MANIFEST = PROJECT / "runtime.json"


@contextmanager
def cleanup_on_termination():
    """Let verifier SIGTERM unwind native-command cleanup before exiting.

    The outer command timeout first sends SIGTERM to the verifier's outer process
    group. Native tools have their own groups, so Python must unwind its active
    command/pool contexts to stop and reap them. Install this only at a CLI
    boundary on the main thread; normal library calls retain caller handlers.
    """
    previous = signal.getsignal(signal.SIGTERM)

    def terminate(signum, frame):
        # A repeated SIGTERM must not interrupt the first cleanup/wait sequence.
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        raise SystemExit(128 + signum)

    signal.signal(signal.SIGTERM, terminate)
    try:
        yield
    finally:
        signal.signal(signal.SIGTERM, previous)


def sha256(path: Path) -> str:
    with Path(path).open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


def _manifest() -> dict:
    """Use a trusted task copy or the installed image's fixed manifest."""
    source = TASK_MANIFEST if TASK_MANIFEST.is_file() else MANIFEST
    manifest = json.loads(source.read_text())
    if manifest.get("inherit_image_runtime") is True:
        # Native binaries are rebuilt from pinned sources. Their current hashes
        # belong to the installed image, not an earlier development image.
        installed = json.loads(MANIFEST.read_text())
        if installed.get("execution", {}).get("mode") != "image":
            raise ValueError("Installed runtime must use image execution mode")
        overrides = manifest.get("paths", {})
        if set(overrides) != {"model_lib"}:
            raise ValueError("Task runtime may override only the selected model library")
        allowed = {installed["paths"]["model_lib"], installed["paths"].get("model_lib_binned")}
        if overrides["model_lib"] not in allowed:
            raise ValueError("Task model library is not provided by this EDA image")
        installed["paths"] = {**installed["paths"], **overrides}
        installed["file_sha256"] = {**installed.get("file_sha256", {}),
                                    **manifest.get("file_sha256", {})}
        installed["execution"] = manifest["execution"]
        manifest = installed
    if manifest.get("execution", {}).get("mode") != "image":
        raise ValueError("The public runtime requires image execution mode")
    return manifest


def load_runtime() -> dict:
    """Resolve only explicit image paths from the trusted manifest."""
    manifest = _manifest()
    result = dict(manifest)
    for key, value in manifest["paths"].items():
        path = Path(value)
        if not path.is_absolute():
            raise ValueError(f"Image runtime path must be absolute: {key}")
        result[key] = str(path.resolve(strict=True))
    return result


def shared_output(path: Path) -> Path:
    """Validate workspace/report roots; keep the existing internal API name."""
    path = path.resolve()
    roots = [Path(value) for value in _manifest()["execution"].get("output_roots", [])]
    if not roots or any(not root.is_absolute() or root == Path("/") for root in roots):
        raise ValueError("Image runtime requires explicit absolute output roots")
    if not any(path.is_relative_to(root.resolve()) for root in roots):
        raise ValueError("EDA output is outside the configured workspace/report roots")
    return path


def work_env(out: Path) -> dict[str, str]:
    """Put scratch files in the validated output directory without changing HOME."""
    out = shared_output(out)
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1")
    for key, name in {"TMPDIR": "tmp", "XDG_CONFIG_HOME": "config",
                      "XDG_CACHE_HOME": "cache", "XDG_RUNTIME_DIR": "xdg-runtime",
                      "KLAYOUT_HOME": "klayout-home", "MPLCONFIGDIR": "matplotlib"}.items():
        directory = out / name
        directory.mkdir(parents=True, exist_ok=True)
        if key == "XDG_RUNTIME_DIR":
            directory.chmod(0o700)
        env[key] = str(directory)
    return env


def klayout_env(out: Path) -> dict[str, str]:
    """Use the image KLayout wrapper and its matching system libraries."""
    load_runtime()
    env = work_env(out)
    for key in ("PYTHONHOME", "PYTHONPATH", "LD_PRELOAD", "DISPLAY", "LD_LIBRARY_PATH",
                "QT_PLUGIN_PATH", "KLAYOUT_PYTHONHOME", "KLAYOUT_PYTHONPATH", "RUBYLIB"):
        env.pop(key, None)
    env["QT_QPA_PLATFORM"] = "offscreen"
    return env


def magic_env(out: Path) -> dict[str, str]:
    """Use the image's Magic and system Tcl libraries."""
    load_runtime()
    env = work_env(out)
    for key in ("LD_PRELOAD", "LD_LIBRARY_PATH", "TCL_LIBRARY", "TK_LIBRARY", "CAD_ROOT"):
        env.pop(key, None)
    return env


def run_command(argv: list[str], *, cwd: Path, env: dict, timeout: float,
                cancel_event=None) -> dict:
    """Run synchronously; timeout or cancellation kills and reaps the process group."""
    cwd = shared_output(Path(cwd))
    if not math.isfinite(timeout) or timeout <= 0:
        raise ValueError("Timeout must be positive and finite")
    # Explicit verifier policy; ordinary tool calls keep their declared timeout.
    command_timeout = None if os.environ.get("ALB_VERIFIER_NO_TIMEOUT") == "1" else timeout
    cwd.mkdir(parents=True, exist_ok=True)
    log_path = cwd / "command.log"
    started = time.monotonic()
    result = {"status": "error", "returncode": None, "log_path": str(log_path)}
    with log_path.open("w") as log:
        if cancel_event is not None and cancel_event.is_set():
            log.write("Command cancelled before launch.\n")
            result.update(status="cancelled", seconds=round(time.monotonic() - started, 3))
            return result
        try:
            process = subprocess.Popen(
                [str(arg) for arg in argv], cwd=cwd, env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
        except OSError as exc:
            log.write(str(exc) + "\n")
            result["error"] = str(exc)
        else:
            try:
                if cancel_event is None:
                    result["returncode"] = process.wait(timeout=command_timeout)
                    result["status"] = "completed"
                else:
                    deadline = None if command_timeout is None else started + command_timeout
                    while True:
                        if cancel_event.is_set():
                            try:
                                os.killpg(process.pid, signal.SIGKILL)
                            except ProcessLookupError:
                                pass
                            process.wait()
                            result["status"] = "cancelled"
                            break
                        remaining = None if deadline is None else deadline - time.monotonic()
                        if remaining is not None and remaining <= 0:
                            raise subprocess.TimeoutExpired(argv, timeout)
                        try:
                            wait_interval = 0.1 if remaining is None else min(remaining, 0.1)
                            result["returncode"] = process.wait(timeout=wait_interval)
                            result["status"] = "completed"
                            break
                        except subprocess.TimeoutExpired:
                            continue
            except BaseException as exc:
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.wait()
                if not isinstance(exc, subprocess.TimeoutExpired):
                    raise
                result["status"] = "timeout"
    result["seconds"] = round(time.monotonic() - started, 3)
    return result
