# Choose an agent and model API

[English](agents.md) | [简体中文](agents.zh-CN.md) · [Documentation index](README.md)

These recipes use **Harbor 0.24.0** and the pinned harness versions below.
Install the [Harbor extra and Docker prerequisites](running.md#installation)
first, then run commands from the checkout root in the activated Python
environment. Harbor installs the selected harness inside each Agent container;
you do not install it on the host or rebuild the EDA base image. Image contents,
downloads and optional rebuilds are covered in the [image guide](images.md).

An API subscription, endpoint and model identifier must come from your provider.
Replace `MODEL_AVAILABLE_TO_YOUR_ACCOUNT` before starting a run. A valid API key
for one protocol does not imply support for another protocol. In particular,
Chat Completions, Responses and Anthropic Messages endpoints are different.
Use the recipe for the API your service actually exposes.

The commands below run one full-budget task with one attempt, one concurrent
trial and zero automatic retries. These commands make model API calls.
For [all 40 tasks](running.md#all-tasks), change `--path "$TASK"` to `--path tasks`;
for [formal evaluation](running.md#formal-evaluation), use three independent
attempts with `--n-attempts 3`. Use a new job name when repeating a run.
Increase `--n-concurrent` only when the Docker host has enough
resources: the task default is 6 CPU and 32 GiB per concurrent trial. Keep the
harness version, exact model ID, provider, model options and number of attempts
with your results.

```bash
export TASK='tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
```

Use a fresh shell when changing providers, or remove endpoint variables left by
an earlier recipe. Do not paste key values into shell commands, job JSON files
or source files. The `read` examples below avoid placing the entered key in shell
history. Do not enable shell tracing while handling credentials. A host's
interactive harness login is not automatically transferred to the task.

## Supported choices

| Harness | Harbor agent | Pinned version | Connection used by the recipe |
|---|---|---|---|
| OpenCode | `opencode` | 1.19.0 | Built-in OpenAI provider; explicit compatible provider for Chat Completions gateways |
| Kimi Code | `kimi-code` | 2.2.0 | Explicit Kimi model API environment |
| Claude Code | `claude-code` | 2.1.302 | Anthropic Messages |
| Codex | `codex` | 0.163.0 | OpenAI Responses |
| Qwen Code | `qwen-coder` | 0.26.1 | OpenAI-compatible Chat Completions |
| DeepSeek Harness (DSH) | Custom `import_path` | 0.2.1-rc.5 | Native provider selected in its JobConfig |

## OpenCode

For the hosted-API alternative in the [Quick Start](../README.md), use the
built-in OpenAI provider:

```bash
unset OPENAI_BASE_URL PROVIDER_OPTIONS
read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
harbor run \
  --path "$TASK" --agent opencode --model "openai/${MODEL_ID}" \
  --agent-kwarg version=1.19.0 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-api-run
```

The built-in provider may use Responses. For a self-hosted API URL or a hosted
Chat Completions-only gateway, use the complete
[alternative B configuration](running.md#self-hosted-url) and
[native run command](running.md#single-task), with the `litellm_proxy/` prefix.
Its `opencode_config` is specific to OpenCode and is not a shared option for the
other harnesses.

## Kimi Code

This is the npm Kimi Code CLI selected by `kimi-code`, not the separate
`kimi-cli` Harbor integration. Supply the API endpoint and model capabilities
for your account. For example, the public Moonshot China Chat Completions base
is `https://api.moonshot.cn/v1`; a Kimi Coding subscription can expose a different
endpoint and model entitlement. Do not substitute a web-chat login for API access.

```bash
export KIMI_MODEL_BASE_URL='https://api.moonshot.cn/v1'
read -r -s -p 'Kimi model API key: ' KIMI_MODEL_API_KEY
export KIMI_MODEL_API_KEY
harbor run \
  --path "$TASK" --agent kimi-code --model "$MODEL_ID" \
  --agent-kwarg version=2.2.0 \
  --agent-env 'KIMI_MODEL_BASE_URL=${KIMI_MODEL_BASE_URL}' \
  --agent-env 'KIMI_MODEL_API_KEY=${KIMI_MODEL_API_KEY}' \
  --agent-env KIMI_MODEL_MAX_CONTEXT_SIZE=262144 \
  --agent-env KIMI_MODEL_CAPABILITIES=image_in,thinking \
  --agent-env KIMI_CODE_EXPERIMENTAL_FLAG=true \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-kimi-run
```

The context and capability values above require a model that supports them;
adjust them to the provider's actual specification. `--model` becomes
`KIMI_MODEL_NAME` inside the Agent. The single-quoted `${...}` strings are Harbor
environment references: Harbor reads their values from the launching process.
Keep the quotes so the shell does not embed the secret in the command arguments.

## Claude Code

For an Anthropic API account:

```bash
read -r -s -p 'Anthropic API key: ' ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY
harbor run \
  --path "$TASK" --agent claude-code --model "anthropic/${MODEL_ID}" \
  --agent-kwarg version=2.1.302 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-claude-run
```

For an **Anthropic Messages-compatible** gateway, additionally export its
documented `ANTHROPIC_BASE_URL` and pass its exact model ID as
`--model "$MODEL_ID"`, without adding a provider prefix. Harbor 0.24 preserves
the model name when a custom base URL is configured. The adapter accepts
`ANTHROPIC_API_KEY` or `ANTHROPIC_AUTH_TOKEN`; use the authentication method the
service specifies. This does not turn a Chat Completions endpoint into a
Messages endpoint.

## Codex

For an OpenAI API account with a model supported by Codex:

```bash
read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
harbor run \
  --path "$TASK" --agent codex --model "openai/${MODEL_ID}" \
  --agent-kwarg version=0.163.0 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-codex-run
```

A custom endpoint must implement the Responses protocol expected by this
configuration. Export its `OPENAI_BASE_URL` before launching Harbor. Harbor
resolves `OPENAI_API_KEY`, passes it to Codex authentication and uploads the
effective endpoint configuration. A Chat Completions-only gateway needs a
different client; changing only the URL cannot provide Responses support.

## Qwen Code

The native Harbor name is **`qwen-coder`**. This adapter explicitly selects
OpenAI-compatible authentication and Chat Completions:

```bash
export OPENAI_BASE_URL='https://your-provider.example/v1'
read -r -s -p 'Chat Completions API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
harbor run \
  --path "$TASK" --agent qwen-coder --model "openai/${MODEL_ID}" \
  --agent-kwarg version=0.26.1 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-qwen-run
```

Replace the example URL with the provider's real API base. Harbor forwards
`OPENAI_API_KEY` and `OPENAI_BASE_URL` and removes the leading `openai/` from the
model ID passed to Qwen Code. This recipe uses API credentials, not interactive
Qwen OAuth.

## DeepSeek Harness (DSH)

Follow the complete [DSH build and JobConfig recipe](../harnesses/deepseek-harness/README.md).
It includes the pinned Node/pnpm runtime build, bundle manifest check, provider
selection, credential references and `harbor run --config` command. DSH is not a
built-in Harbor 0.24 agent: select
`analoglayoutworld_agents.deepseek_harness:DeepSeekHarnessAgent` through
`import_path`, not `--agent dsh`.

The recipe's Moonshot route uses its shipped Chat Completions provider. The
native `deepseek-official` route expects DSH's DeepSeek Messages interface;
generic `/v1/chat/completions` gateways must not be routed through it. The bundle
is built on the controller once and uploaded during setup.

## Check configuration and read results

Append `--print-config` to a native command to inspect its JobConfig without
starting containers or making model calls. This checks CLI/configuration
construction, not API credentials, service reachability or model compatibility.
Use placeholder references for secrets when saving or sharing configs.

After a real run, inspect the job's `result.json`, per-trial `result.json`,
`agent/` records and `verifier/` reports under `jobs/`. An Agent deadline can leave
a usable submission that is still independently verified. A completed tool call,
a valid evaluation and a passing circuit are separate outcomes; read
`evaluation/metrics.json` and the stage reports before interpreting the reward.
See the running guide for [result paths](running.md#results),
[troubleshooting](running.md#troubleshooting) and
[verification of an existing GDS](running.md#existing-gds).
