"""Portable DSH contracts and durable log semantics; no model or Docker calls.

Set ALW_DSH_BUNDLE and ALW_DSH_NODE to additionally inspect real
0.2.1-rc.5 profile composition offline. That opt-in test never runs an Agent.
"""
from __future__ import annotations

import asyncio
from copy import deepcopy
import hashlib
from importlib.util import find_spec
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from analoglayoutworld_agents.dsh_logs import read_dsh_sessions

HARBOR_AVAILABLE = find_spec("harbor") is not None
if HARBOR_AVAILABLE:
    from harbor.environments.base import ExecResult
    from harbor.models.agent.context import AgentContext
    from harbor.models.trajectories.trajectory import Trajectory
    from harbor.agents.installed.base import NonZeroAgentExitCodeError
    from analoglayoutworld_agents.deepseek_harness import (
        DeepSeekHarnessAgent, DeepSeekHarnessOptions, ENTRYPOINT, PACKAGE, VERSION,
        REMOTE_CONFIG, native_patch, validate_dsh_bundle,
    )
    from analoglayoutworld_agents.dsh_logs import populate_dsh_context


def usage(uncached=10, output=4, read=2, write=1):
    return {"inputTokens": uncached, "outputTokens": output,
            "cacheReadTokens": read, "cacheWriteTokens": write, "reasoningTokens": 1,
            "totalTokens": uncached + read + write + output}


def event(seq, kind, **data):
    return {"seq": seq, "time": 1000 + seq, "type": kind, "data": data}


def message(seq, sample=None, *, turn=1, step=1, content=None):
    row = event(seq, "assistant/message", turn=turn, step=step,
                message={"id": f"message-{seq}", "role": "assistant",
                         "source": {"kind": "model", "provider": "test", "model": "model"},
                         "content": content or [{"type": "text", "text": "DONE"}]})
    if sample is not None:
        row["data"]["usage"] = sample
        row["data"]["stream"] = [{"type": "chunk", "chunk": {"type": "usage", "usage": sample}}]
    return row


def write_session(root, identity, rows, **header):
    path = root / "deepseek-harness/home/sessions/project" / identity / "session.v4.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    header = {"type": "session", "version": 4, "id": identity, "createdAt": 1000,
              "isSeeded": False, "delegationDepth": 0, **header}
    path.write_text("".join(json.dumps(row) + "\n" for row in [header, *rows]))
    return path


