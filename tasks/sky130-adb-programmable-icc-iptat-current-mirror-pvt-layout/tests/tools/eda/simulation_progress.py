"""Private native-run receipts for interrupted post-simulation collection.

Only the native runner writes these receipts.  A waveform or a successful-looking
log is not a substitute for the runner's completed command/exit status.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
from threading import Lock
import time


def atomic_json(path: Path, value: dict) -> None:
    """Replace a progress document only after its finite JSON is complete."""
    path = Path(path)
    text = json.dumps(value, indent=2, allow_nan=False) + '\n'
    temporary = path.with_name(path.name + '.new')
    temporary.write_text(text)
    temporary.replace(path)


class NativeExecutionReceipts:
    """Record native results before ordered consumers or solver rechecks wait.

    Calling this object forwards the original arguments to ``runner`` unchanged.
    ``successful`` returns only an immutable snapshot of a certified successful
    execution from this instance; it never reads or infers success from files
    left by another run. Failed commands are still retained for diagnostics.
    """

    def __init__(self, runner):
        self.runner = runner
        self._receipts = {}
        self._lock = Lock()

    @staticmethod
    def _directory(options_or_out) -> Path:
        value = options_or_out['out'] if isinstance(options_or_out, dict) else options_or_out
        return Path(value).resolve()

    def __call__(self, **options):
        execution = self.runner(**options)
        # The caller may augment or invalidate its result during measurement.
        # Capture the native command's own result before returning that object.
        snapshot = deepcopy(execution)
        completed_at = time.monotonic()
        directory = self._directory(options)
        deck = Path(options['deck'])
        receipt = {
            'schema_version': 1,
            'deck': str(deck.resolve()),
            'deck_sha256': hashlib.sha256(deck.read_bytes()).hexdigest(),
            'completed_at_monotonic': completed_at,
            'execution': snapshot,
        }
        initialization = directory / '.spiceinit'
        if initialization.is_file():
            receipt['spiceinit_sha256'] = hashlib.sha256(initialization.read_bytes()).hexdigest()
        with self._lock:
            atomic_json(directory / 'native_execution.json', receipt)
            self._receipts[directory] = receipt
        return execution

    def successful(self, options_or_out, *, before: float | None = None) -> dict | None:
        """Return certified native success, optionally completed by a cutoff.

        ``before`` uses the same monotonic clock as completion receipts. This
        prevents cleanup after an expired budget from admitting later results.
        """
        directory = self._directory(options_or_out)
        with self._lock:
            receipt = self._receipts.get(directory)
            if receipt is None:
                return None
            if before is not None and not receipt['completed_at_monotonic'] <= before:
                return None
            execution = receipt['execution']
            if not isinstance(execution, dict):
                return None
            command = execution.get('command')
            if (execution.get('status') != 'completed'
                    or not isinstance(command, dict)
                    or command.get('status') != 'completed'
                    or type(command.get('returncode')) is not int
                    or command['returncode'] != 0):
                return None
            return deepcopy(execution)
