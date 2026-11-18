"""Allocate a declared verifier CPU budget between independent ngspice runs.

This module changes scheduling only. It does not set a wall-clock budget or
alter any circuit, model, stimulus, tolerance, or measurement.
"""
from __future__ import annotations

from dataclasses import dataclass
import math
import os
import re


def positive_integer(value: int, name: str) -> int:
    if type(value) is not int or value < 1:
        raise ValueError(f"{name} must be a positive integer")
    return value


def verifier_cpu_budget() -> int:
    """Use the caller's configured CPU budget, defaulting explicitly to 4.

    Harbor supplies ALB_VERIFIER_CPUS from its final requested task resources.
    Standalone callers can supply the same setting; without it, the default
    matches the tasks' declared four-CPU verifier budget. This is configuration,
    not hardware detection: cgroups, affinity and host CPU counts are not read.
    """
    raw = os.environ.get("ALB_VERIFIER_CPUS")
    if raw is not None:
        try:
            value = float(raw)
        except ValueError as exc:
            raise ValueError("ALB_VERIFIER_CPUS must be a positive integer") from exc
        if not math.isfinite(value) or not value.is_integer() or value < 1:
            raise ValueError("ALB_VERIFIER_CPUS must be a positive integer")
        return int(value)
    return 4


@dataclass(frozen=True)
class SimulationResources:
    workers: int
    threads_per_worker: int | None
    cpu_budget: int | None

    def record(self) -> dict:
        return {"simulation_workers": self.workers,
                "simulation_threads_per_worker": self.threads_per_worker,
                "simulation_cpu_budget": self.cpu_budget}


def simulation_resources(workers: int, case_count: int,
                         cpu_budget: int | None = None) -> SimulationResources:
    """Use no more runnable threads than the supplied CPU allocation.

    A process keeps its thread count for its lifetime. We therefore use a fixed
    per-process share for this group instead of increasing threads as other
    cases finish, which could oversubscribe still-running processes.
    """
    positive_integer(workers, "Simulation workers")
    positive_integer(case_count, "Simulation case count")
    active = min(workers, case_count)
    if cpu_budget is None:
        return SimulationResources(active, None, None)
    positive_integer(cpu_budget, "Simulation CPU budget")
    active = min(active, cpu_budget)
    return SimulationResources(active, cpu_budget // active, cpu_budget)


def thread_initialization(initialization: str, num_threads: int) -> str:
    """Replace existing num_threads assignments and retain unrelated commands."""
    positive_integer(num_threads, "ngspice thread count")
    rewritten, _ = configure_deck_threads(initialization, num_threads)
    return rewritten.rstrip("\n") + f"\nset num_threads={num_threads}\n"


def configure_deck_threads(source: str, num_threads: int) -> tuple[str, list[dict]]:
    """Override explicit native thread assignments in a staged trusted deck.

    A .control `set num_threads=1` runs after .spiceinit and would otherwise
    undo the allocation. Only values of this named execution option change;
    all other bytes, including additional set variables and comments, remain.
    Quoted strings mentioning num_threads are not interpreted as assignments.
    """
    positive_integer(num_threads, "ngspice thread count")
    token = re.compile(r'''"[^"\n]*"|'[^'\n]*'|[^\s=;]+|=|;''')
    output, changes = [], []
    for number, line in enumerate(source.splitlines(keepends=True), 1):
        command = re.match(r"^\s*set\b", line, re.I)
        if command is None:
            output.append(line)
            continue
        tokens = list(token.finditer(line, command.end()))
        substitutions = []
        for index, item in enumerate(tokens):
            if item[0] == ';':
                break
            if (item[0].lower() == 'num_threads' and index + 2 < len(tokens)
                    and tokens[index + 1][0] == '=' and tokens[index + 2][0] != ';'):
                value = tokens[index + 2]
                substitutions.append((value.start(), value.end()))
        rewritten = line
        for start, end in reversed(substitutions):
            rewritten = rewritten[:start] + str(num_threads) + rewritten[end:]
        if rewritten != line:
            changes.append({'line': number, 'before': line.rstrip('\r\n'),
                            'after': rewritten.rstrip('\r\n'),
                            'assignments': len(substitutions)})
        output.append(rewritten)
    return ''.join(output), changes