class CompletionReaderTests(unittest.TestCase):
    def test_success_requires_last_native_turn_completion_not_cli_exit_or_old_turn(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            rows = [event(0, "turn/start", turn=1),
                    event(1, "turn/end", turn=1, reason={"kind": "completed"}),
                    event(2, "turn/start", turn=2)]
            write_session(root, "root", rows)
            self.assertFalse(read_dsh_sessions(root)["completion"]["completed"])
            write_session(root, "root", rows + [event(3, "turn/end", turn=2, reason={"kind": "error"})])
            self.assertEqual(read_dsh_sessions(root)["completion"]["reason"], "error")

    def test_completion_command_is_stdlib_only_and_rejects_truncated_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = write_session(root, "root", [event(0, "turn/start", turn=1),
                event(1, "turn/end", turn=1, reason={"kind": "completed"})])
            argv = [sys.executable, "-I", "-S", str(ROOT / "src/analoglayoutworld_agents/dsh_logs.py"),
                    "--check-completed", "--logs-dir", str(root / "deepseek-harness")]
            done = subprocess.run(argv, capture_output=True, text=True, check=False)
            self.assertEqual(done.returncode, 0, done.stderr)
            with path.open("ab") as stream:
                stream.write(b'{"seq": 2, "text": "\xe4\xb8')
            torn = subprocess.run(argv, capture_output=True, text=True, check=False)
            self.assertEqual(torn.returncode, 1)
            self.assertTrue(json.loads(torn.stdout)["completion"]["log_integrity_uncertain"])

    def test_ambiguous_roots_are_not_guessed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for identity in ["one", "two"]:
                write_session(root, identity, [event(0, "turn/start", turn=1),
                    event(1, "turn/end", turn=1, reason={"kind": "completed"})])
            self.assertIsNone(read_dsh_sessions(root)["root_session_id"])
            stdout = root / "deepseek-harness/stdout.log"
            stdout.write_text(json.dumps({"type": "session", "sessionId": "two"}) + "\n")
            self.assertEqual(read_dsh_sessions(root)["root_session_id"], "two")


@unittest.skipUnless(HARBOR_AVAILABLE, "Install the optional Harbor dependency")
class AdapterTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="dsh paths with spaces ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.bundle = self.root / "bundle"
        cli = self.bundle / ENTRYPOINT
        cli.parent.mkdir(parents=True)
        cli.write_text("// synthetic payload; never executed\n")
        (cli.parent.parent / "package.json").write_text(json.dumps({"name": PACKAGE, "version": VERSION}))
        self.logs = self.root / "logs"
        self.pin_manifest()

    def pin_manifest(self):
        files = {}
        for path in self.bundle.rglob("*"):
            relative = path.relative_to(self.bundle).as_posix()
            if relative == "manifest.json":
                continue
            if path.is_symlink():
                files[relative] = {"symlink": str(path.readlink())}
            elif path.is_file():
                files[relative] = {"sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "bytes": path.stat().st_size}
        manifest = {"schema_version": 1, "package": PACKAGE, "version": VERSION,
                    "entrypoint": ENTRYPOINT, "files": files}
        path = self.bundle / "manifest.json"
        path.write_text(json.dumps(manifest))
        self.pin = hashlib.sha256(path.read_bytes()).hexdigest()

    def parameters(self, **changes):
        return {"bundle_path": self.bundle, "manifest_sha256": self.pin,
                "max_output_tokens": 2048, **changes}

    def agent(self, **changes):
        return DeepSeekHarnessAgent(logs_dir=self.logs, model_name="provider/model",
            extra_env={"API_KEY": "test-only-value"}, **self.parameters(**changes))

    def test_bundle_preserves_pnpm_links_and_rejects_modified_or_escaping_payload(self):
        package = self.bundle / "node_modules/@deepseek-ai/dsh"
        physical = self.bundle / "node_modules/.pnpm/pinned/node_modules/@deepseek-ai/dsh"
        physical.parent.mkdir(parents=True)
        package.rename(physical)
        package.symlink_to("../.pnpm/pinned/node_modules/@deepseek-ai/dsh", target_is_directory=True)
        self.pin_manifest()
        validate_dsh_bundle(self.bundle, VERSION, self.pin)
        (physical / "lib/bin.js").write_text("modified\n")
        with self.assertRaisesRegex(ValueError, "file changed"):
            validate_dsh_bundle(self.bundle, VERSION, self.pin)
        self.pin_manifest()
        outside = self.root / "outside"
        outside.write_text("not part of the package")
        (self.bundle / "escape").symlink_to("../outside")
        self.pin_manifest()
        with self.assertRaisesRegex(ValueError, "escapes"):
            validate_dsh_bundle(self.bundle, VERSION, self.pin)

    def test_inventory_pin_rejects_extra_unmanifested_files(self):
        (self.bundle / "unexpected.cache").write_text("unexpected")
        with self.assertRaisesRegex(ValueError, "inventory"):
            validate_dsh_bundle(self.bundle, VERSION, self.pin)
        with self.assertRaisesRegex(ValueError, "pinned"):
            validate_dsh_bundle(self.bundle, VERSION, "0" * 64)

    def test_provider_routes_do_not_disguise_chat_completions_as_messages(self):
        direct = native_patch(DeepSeekHarnessOptions(**self.parameters(api_url="https://example.invalid/v1")), "model", "/sessions")
        direct = {r["id"]: r for r in direct}
        self.assertEqual(direct["agent-default-model"]["config"]["provider"], "deepseek-official")
        self.assertEqual(direct["llm-deepseek"]["config"]["apiKeyEnv"], "API_KEY")
        options = DeepSeekHarnessOptions(**self.parameters(provider="moonshotai-cn", api="openai-completions",
            api_url="https://api.moonshot.cn/v1", api_key_env="MOONSHOT_API_KEY", generate_titles=False, disable_web_tools=True))
        rows = {r["id"]: r for r in native_patch(options, "kimi-k2.6", "/sessions")}
        route = rows["llm-pi-ai"]["config"]["providers"]["moonshotai-cn"]
        self.assertEqual(route["api"], "openai-completions")
        self.assertEqual(route["models"][0]["maxTokens"], 2048)
        self.assertNotIn("thinking", route)
        self.assertNotIn("reasoning", route)
        self.assertNotIn("llm-deepseek", rows)
        self.assertNotIn("web-search-deepseek", rows)
        self.assertTrue(rows["session-title-llm"]["disabled"])
        self.assertTrue(rows["tool-web"]["disabled"])

    def test_reported_model_matches_native_override_and_default_auxiliary_calls_are_disabled(self):
        agent = self.agent(provider="moonshotai-cn", api_model="kimi-k2.6")
        info = agent.to_agent_info()
        self.assertEqual((info.model_info.name, info.model_info.provider), ("kimi-k2.6", "moonshotai-cn"))
        self.assertFalse(agent.options.generate_titles)
        self.assertTrue(agent.options.disable_web_tools)
        rows = {r["id"]: r for r in native_patch(agent.options, agent._model(), "/sessions")}
        self.assertTrue(rows["session-title-llm"]["disabled"])
        self.assertTrue(rows["tool-web"]["disabled"])

    def test_invalid_protocol_credentials_and_compaction_reserve_fail_before_setup(self):
        for changes in [{"api": "openai-completions"}, {"api_url": "https://user:password@example.invalid"},
                        {"api_url": "https://example.invalid?key=value"}, {"api_key_env": "KEY; echo bad"},
                        {"max_output_tokens": 65536}, {"api_model": "  "},
                        {"provider": "moonshotai-cn", "stream_idle_timeout_ms": 1000}]:
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                DeepSeekHarnessOptions(**self.parameters(**changes))
        options = DeepSeekHarnessOptions(**self.parameters(max_output_tokens=51808))
        rows = {r["id"]: r["config"] for r in native_patch(options, "model", "/sessions") if "config" in r}
        c = rows["compaction-basic"]
        self.assertEqual(min(options.context_tokens * c["thresholdRatio"],
            options.context_tokens - options.max_output_tokens - c["headroomTokens"]), 196000)

    async def test_standard_transfers_keep_instruction_and_key_out_of_patch_and_command(self):
        captured = {}
        async def upload(source, target):
            if target == REMOTE_CONFIG:
                captured["patch"] = (source / "eval.patch.yml").read_text()
                self.assertTrue((source / "dsh_logs.py").is_file())
        environment = SimpleNamespace(upload_dir=AsyncMock(side_effect=upload), upload_file=AsyncMock(),
            exec=AsyncMock(return_value=ExecResult(return_code=0)))
        agent = self.agent()
        await agent.setup(environment)
        self.assertEqual(environment.upload_dir.await_count, 2)
        self.assertNotIn("test-only-value", captured["patch"])
        self.assertEqual(environment.exec.await_args.kwargs["env"]["API_KEY"], "")
        identity = json.loads((self.logs / "deepseek-harness-runtime.json").read_text())
        self.assertEqual(identity["reasoning_effort_requested"], "max")
        instruction = 'Original task\nquotes: " \' $() `literal`\n'
        context = AgentContext()
        await agent.run(instruction, environment, context)
        self.assertEqual((self.logs / "instruction.txt").read_text(), instruction)
        argv = environment.exec.await_args.kwargs
        self.assertNotIn(instruction, argv["command"])
        self.assertNotIn("test-only-value", argv["command"])
        self.assertEqual(argv["env"]["API_KEY"], "test-only-value")
        self.assertIsNone(argv["timeout_sec"])
        self.assertTrue(context.is_empty(), "Wait for Harbor to download all logs before backfilling")

    async def test_cancellation_propagates_without_retry_or_extra_deadline(self):
        environment = SimpleNamespace(upload_dir=AsyncMock(), upload_file=AsyncMock(),
            exec=AsyncMock(return_value=ExecResult(return_code=0)))
        agent = self.agent()
        await agent.setup(environment)
        environment.exec.reset_mock()
        environment.exec.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await agent.run("task", environment, AgentContext())
        self.assertEqual(environment.exec.await_count, 1)
        self.assertIsNone(environment.exec.await_args.kwargs["timeout_sec"])

    async def test_nonzero_native_run_remains_an_error(self):
        environment = SimpleNamespace(upload_dir=AsyncMock(), upload_file=AsyncMock(),
            exec=AsyncMock(return_value=ExecResult(return_code=0)))
        agent = self.agent()
        await agent.setup(environment)
        environment.exec.return_value = ExecResult(return_code=1)
        with self.assertRaises(NonZeroAgentExitCodeError):
            await agent.run("task", environment, AgentContext())

    def test_retry_summary_and_committed_stream_usage_are_counted_once(self):
        rows = [event(0, "turn/start", turn=1),
            event(1, "assistant/attempt", turn=1, step=1, stream=[{"type": "chunk", "chunk": {"type": "usage", "usage": usage(5, 2, 1, 0)}}]),
            message(2, usage()),
            event(3, "compaction/summary", compactionId="summary", llmStreamCall=True, model="summary", usage=usage(3, 1, 0, 0)),
            event(4, "turn/end", turn=1, reason={"kind": "completed"})]
        path = write_session(self.logs, "root", rows)
        path.with_name("session.jsonl").write_bytes(path.read_bytes())
        context = AgentContext()
        audit = populate_dsh_context(self.logs, context, "model", VERSION)
        self.assertEqual((context.n_input_tokens, context.n_output_tokens, context.n_cache_tokens), (22, 7, 3))
        self.assertEqual(audit["attempts_and_summaries"], 3)
        self.assertTrue(audit["whole_run_totals_certified"])
        Trajectory.model_validate_json((self.logs / "trajectory.json").read_text())

    def test_post_timeout_hook_retains_atif_and_subtotals_without_certifying_whole_run(self):
        write_session(self.logs, "root", [event(0, "turn/start", turn=1), message(1, usage()),
            event(2, "step/start", turn=1, step=2)])
        context = AgentContext()
        self.agent().populate_context_post_run(context)
        self.assertIsNone(context.n_input_tokens)
        self.assertEqual(context.model_usage, {}, "Prevent Harbor from backfilling partial ATIF as a full total")
        audit = context.metadata["dsh_usage"]
        self.assertEqual(audit["reported_subtotals"]["input"], 13)
        self.assertEqual(audit["unsettled_model_steps"], 1)
        self.assertFalse(audit["whole_run_totals_certified"])
        self.assertTrue((self.logs / "trajectory.json").exists())

    def test_exact_native_pi_ai_total_proves_omitted_zero_cache_but_not_unknown_buckets(self):
        rows = [event(0, "turn/start", turn=1),
                message(1, {"inputTokens": 10, "outputTokens": 4, "totalTokens": 14}),
                event(2, "turn/end", turn=1, reason={"kind": "completed"})]
        rows[1]["data"]["message"]["source"]["model"] = "kimi-k2.6"
        write_session(self.logs, "root", rows)
        context = AgentContext()
        audit = populate_dsh_context(self.logs, context, "kimi-k2.6", VERSION)
        self.assertEqual((context.n_input_tokens, context.n_output_tokens, context.n_cache_tokens), (10, 4, 0))
        self.assertTrue(audit["whole_run_totals_certified"])
        rows[1]["data"]["usage"]["totalTokens"] = 16
        write_session(self.logs, "root", rows)
        audit = populate_dsh_context(self.logs, AgentContext(), "kimi-k2.6", VERSION)
        self.assertFalse(audit["whole_run_totals_certified"])
        self.assertIsNone(audit["model_reported_totals"]["kimi-k2.6"]["cache"])

    def test_tool_ledger_and_seeded_child_do_not_duplicate_calls_or_inherited_usage(self):
        call = {"type": "tool-call", "id": "call", "name": "bash", "arguments": '{"command":"true"}'}
        write_session(self.logs, "root", [event(0, "turn/start", turn=1), message(1, usage(), content=[call]),
            event(2, "tool/call", turn=1, step=1, callId="call", name="bash", arguments='{"command":"true"}'),
            event(3, "tool/result", turn=1, step=1, message={"toolCallId": "call", "content": [{"type": "text", "text": "ok"}]}),
            event(4, "turn/end", turn=1, reason={"kind": "completed"})])
        write_session(self.logs, "child", [message(0, usage(100)), event(1, "session/end-seed", inherited=True),
            event(2, "turn/start", turn=1), message(3, usage(6)),
            event(4, "turn/end", turn=1, reason={"kind": "completed"})], isSeeded=True, origin="subagent", delegationDepth=1)
        context = AgentContext()
        audit = populate_dsh_context(self.logs, context, "model", VERSION)
        trajectory = Trajectory.model_validate_json((self.logs / "trajectory.json").read_text())
        self.assertEqual(len(trajectory.steps[0].tool_calls), 1)
        self.assertEqual(len(trajectory.steps[0].observation.results), 1)
        self.assertEqual(context.n_input_tokens, 22)
        self.assertEqual(audit["diagnostics"]["inherited_events_skipped"], 2)
        self.assertEqual(len(trajectory.subagent_trajectories), 1)

    def test_unmetered_auxiliary_call_or_conflicting_event_keeps_usage_unknown(self):
        rows = [event(0, "turn/start", turn=1), message(1, usage()),
                event(2, "session/title-llm-request"), event(3, "turn/end", turn=1, reason={"kind": "completed"})]
        write_session(self.logs, "root", rows)
        context = AgentContext()
        audit = populate_dsh_context(self.logs, context, "model", VERSION)
        self.assertIsNone(context.n_input_tokens)
        self.assertEqual(audit["reported_subtotals"]["input"], 13)
        changed = deepcopy(rows[1]);changed["data"]["usage"] = usage(999)
        write_session(self.logs, "root", [rows[0], rows[1], changed, rows[-1]])
        audit = populate_dsh_context(self.logs, AgentContext(), "model", VERSION)
        self.assertFalse(audit["completion"]["completed"])


@unittest.skipUnless(HARBOR_AVAILABLE and os.environ.get("ALW_DSH_BUNDLE") and os.environ.get("ALW_DSH_NODE"),
                     "Opt in to local official DSH config composition with ALW_DSH_BUNDLE/NODE")
class NativeCompositionTests(unittest.TestCase):
    def test_official_headless_composes_deepseek_and_moonshot_routes_without_model_calls(self):
        import yaml
        class Loader(yaml.SafeLoader):
            pass
        Loader.add_constructor("tag:yaml.org,2002:js", lambda loader, node: loader.construct_scalar(node))
        bundle = Path(os.environ["ALW_DSH_BUNDLE"]).resolve()
        node = Path(os.environ["ALW_DSH_NODE"]).resolve()
        manifest = bundle / "manifest.json"
        before = hashlib.sha256(manifest.read_bytes()).hexdigest()
        validate_dsh_bundle(bundle, VERSION, before)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for provider, model in [("deepseek-official", "deepseek-flash"), ("moonshotai-cn", "kimi-k2.6")]:
                with self.subTest(provider=provider):
                    options = DeepSeekHarnessOptions(bundle_path=bundle, manifest_sha256=before,
                        provider=provider, max_output_tokens=2048, generate_titles=False, disable_web_tools=True)
                    patch = root / (provider + ".json")
                    patch.write_text(json.dumps(native_patch(options, model, str(root / "sessions"))))
                    environment = {"PATH": os.environ.get("PATH", ""), "DSH_HOME": str(root / "home"),
                                   "DSH_TELEMETRY_DISABLED": "1", "DSH_PERMISSION_MODE": "danger-full-access"}
                    completed = subprocess.run([str(node), str(bundle / ENTRYPOINT), "--profile", "headless",
                        "--patch", str(patch), "--dump-config"], env=environment, cwd=root,
                        text=True, capture_output=True, timeout=60, check=False)
                    self.assertEqual(completed.returncode, 0, completed.stderr)
                    composed = yaml.load(completed.stdout, Loader=Loader)
                    def find(value, identity):
                        if isinstance(value, dict):
                            if value.get("id") == identity:
                                return value
                            for nested in value.values():
                                found = find(nested, identity)
                                if found is not None:
                                    return found
                        elif isinstance(value, list):
                            for nested in value:
                                found = find(nested, identity)
                                if found is not None:
                                    return found
                    selected = find(composed, "agent-default-model")["config"]
                    self.assertEqual((selected["provider"], selected["model"]), (provider, model))
                    self.assertTrue(find(composed, "session-title-llm")["disabled"])
                    self.assertTrue(find(composed, "tool-web")["disabled"])
                    if provider == "moonshotai-cn":
                        route = find(composed, "llm-pi-ai")["config"]["providers"][provider]
                        self.assertEqual(route["models"][0]["maxTokens"], 2048)
                    else:
                        self.assertEqual(find(composed, "llm-deepseek")["config"]["maxTokens"], 2048)
        self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), before)


if __name__ == "__main__":
    unittest.main()
