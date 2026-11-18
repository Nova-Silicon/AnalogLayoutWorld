# SPDX-License-Identifier: Apache-2.0
"""Portable Harbor integration for the unmodified official DSH headless CLI.

This is original project integration code, not a copy of the MIT-licensed DSH
core. Supply a complete, independently prepared npm bundle and its manifest
SHA256. Setup performs no installation or network access. Harbor owns the trial
deadline, cancellation, log download and subsequent verifier lifecycle.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import shlex
import stat
import tempfile
from typing import Literal
from urllib.parse import urlsplit

from pydantic import Field, model_validator

from harbor.agents.base import BaseAgent
from harbor.agents.capabilities import AgentCapabilities
from harbor.agents.installed.base import NonZeroAgentExitCodeError
from harbor.agents.options import AgentOptions
from harbor.environments.base import BaseEnvironment
from harbor.models.agent.context import AgentContext
from harbor.models.trial.result import AgentInfo, ModelInfo


PACKAGE = "@deepseek-ai/dsh"
VERSION = "0.2.1-rc.5"
ENTRYPOINT = "node_modules/@deepseek-ai/dsh/lib/bin.js"
REMOTE_BUNDLE = "/installed-agent/deepseek-harness"
REMOTE_CONFIG = "/installed-agent/deepseek-harness-config"


def sha256(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def validate_dsh_bundle(source: Path, version: str, manifest_sha256: str) -> dict:
    """Verify the complete local payload, including contained npm/pnpm links.

    A matching manifest is an integrity check against the caller's pin, not an
    independent signature or authorization to execute an untrusted npm package.
    """
    source = Path(source)
    path = source / "manifest.json"
    if source.is_symlink() or not source.is_dir() or path.is_symlink() or not path.is_file():
        raise ValueError("DSH bundle and manifest must be physical local paths")
    if sha256(path) != manifest_sha256:
        raise ValueError("DSH manifest differs from the pinned SHA256")
    manifest = json.loads(path.read_text())
    if not isinstance(manifest, dict) or (
        manifest.get("schema_version"), manifest.get("package"), manifest.get("version"),
        manifest.get("entrypoint"),
    ) != (1, PACKAGE, version, ENTRYPOINT):
        raise ValueError("DSH bundle identity does not match the configured release")
    files = manifest.get("files")
    actual = {p.relative_to(source).as_posix() for p in source.rglob("*")
              if not stat.S_ISDIR(p.lstat().st_mode) and p.relative_to(source).as_posix() != "manifest.json"}
    if not isinstance(files, dict) or actual != set(files):
        raise ValueError("DSH bundle inventory differs from the pinned payload")
    root = source.resolve()
    for name, entry in files.items():
        relative = PurePosixPath(name)
        if (not name or "\\" in name or relative.is_absolute() or ".." in relative.parts
                or relative.as_posix() != name or not isinstance(entry, dict)):
            raise ValueError("Invalid DSH bundle inventory entry")
        item = source / name
        if item.is_symlink():
            target = item.readlink()
            if (entry != {"symlink": str(target)} or target.is_absolute()
                    or not item.exists() or not item.resolve().is_relative_to(root)):
                raise ValueError(f"DSH runtime link escapes its payload: {name}")
        elif (not item.is_file() or set(entry) != {"sha256", "bytes"}
              or type(entry["bytes"]) is not int or entry["bytes"] < 0
              or item.stat().st_size != entry["bytes"] or sha256(item) != entry["sha256"]):
            raise ValueError(f"DSH runtime file changed: {name}")
    cli = (source / ENTRYPOINT).resolve()
    if (not cli.is_file() or not cli.is_relative_to(root)
            or cli.relative_to(root).as_posix() not in files):
        raise ValueError("DSH CLI entry point is not an inventoried runtime file")
    package = json.loads((source / "node_modules/@deepseek-ai/dsh/package.json").read_text())
    if (package.get("name"), package.get("version")) != (PACKAGE, version):
        raise ValueError("DSH installed package identity is inconsistent")
    return manifest


class DeepSeekHarnessOptions(AgentOptions):
    bundle_path: Path
    version: Literal["0.2.1-rc.5"] = VERSION
    manifest_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    provider: str = Field(default="deepseek-official", pattern=r"^[a-z][a-z0-9_-]*$")
    api_url: str | None = None
    api: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]*$")
    api_model: str | None = None
    api_key_env: str = "API_KEY"
    input_modalities: list[Literal["text", "image"]] = Field(default_factory=lambda: ["text"], min_length=1)
    max_output_tokens: int = Field(gt=0, strict=True)
    reasoning_effort: Literal["off", "minimal", "low", "medium", "high", "xhigh", "max"] | None = None
    context_tokens: int = Field(default=256000, gt=0, strict=True)
    compact_at_tokens: int = Field(default=196000, gt=0, strict=True)
    summary_tokens: int = Field(default=8192, gt=0, strict=True)
    headroom_tokens: int = Field(default=8192, ge=0, strict=True)
    stream_idle_timeout_ms: int | None = Field(default=None, gt=0, strict=True)
    generate_titles: bool = Field(default=False, strict=True)
    disable_web_tools: bool = Field(default=True, strict=True)
    node_path: str = "/opt/analog-layout/agent/bin/node"
    python_path: str = "/opt/analog-layout/python/bin/python3.12"
    workdir: str = "/alb-workspace"

    @model_validator(mode="after")
    def check_native_configuration(self):
        if self.api_url is not None:
            url = urlsplit(self.api_url)
            if (url.scheme not in {"http", "https"} or not url.netloc or url.username
                    or url.password or url.query or url.fragment):
                raise ValueError("api_url must be a credential-free HTTP(S) provider base URL")
        if self.provider == "deepseek-official":
            if self.api is not None:
                raise ValueError("The native DeepSeek provider uses Messages, not a selectable api transport")
            if self.reasoning_effort not in (None, "high", "max"):
                raise ValueError("The native DeepSeek provider supports high or max reasoning_effort")
        elif self.stream_idle_timeout_ms is not None:
            raise ValueError("stream_idle_timeout_ms is specific to the native DeepSeek provider")
        if not 0 < self.compact_at_tokens < self.context_tokens:
            raise ValueError("compact_at_tokens must be below context_tokens")
        if self.max_output_tokens + self.headroom_tokens > self.context_tokens - self.compact_at_tokens:
            raise ValueError("Output cap plus compaction reserve would lower the requested compression threshold")
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", self.api_key_env):
            raise ValueError("api_key_env must name an environment variable")
        if self.api_model is not None and not self.api_model.strip():
            raise ValueError("api_model must be a nonempty model identifier")
        if "text" not in self.input_modalities or len(set(self.input_modalities)) != len(self.input_modalities):
            raise ValueError("input_modalities must include text and contain no duplicates")
        return self


def native_patch(options: DeepSeekHarnessOptions, model: str, session_root: str) -> list[dict]:
    """Use official profile entries; do not replace DSH's loop or tools.

    deepseek-official selects the original Messages adapter. Other route names
    select the already-shipped pi-ai adapter and inherit that route's catalog
    compatibility defaults. Unknown routes need api, api_url and model metadata
    accepted by the fixed DSH release; native configuration errors remain visible.
    """
    patches = [{"id": "agent-default-model", "config": {"provider": options.provider, "model": model}}]
    if options.provider == "deepseek-official":
        config = {
            "apiKeyEnv": options.api_key_env, "thinking": "enabled",
            "reasoningEffort": options.reasoning_effort or "max",
            "maxTokens": options.max_output_tokens, "defaultContextWindow": options.context_tokens,
            "models": [{"id": model, "contextWindow": options.context_tokens,
                        "inputModalities": list(options.input_modalities)}],
        }
        if options.api_url is not None:
            base = options.api_url.rstrip("/")
            config["baseURL"] = base
            search_base = base if base.endswith("/v1") else base + "/v1"
            patches.extend([
                {"id": "web-search-deepseek", "config": {"apiKeyEnv": options.api_key_env, "baseURL": search_base, "model": model}},
                {"id": "web-deepseek-api", "config": {"apiKeyEnv": options.api_key_env, "baseURL": search_base + "/tools"}},
            ])
        else:
            patches.extend([
                {"id": "web-search-deepseek", "config": {"apiKeyEnv": options.api_key_env, "model": model}},
                {"id": "web-deepseek-api", "config": {"apiKeyEnv": options.api_key_env}},
            ])
        if options.stream_idle_timeout_ms is not None:
            config["streamIdleTimeoutMs"] = options.stream_idle_timeout_ms
        patches.append({"id": "llm-deepseek", "config": config})
    else:
        route = {
            "apiKeyEnv": options.api_key_env,
            "models": [{"id": model, "contextWindow": options.context_tokens,
                        "maxTokens": options.max_output_tokens, "input": list(options.input_modalities)}],
        }
        if options.api_url is not None:
            route["baseURL"] = options.api_url.rstrip("/")
        if options.api is not None:
            route["api"] = options.api
        if options.reasoning_effort is not None:
            route["reasoning"] = options.reasoning_effort
        patches.append({"id": "llm-pi-ai", "config": {"providers": {options.provider: route}}})
    patches.extend([
        {"id": "compaction-basic", "config": {
            "thresholdRatio": options.compact_at_tokens / options.context_tokens,
            "headroomTokens": options.headroom_tokens, "maxTokens": options.summary_tokens,
        }},
        {"id": "session-persistence-jsonl", "config": {"root": session_root, "compression": "none"}},
    ])
    if not options.generate_titles:
        patches.append({"id": "session-title-llm", "disabled": True})
    if options.disable_web_tools:
        patches.append({"id": "tool-web", "disabled": True})
    return patches


class DeepSeekHarnessAgent(BaseAgent):
    """Stage native DSH through standard Harbor transfers and exec only."""

    options_model = DeepSeekHarnessOptions
    options: DeepSeekHarnessOptions
    capabilities = AgentCapabilities(atif=True, native_config=True)

    @staticmethod
    def name() -> str:
        return "deepseek-harness"

    def version(self) -> str:
        return self.options.version

    def _model(self) -> str:
        model = self.options.api_model or self._parsed_model_name
        if not model:
            raise ValueError("DSH requires an explicit API model")
        return model

    def to_agent_info(self) -> AgentInfo:
        # api_model/provider select the real native route even when Harbor's
        # display model has a different prefix or the model is supplied by kwargs.
        return AgentInfo(name=self.name(), version=self.version(),
                         model_info=ModelInfo(name=self._model(), provider=self.options.provider))

    def _native_env(self, remote_logs: str, *, api_key: str = "") -> dict[str, str]:
        return {**self.extra_env, "DSH_HOME": f"{remote_logs}/home",
                "DSH_PERMISSION_MODE": "danger-full-access", "DSH_TELEMETRY_DISABLED": "1",
                self.options.api_key_env: api_key}

    async def setup(self, environment: BaseEnvironment) -> None:
        if self.mcp_servers or self.skills_dir or self.load_trajectory:
            raise ValueError("DSH uses its native profile; Harbor MCP, task-skills and resume are not implemented")
        manifest = validate_dsh_bundle(self.options.bundle_path, self.version(), self.options.manifest_sha256)
        await environment.upload_dir(self.options.bundle_path, REMOTE_BUNDLE)
        with tempfile.TemporaryDirectory(prefix="alw-dsh-config-") as directory:
            root = Path(directory)
            session_root = str(self.environment_logs_dir / "deepseek-harness/home/sessions")
            (root / "eval.patch.yml").write_text(json.dumps(native_patch(self.options, self._model(), session_root), ensure_ascii=False, indent=2) + "\n")
            (root / "dsh_logs.py").write_bytes(Path(__file__).with_name("dsh_logs.py").read_bytes())
            await environment.upload_dir(root, REMOTE_CONFIG)
        logs = str(self.environment_logs_dir / "deepseek-harness-setup")
        cli = f"{REMOTE_BUNDLE}/{ENTRYPOINT}"
        version = shlex.join([self.options.node_path, cli, "--version"])
        dump = shlex.join([self.options.node_path, cli, "--profile", "headless", "--patch", f"{REMOTE_CONFIG}/eval.patch.yml", "--dump-config"])
        command = (f"mkdir -p {shlex.quote(logs)} && {version} > {shlex.quote(logs + '/version.txt')} "
                   f"2> {shlex.quote(logs + '/version.stderr')} && "
                   f"test \"$(cat {shlex.quote(logs + '/version.txt')})\" = {shlex.quote(self.version())} && "
                   f"{dump} > {shlex.quote(logs + '/composed.yml')} 2> {shlex.quote(logs + '/stderr.log')}")
        result = await environment.exec(command=command, cwd=self.options.workdir,
                                        env=self._native_env(logs), timeout_sec=None)
        if result.return_code != 0:
            raise RuntimeError("DSH native version/configuration check failed; see deepseek-harness-setup logs")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "deepseek-harness-runtime.json").write_text(json.dumps({
            "package": PACKAGE, "version": self.version(), "manifest_sha256": self.options.manifest_sha256,
            "upstream": manifest.get("upstream"), "session_id": None,
            "profile": "headless", "provider": self.options.provider, "api": self.options.api,
            "api_model": self._model(),
            "reasoning_effort_requested": (self.options.reasoning_effort or "max")
                if self.options.provider == "deepseek-official" else self.options.reasoning_effort,
            "input_modalities": list(self.options.input_modalities), "generate_titles": self.options.generate_titles,
            "disable_web_tools": self.options.disable_web_tools,
            "context_tokens": self.options.context_tokens, "compact_at_tokens": self.options.compact_at_tokens,
            "max_output_tokens": self.options.max_output_tokens,
            "summary_tokens": self.options.summary_tokens, "headroom_tokens": self.options.headroom_tokens,
        }, indent=2) + "\n")

    async def run(self, instruction: str, environment: BaseEnvironment, context: AgentContext) -> None:
        key = self._get_env(self.options.api_key_env)
        if not key:
            raise ValueError(f"DSH credential environment variable is missing: {self.options.api_key_env}")
        instruction_file = self.logs_dir / "instruction.txt"
        instruction_file.write_text(instruction)
        await environment.upload_file(instruction_file, f"{REMOTE_CONFIG}/instruction.txt")
        logs = str(self.environment_logs_dir / "deepseek-harness")
        native = shlex.join([self.options.node_path, f"{REMOTE_BUNDLE}/{ENTRYPOINT}",
                             "--profile", "headless", "--patch", f"{REMOTE_CONFIG}/eval.patch.yml",
                             "--", "--json", "-"])
        check = shlex.join([self.options.python_path, "-I", "-B", f"{REMOTE_CONFIG}/dsh_logs.py",
                            "--check-completed", "--logs-dir", logs])
        command = (f"mkdir -p {shlex.quote(logs)} && "
                   f"{native} < {shlex.quote(REMOTE_CONFIG + '/instruction.txt')} "
                   f"> {shlex.quote(logs + '/stdout.log')} 2> {shlex.quote(logs + '/stderr.log')}; "
                   f"native_status=$?; {check} > {shlex.quote(logs + '/completion.json')}; "
                   "completion_status=$?; if [ \"$native_status\" -ne 0 ]; then exit \"$native_status\"; fi; exit \"$completion_status\"")
        result = await environment.exec(command=command, cwd=self.options.workdir,
                                        env=self._native_env(logs, api_key=key), timeout_sec=None)
        if result.return_code != 0:
            raise NonZeroAgentExitCodeError(f"DSH native run did not complete successfully (exit {result.return_code}); see native logs")
        # Do not populate context here: on unmounted backends logs have not been
        # downloaded yet. Harbor calls the hook after syncing logs, including
        # after timeout/cancellation; an early partial context suppresses it.

    def populate_context_post_run(self, context: AgentContext) -> None:
        from analoglayoutworld_agents.dsh_logs import populate_dsh_context

        identity_path = self.logs_dir / "deepseek-harness-runtime.json"
        identity = json.loads(identity_path.read_text()) if identity_path.exists() else {}
        audit = populate_dsh_context(self.logs_dir, context, self._model(), self.version(),
                                     session_id=identity.get("session_id"))
        if audit.get("root_session_id") and identity_path.exists():
            identity["session_id"] = audit["root_session_id"]
            identity_path.write_text(json.dumps(identity, indent=2) + "\n")
