# SPDX-License-Identifier: Apache-2.0
"""Project pinned DSH v4 session logs without replaying or executing them.

The durable session artifacts remain authoritative. This module deliberately
does not infer usage from text, stdout's truncated projection, or estimates.
Top-level imports are standard-library only so the completion reader can also
run inside the EDA worker before Harbor collects its logs.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any


def _integer(value: Any) -> bool:
    return type(value) is int and value >= 0


def _object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _completion(root: dict[str, Any] | None) -> dict[str, Any]:
    answer = {"completed": False, "reason": None, "turn": None}
    if root is None:
        return answer
    events = root["events"]
    starts = [e for e in events if e["type"] == "turn/start"]
    if not starts:
        return answer
    start = starts[-1]
    turn = start["data"].get("turn")
    answer["turn"] = turn
    ends = [e for e in events if e["type"] == "turn/end"
            and e["seq"] > start["seq"] and e["data"].get("turn") == turn]
    if not ends:
        return answer
    reason = ends[-1]["data"].get("reason")
    if not isinstance(reason, dict):
        return answer
    answer["reason"] = reason.get("kind")
    answer["completed"] = reason.get("kind") == "completed"
    if "error" in reason:
        answer["error"] = reason["error"]
    return answer


def read_dsh_sessions(logs_dir: Path | str, *, session_id: str | None = None) -> dict[str, Any]:
    """Read plain selected-version logs, retaining valid events before a torn tail.

    ``logs_dir`` is Harbor's collected agent directory, containing
    ``deepseek-harness/home/sessions``. ``session_id`` identifies the native
    root, rather than Harbor's run id. Without it, the native headless opening
    ``session`` event identifies the root, falling back to exactly one
    parentless non-child header. Ambiguous roots are not guessed.
    """
    logs_dir = Path(logs_dir)
    if logs_dir.name == "deepseek-harness" or (logs_dir / "home/sessions").is_dir():
        logs_dir = logs_dir.parent
    home = logs_dir / "deepseek-harness/home/sessions"
    diagnostics = {"malformed_lines": 0, "duplicate_events": 0,
                   "conflicting_events": 0, "unsupported_sessions": 0,
                   "unreadable_files": 0, "inherited_events_skipped": 0,
                   "duplicate_session_files": 0, "seed_cut_missing": 0,
                   "ambiguous_root": 0}
    sessions: dict[str, dict[str, Any]] = {}
    paths = sorted({*home.glob("**/session.v4.jsonl"), *home.glob("**/session.jsonl")})
    for path in paths:
        if path.is_symlink() or not path.resolve().is_relative_to(logs_dir.resolve()):
            diagnostics["unreadable_files"] += 1
            continue
        header = None
        events = {}
        conflicts = set()
        try:
            with path.open("rb") as stream:
                for raw in stream:
                    if not raw.strip():
                        continue
                    try:
                        record = json.loads(raw.decode("utf-8"))
                    except (ValueError, UnicodeDecodeError):
                        diagnostics["malformed_lines"] += 1
                        continue
                    if header is None:
                        if (not isinstance(record, dict) or record.get("type") != "session"
                                or record.get("version") != 4 or not isinstance(record.get("id"), str)
                                or not record["id"] or not isinstance(record.get("isSeeded"), bool)):
                            diagnostics["unsupported_sessions"] += 1
                            break
                        header = record
                        continue
                    if (not isinstance(record, dict) or not _integer(record.get("seq"))
                            or not isinstance(record.get("type"), str)
                            or not isinstance(record.get("data"), dict)):
                        diagnostics["malformed_lines"] += 1
                        continue
                    seq = record["seq"]
                    if seq in events:
                        if events[seq] == record:
                            diagnostics["duplicate_events"] += 1
                        else:
                            conflicts.add(seq)
                        continue
                    events[seq] = record
        except OSError:
            diagnostics["unreadable_files"] += 1
            continue
        if header is None:
            continue
        identity = header["id"]
        if identity in sessions:
            previous = sessions[identity]
            diagnostics["duplicate_session_files"] += 1
            if previous["header"] != header:
                previous["conflicted"] = True
                diagnostics["conflicting_events"] += 1
                continue
            previous["paths"].append(str(path))
            for seq, event in events.items():
                if seq in previous["events_by_seq"]:
                    if previous["events_by_seq"][seq] == event:
                        diagnostics["duplicate_events"] += 1
                    else:
                        conflicts.add(seq)
                else:
                    previous["events_by_seq"][seq] = event
            previous["conflicted"] |= bool(conflicts)
        else:
            sessions[identity] = {"id": identity, "header": header, "paths": [str(path)],
                                  "events_by_seq": events, "conflicted": bool(conflicts)}
        diagnostics["conflicting_events"] += len(conflicts)
    values = []
    for session in sessions.values():
        events = [e for _, e in sorted(session.pop("events_by_seq").items())]
        if session["conflicted"]:
            # An event identity with two meanings is not valid evidence for
            # accounting or for successful completion.
            events = []
        if session["header"]["isSeeded"]:
            cuts = [e["seq"] for e in events if e["type"] == "session/end-seed"
                    and e["data"].get("inherited") is True]
            if cuts:
                cut = max(cuts)
                diagnostics["inherited_events_skipped"] += sum(e["seq"] <= cut for e in events)
                events = [e for e in events if e["seq"] > cut]
            else:
                diagnostics["seed_cut_missing"] += 1
                events = []
                session["conflicted"] = True
        session["events"] = events
        values.append(session)
    roots = [s for s in values if s["header"].get("origin") != "subagent"
             and s["header"].get("delegationDepth", 0) == 0]
    stdout_ids = set()
    if session_id is None:
        stdout = logs_dir / "deepseek-harness/stdout.log"
        if stdout.is_file() and not stdout.is_symlink() and stdout.resolve().is_relative_to(logs_dir.resolve()):
            try:
                with stdout.open("rb") as stream:
                    for raw in stream:
                        try:
                            item = json.loads(raw.decode("utf-8"))
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if (isinstance(item, dict) and item.get("type") == "session"
                                and isinstance(item.get("sessionId"), str) and item["sessionId"]):
                            stdout_ids.add(item["sessionId"])
            except OSError:
                diagnostics["unreadable_files"] += 1
        if len(stdout_ids) == 1:
            session_id = next(iter(stdout_ids))
    if session_id is not None:
        root = next((s for s in roots if s["id"] == session_id), None)
    else:
        fallback = [s for s in roots if not s["header"].get("parentSession")]
        root = fallback[0] if len(fallback) == 1 and len(stdout_ids) < 2 else None
    if root is None and values:
        diagnostics["ambiguous_root"] += 1
    completion = _completion(root)
    if completion["completed"] and any(diagnostics[k] for k in (
        "malformed_lines", "conflicting_events", "unsupported_sessions", "unreadable_files", "seed_cut_missing")):
        completion = {**completion, "completed": False, "log_integrity_uncertain": True}
    return {"sessions": values, "root_session_id": root["id"] if root else None,
            "completion": completion, "diagnostics": diagnostics}


def _stream_usage(data: dict[str, Any]) -> dict[str, Any] | None:
    stream = data.get("stream")
    if not isinstance(stream, list):
        return None
    samples = [r["chunk"].get("usage") for r in stream
               if isinstance(r, dict) and r.get("type") == "chunk"
               and isinstance(r.get("chunk"), dict) and r["chunk"].get("type") == "usage"]
    return samples[-1] if samples and isinstance(samples[-1], dict) else None


def _usage(value: Any) -> dict[str, int | None] | None:
    if (not isinstance(value, dict) or not _integer(value.get("inputTokens"))
            or not _integer(value.get("outputTokens"))):
        return None
    for field in ("cacheReadTokens", "cacheWriteTokens", "reasoningTokens", "totalTokens"):
        if field in value and not _integer(value[field]):
            return None
    if value.get("reasoningTokens", 0) > value["outputTokens"]:
        return None
    known_input = value["inputTokens"] + value.get("cacheReadTokens", 0) + value.get("cacheWriteTokens", 0)
    prompt = None
    if "totalTokens" in value:
        prompt = value["totalTokens"] - value["outputTokens"]
        if prompt < known_input:
            return None
        if all(k in value for k in ("cacheReadTokens", "cacheWriteTokens")) and prompt != known_input:
            return None
    elif all(k in value for k in ("cacheReadTokens", "cacheWriteTokens")):
        prompt = known_input
    # Native pi-ai omits zero cache buckets. An exact authoritative total with
    # no residual input proves absent buckets are zero; a residual stays unknown.
    zero_residual = prompt is not None and prompt == known_input
    return {"input": prompt, "output": value["outputTokens"],
            "cache": value.get("cacheReadTokens", 0 if zero_residual else None),
            "uncached_input": value["inputTokens"],
            "cache_write": value.get("cacheWriteTokens", 0 if zero_residual else None),
            "reasoning": value.get("reasoningTokens")}


def _text(content: Any) -> tuple[str, str | None]:
    if isinstance(content, str):
        return content, None
    text, reasoning = [], []
    for block in content if isinstance(content, list) else []:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text":
            text.append(str(block.get("text", "")))
        elif block.get("type") == "reasoning":
            reasoning.append(str(block.get("text", "")))
        elif block.get("type") != "tool-call":
            text.append("[Native content block] " + json.dumps(block, ensure_ascii=False))
    return "\n".join(text), "\n".join(reasoning) or None


def _time(event: dict[str, Any]) -> str | None:
    value = event.get("time")
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return None
    try:
        return datetime.fromtimestamp(value / 1000, timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return None


def populate_dsh_context(logs_dir: Path | str, context: Any, model_name: str, version: str,
                         session_id: str | None = None) -> dict[str, Any]:
    """Backfill Harbor usage and ATIF from native owned events, never stdout.

    Missing attempts or unknown cache buckets remain explicit unknowns. The
    audit records reported subtotals separately from whole-run totals.
    """
    from harbor.models.agent.context import ModelUsage
    from harbor.models.trajectories.agent import Agent
    from harbor.models.trajectories.metrics import Metrics
    from harbor.models.trajectories.observation import Observation
    from harbor.models.trajectories.observation_result import ObservationResult
    from harbor.models.trajectories.step import Step
    from harbor.models.trajectories.tool_call import ToolCall
    from harbor.models.trajectories.trajectory import Trajectory

    logs_dir = Path(logs_dir)
    if logs_dir.name == "deepseek-harness" or (logs_dir / "home/sessions").is_dir():
        logs_dir = logs_dir.parent
    parsed = read_dsh_sessions(logs_dir, session_id=session_id)
    records = []
    trajectories = {}
    title_requests = 0
    search_requests = 0
    excluded_roots = 0
    unsettled_steps = 0
    unsettled_compactions = 0
    for session in parsed["sessions"]:
        if (parsed["root_session_id"] is not None and session["id"] != parsed["root_session_id"]
                and session["header"].get("origin") != "subagent"
                and session["header"].get("delegationDepth", 0) == 0):
            excluded_roots += 1
            continue
        model = model_name
        steps = []
        by_step = {}
        opened_steps, settled_steps, ended_steps = set(), set(), set()
        opened_compactions, ended_compactions = set(), set()
        for event in session["events"]:
            kind, data = event["type"], event["data"]
            native_step_key = (data.get("turn"), data.get("step"))
            if all(_integer(value) for value in native_step_key):
                if kind == "step/start":
                    opened_steps.add(native_step_key)
                elif kind == "step/end":
                    ended_steps.add(native_step_key)
                elif kind == "assistant/message":
                    settled_steps.add(native_step_key)
            compaction_id = data.get("compactionId")
            if isinstance(compaction_id, str):
                if kind == "compaction/start":
                    opened_compactions.add(compaction_id)
                elif kind == "compaction/end":
                    ended_compactions.add(compaction_id)
            if kind == "request/header":
                config = _object(_object(data.get("header")).get("config"))
                model = config.get("model") if isinstance(config.get("model"), str) else model
                continue
            if kind == "request/context":
                model = data.get("model") if isinstance(data.get("model"), str) else model
                continue
            if kind == "session/title-llm-request":
                title_requests += 1
                continue  # Native title records do not report the response usage.
            if kind == "web/deepseek-search-llm-request":
                search_requests += 1
                continue  # The search helper records request facts, not response usage.
            sample = None
            if kind in ("assistant/message", "assistant/attempt"):
                message_source = _object(_object(data.get("message")).get("source"))
                if isinstance(message_source.get("model"), str):
                    model = message_source["model"]
                raw_usage = data.get("usage") if kind == "assistant/message" else None
                sample = _usage(raw_usage if raw_usage is not None else _stream_usage(data))
                records.append({"session": session["id"], "seq": event["seq"], "model": model,
                                "kind": kind, "usage": sample})
            elif kind == "compaction/summary" and (data.get("llmStreamCall") is True or "usage" in data):
                sample = _usage(data.get("usage"))
                records.append({"session": session["id"], "seq": event["seq"],
                                "model": data.get("model") or model, "kind": kind, "usage": sample})
                continue
            if kind == "user/message":
                message, _ = _text(data.get("content"))
                steps.append(Step(step_id=len(steps) + 1, source="user", message=message,
                                  timestamp=_time(event), extra={"native_seq": event["seq"]}))
                continue
            if kind not in ("assistant/message", "assistant/attempt", "tool/call", "tool/result"):
                continue
            if kind == "tool/result" and event.get("surfaceOp") not in (None, "append"):
                continue  # A compaction's replacement is not another tool execution.
            native_step = (data.get("turn"), data.get("step"))
            if not all(_integer(value) for value in native_step):
                native_step = ("unidentified", event["seq"])
            if kind in ("assistant/message", "assistant/attempt"):
                message = _object(data.get("message"))
                text, reasoning = _text(message.get("content"))
                metrics = Metrics(prompt_tokens=sample["input"], completion_tokens=sample["output"],
                                  cached_tokens=sample["cache"]) if sample is not None else None
                step = Step(step_id=len(steps) + 1, source="agent", message=text,
                            reasoning_content=reasoning, model_name=model, timestamp=_time(event),
                            llm_call_count=1, metrics=metrics,
                            extra={"native_seq": event["seq"], "native_turn": data.get("turn"),
                                   "native_step": data.get("step"), "native_event": kind,
                                   "interrupted": data.get("interrupted", False)})
                if kind == "assistant/message":
                    calls = []
                    for block in message.get("content") or []:
                        if not isinstance(block, dict) or block.get("type") != "tool-call":
                            continue
                        if not isinstance(block.get("id"), str) or not isinstance(block.get("name"), str):
                            continue
                        arguments = block.get("arguments", "{}")
                        try:
                            arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                        except ValueError:
                            arguments = {"_native_arguments": arguments}
                        if not isinstance(arguments, dict):
                            arguments = {"_native_arguments": arguments}
                        calls.append(ToolCall(tool_call_id=block["id"], function_name=block["name"], arguments=arguments))
                    step.tool_calls = calls or None
                    by_step[native_step] = step
                steps.append(step)
                continue
            step = by_step.get(native_step)
            if step is None:
                step = Step(step_id=len(steps) + 1, source="agent", message="", llm_call_count=0,
                            extra={"native_event": kind, "native_seq": event["seq"], "unmatched": True})
                steps.append(step)
                by_step[native_step] = step
            if kind == "tool/call":
                call_id = data.get("callId")
                if not isinstance(call_id, str) or any(c.tool_call_id == call_id for c in step.tool_calls or []):
                    continue
                arguments = data.get("arguments", "{}")
                try:
                    arguments = json.loads(arguments) if isinstance(arguments, str) else arguments
                except ValueError:
                    arguments = {"_native_arguments": arguments}
                if not isinstance(arguments, dict):
                    arguments = {"_native_arguments": arguments}
                call = ToolCall(tool_call_id=call_id, function_name=str(data.get("name") or "unknown"), arguments=arguments)
                step.tool_calls = [*(step.tool_calls or []), call]
            else:
                message = _object(data.get("message"))
                text, _ = _text(message.get("content"))
                call_id = message.get("toolCallId")
                known = {c.tool_call_id for c in step.tool_calls or []}
                result = ObservationResult(source_call_id=call_id if call_id in known else None,
                                           content=text, extra={"native_seq": event["seq"],
                                                                "is_error": message.get("isError", False)})
                if step.observation is None:
                    step.observation = Observation(results=[])
                step.observation.results.append(result)
        unsettled_steps += len(opened_steps - settled_steps - ended_steps)
        unsettled_compactions += len(opened_compactions - ended_compactions)
        if steps:
            trajectories[session["id"]] = Trajectory(
                session_id=parsed["root_session_id"] or session["id"], trajectory_id=session["id"],
                agent=Agent(name="deepseek-harness", version=version, model_name=model_name), steps=steps,
                extra={"native_header": session["header"], "native_paths": session["paths"]},
                notes="Durable DSH v4 session logs are authoritative. ATIF projects committed messages, attempts and tool events; compact raw streams and other native diagnostics remain in JSONL.")
    invalid_logs = any(parsed["diagnostics"][key] for key in (
        "malformed_lines", "conflicting_events", "unsupported_sessions", "unreadable_files", "seed_cut_missing"))
    complete = (bool(records) and parsed["completion"]["completed"]
                and parsed["root_session_id"] is not None and not invalid_logs
                and title_requests == 0 and search_requests == 0
                and unsettled_steps == 0 and unsettled_compactions == 0)
    totals = {}
    grouped = defaultdict(list)
    for record in records:
        grouped[record["model"]].append(record["usage"])
    for model, samples in grouped.items():
        totals[model] = {field: sum(s[field] for s in samples) if all(s is not None and s[field] is not None for s in samples) else None
                         for field in ("input", "output", "cache")}
    for field, attr in (("input", "n_input_tokens"), ("output", "n_output_tokens"), ("cache", "n_cache_tokens")):
        values = [value[field] for value in totals.values()]
        setattr(context, attr, sum(values) if complete and all(x is not None for x in values) else None)
    totals_certified = complete and all(all(v is not None for v in value.values()) for value in totals.values())
    if totals_certified:
        context.model_usage = {model: ModelUsage(n_input_tokens=value["input"], n_output_tokens=value["output"],
                                                n_cache_tokens=value["cache"]) for model, value in totals.items()}
    else:
        # Harbor otherwise reconstructs model_usage from whatever ATIF steps
        # survived a timeout, mistaking known subtotals for a whole-run total.
        # No certified entries is distinct from an asserted zero-token model.
        context.model_usage = {}
    reported = {field: sum(r["usage"][field] for r in records if r["usage"] is not None and r["usage"][field] is not None)
                for field in ("input", "output", "cache")}
    audit = {"source": "native_dsh_v4_session_jsonl", "session_count": len(parsed["sessions"]),
             "root_session_id": parsed["root_session_id"], "completion": parsed["completion"],
             "diagnostics": parsed["diagnostics"], "attempts_and_summaries": len(records),
             "unselected_root_sessions_excluded": excluded_roots,
             "unsettled_model_steps": unsettled_steps, "unsettled_compactions": unsettled_compactions,
             "calls_without_valid_usage": sum(r["usage"] is None for r in records),
             "unmetered_title_requests": title_requests, "unmetered_search_requests": search_requests,
             "whole_run_totals_certified": totals_certified,
             "reported_subtotals": reported,
             "model_reported_totals": totals,
             "scope": "Owned v4 assistant attempts/messages and reported compaction calls across root and children; missing usage, corrupt logs and unmetered title/search requests prevent whole-run totals. Cache writes are input, reasoning is included in output."}
    context.metadata = {**(context.metadata or {}), "dsh_usage": audit}
    root = trajectories.get(parsed["root_session_id"])
    if root is not None:
        root.subagent_trajectories = [value for key, value in trajectories.items() if key != parsed["root_session_id"]] or None
        logs_dir.mkdir(parents=True, exist_ok=True)
        (logs_dir / "trajectory.json").write_text(json.dumps(root.to_json_dict(), ensure_ascii=False, indent=2) + "\n")
    return audit


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Check the selected DSH native session's durable completion marker.")
    parser.add_argument("--check-completed", action="store_true", required=True)
    parser.add_argument("--logs-dir", required=True, type=Path)
    parser.add_argument("--session-id")
    args = parser.parse_args()
    parsed = read_dsh_sessions(args.logs_dir, session_id=args.session_id)
    print(json.dumps({"root_session_id": parsed["root_session_id"],
                      "completion": parsed["completion"], "diagnostics": parsed["diagnostics"]}))
    return 0 if parsed["completion"]["completed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
