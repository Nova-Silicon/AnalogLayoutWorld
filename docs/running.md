# Running AnalogLayoutWorld

[English](running.md) | [简体中文](running.zh-CN.md) · [Documentation index](README.md)

This guide expands the two alternatives in the [Quick Start](../README.md):
**A. a hosted model API using OpenCode's native OpenAI provider**, or
**B. a self-hosted Chat Completions service using its API URL**.
Both use native Harbor commands. Run commands from the checkout root in Bash.
For other agents, see the [six harness recipes](agents.md). To evaluate an
existing GDS without a model account, complete installation and go to
[chapter 8](#existing-gds).

<a id="installation"></a>
<a id="1-check-the-host-and-prepare-the-eda-image"></a>
## 1. Install the host tools and Harbor

Use a **Linux/amd64 Docker host, Docker Compose v2 and Python 3.12+** with
`venv`. Install Git, Docker Engine and its Compose plugin, then run:

```bash
git clone https://github.com/Nova-Silicon/AnalogLayoutWorld.git
cd AnalogLayoutWorld
docker info --format '{{.ServerVersion}}'
docker compose version
python3 --version
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[harbor]'
alw list
```

`docker info` must reach a running Docker daemon; Compose must be v2 and Python
must be at least 3.12. The editable installation pins **Harbor 0.24.0**.
`alw list` should print the release's 40 task records and stable task IDs.
Reactivate `.venv` when opening a new shell.

Start with one task. Each concurrent trial requests **6 CPU and 32 GiB** by
default, in addition to host overhead. Keep disk space for images, harness
installation and results. The public prebuilt EDA image is pulled automatically
by the task Dockerfiles. Image details, optional prefetching, runtime checks and
source rebuilds are collected in the [image guide](images.md).

Harbor installs **OpenCode 1.19.0** inside each Agent container for the commands
below. The EDA image supplies the PDK, native EDA tools, Python and Node/npm;
harness installation and credentials are separate from that image. Image pulls,
harness installation and model API calls need network access. Task instructions
require offline EDA tool use; independent verification has networking disabled.

<a id="endpoint"></a>
## 2. Choose A or B and configure the endpoint

Choose one alternative in a fresh shell with `.venv` activated. Supply your
actual model ID and API credentials; the repository does not provide them.
Host-side interactive OpenCode login files are not copied into new task
containers.

| Alternative | Service protocol | Model prefix | Extra OpenCode configuration |
|---|---|---|---|
| A: hosted model API | Native OpenAI provider; the service must support the protocol it selects, which may be Responses | `openai/` | None |
| B: self-hosted API URL | OpenAI-compatible `/v1/chat/completions` | `litellm_proxy/` | `PROVIDER_OPTIONS` below |

A hosted Chat Completions-only gateway also uses B. An API key or a base URL
alone does not make Chat Completions and Responses interchangeable.

<a id="hosted-api"></a>
### A. Hosted model API with the native OpenAI provider

For an OpenAI API account and a model available to that account:

```bash
unset OPENAI_BASE_URL PROVIDER_OPTIONS
export OPENAI_API_KEY='YOUR_API_KEY'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
```

`unset` clears a custom endpoint and compatible-provider options left by an
earlier shell configuration. The native provider uses `OPENAI_API_KEY`. Continue with command
A in [chapter 3](#single-task).

<a id="self-hosted-url"></a>
<a id="chat-completions-compatible-gateways"></a>
### B. Self-hosted Chat Completions API URL

Start your model service separately and use its documented API base URL, ending
in `/v1` for this example. Replace the URL and use the exact model identifier
accepted by that service:

```bash
export OPENAI_BASE_URL='http://your-model-server.example:8000/v1'
export OPENAI_API_KEY='YOUR_API_KEY'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
export PROVIDER_OPTIONS='{"provider":{"litellm_proxy":{"npm":"@ai-sdk/openai-compatible","options":{"baseURL":"{env:OPENAI_BASE_URL}","apiKey":"{env:OPENAI_API_KEY}"}}}}'
```

This explicitly selects OpenCode's compatible Chat Completions implementation.
Harbor's existing `litellm_proxy` alias forwards the standard OpenAI environment
variables; the name does not require running a separate LiteLLM proxy.
If the service has no authentication, set `OPENAI_API_KEY` to `not-needed`. The JSON contains environment references, not key values. Set context/output
limits according to your model service when needed.

OpenCode connects from the **Agent container**. Test connectivity there. In a container, `localhost` or `127.0.0.1` points to that container, not the host running
your model server. Use a hostname or address routed to your service, and check
the service's listening address, port and authentication. Continue with command
B in [chapter 3](#single-task).

<a id="single-task"></a>
## 3. Run one task with one attempt

Run only the command matching chapter 2. Each command creates a named job with
**one attempt, one concurrent trial and zero automatic retries**, using the full
task budget. These commands make model API calls.

**A. Hosted API:**

```bash
harbor run \
  --path tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --model "openai/${MODEL_ID}" \
  --agent-kwarg version=1.19.0 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-api-run
```

**B. Self-hosted URL:**

```bash
harbor run \
  --path tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --model "litellm_proxy/${MODEL_ID}" \
  --agent-kwarg version=1.19.0 \
  --agent-kwarg "opencode_config=${PROVIDER_OPTIONS}" \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-url-run
```

Choose a new job name for each new run. Append `--print-config` to either command
to inspect the native JobConfig without starting containers or calling a model.
This checks command/configuration construction, not credentials, API
reachability or model compatibility.

The task configuration specifies **10,800 seconds for the Agent**, with
independent verification in a separate container using a **3,600-second outer
budget and 3,300-second internal budget**. The commands preserve the task's
instructions and native EDA interfaces.

<a id="all-tasks"></a>
## 4. Run all 40 tasks

After a single task confirms that your service configuration works, reuse
command A or B from chapter 3 with these changes:

| Argument | Single task | All 40 tasks |
|---|---|---|
| `--path` | `tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout` | `tasks` |
| `--job-name` | `first-api-run` or `first-url-run` | A new name, such as `all-api-run` or `all-url-run` |

Keep the selected provider's model prefix and, for B, its `opencode_config`.
With `--n-attempts 1 --n-concurrent 1 --max-retries 0`, the 40 tasks run serially,
once each, without automatic retries. Raising concurrency multiplies the Docker
resource requirement. These settings establish a first full run; the formal
attempt count is described next.

<a id="formal-evaluation"></a>
## 5. Use three attempts for formal evaluation

For the formal three-attempt setup, reuse your working A or B command with
`--path tasks`, replace `--n-attempts 1` with **`--n-attempts 3`**, and choose a
new job name such as `formal-api-run` or `formal-url-run`. Keep
`--n-concurrent 1 --max-retries 0` and the pinned harness version. This schedules
**40 tasks × 3 independent attempts = 120 trials**; each receives the full task
budget. Independent attempts and automatic retries are different settings.

Preserve the exact model ID, provider/protocol, harness version, model options,
attempt count, resource allocation and job configuration with the results.
Interpret scores using the [scoring protocol](protocol.md).

<a id="results"></a>
<a id="4-inspect-the-outcome-or-evaluate-existing-artifacts"></a>
## 6. Inspect outputs and evidence

For command A, Harbor saves the following under `jobs/first-api-run/`; command B
uses `jobs/first-url-run/` instead:

```text
jobs/first-api-run/
  config.json
  result.json                  # aggregate job outcomes and errors
  <trial-name>/
    result.json                # this attempt, errors and verifier reward
    agent/                     # harness output; trajectory format varies
    artifacts/
      submission/              # present only if the agent saved artifacts
        layout.gds
        src/
    verifier/
      evaluation/
        metrics.json           # physical/electrical outcomes and score facts
        ...                    # stage reports and logs
```

The declared submission is transferred to a fresh verifier container. Use the
trial's `artifacts/submission/` directory to inspect or re-evaluate its layout.
An Agent deadline can leave a usable submission that is still independently
verified. Missing artifacts are not replaced with a sample layout or success
marker.

Read `score`, `score_valid`, `pipeline_completed`, `evaluation_error`,
`design_passed` and `score_is_lower_bound` together. A lower-bound score can
retain verified partial evidence while unfinished requirements remain in the
denominator. A tool call completing, a valid evaluation and a passing circuit
are separate outcomes. Consult the stage reports and [scoring protocol](protocol.md)
before interpreting the reward.

<a id="troubleshooting"></a>
## 7. Resolve setup and execution errors

| Observation | First check |
|---|---|
| Docker exists but cannot reach its server | Check the Docker service and access to its socket. |
| Task build cannot pull the EDA base | Check GHCR access and the published digest in the [image guide](images.md). |
| Authentication fails in a new container | Export the selected provider's credential variable in the process starting Harbor. |
| A compatible endpoint fails before model output | Check API protocol, model ID, and B's model prefix plus `opencode_config`. |
| Model connection times out or is refused | Check the URL from the Agent container, including the server's bind address and port; container `localhost` is not the Docker host. |
| Job directory or helper config already exists | Use a new job name; start a saved helper config with `harbor run --config`. |
| `alw` cannot find the checkout after a wheel install | Keep the checkout and use `alw --repository /path/to/AnalogLayoutWorld list` or `verify ...`; an editable install locates it automatically. |
| Installation or setup fails before a model call | Confirm Python 3.12+, Harbor 0.24.0, the pinned harness, package-source access and available disk/memory. |
| Trial reports an execution/evidence error | Read the job/trial `result.json` and verifier logs; do not treat it as a measured circuit failure. |
| A valid evaluation gives a low score | Read measured stage evidence; successful tool execution does not imply a passing layout. |

<a id="existing-gds"></a>
## 8. Evaluate an existing GDS without a model

Read the task's `instruction.md`, `environment/GUIDE.md`,
`environment/DEVICE_API.md` and `environment/task/testbench/README.md` for its
top cell, ports, native EDA commands and public fixtures.

Prepare your submission directory:

```text
my-submission/
  layout.gds
  src/
    generate.py
  README.md          # optional
```

The submission must contain the task's prescribed Python generation source in
`src/`; the verifier checks the GDS without executing that submitted source.
For an OTA submission in `my-submission/`, choose a new output directory:

```bash
alw verify \
  --task sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --submission "$PWD/my-submission" --out "$PWD/evaluation-ota5t"
```

The command writes `evaluation-ota5t/summary.json` and
`evaluation-ota5t/verifier/evaluation/metrics.json`. Exit codes are **0** (design
passed), **1** (valid evaluation, design did not fully pass) and **2**
(runner/evidence error). Default allocation is 6 CPU and `32g` memory;
`--cpus N --memory Ng` explicitly overrides it. Keep the default allocation
when comparing runs. Local image overrides are covered by the [image guide](images.md).

Host paths are resolved from the checkout and supplied arguments.
`/opt/analog-layout`, `/alb-workspace` and `/logs/verifier` are container paths.

<a id="helper"></a>
## 9. Optional: generate a JobConfig with the helper

`scripts/run_harbor.py` writes a native Harbor JobConfig and, without
`--dry-run`, invokes `harbor run`. To preview a native-provider job first:

```bash
python scripts/run_harbor.py \
  --task sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --agent-version 1.19.0 --model "openai/${MODEL_ID}" \
  --attempts 1 --concurrency 1 --job-name helper-api-run --dry-run
harbor run --config jobs/helper-api-run.json
```

The first command only writes and prints `jobs/helper-api-run.json`; inspect it
before running the second. Use `--task all` for all 40 tasks and `--attempts 3`
for formal evaluation. The helper defaults to three attempts, one concurrent
trial and zero retries, so set the attempt count explicitly.

Use the native command in chapter 3 for B: the helper does not expose an
`opencode_config` CLI option. Each helper invocation needs a new job name and
refuses to overwrite an existing config or job directory. Its launch file
`jobs/helper-api-run.json` is distinct from Harbor's resulting
`jobs/helper-api-run/config.json` record.
