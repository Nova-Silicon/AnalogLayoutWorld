# 运行 AnalogLayoutWorld

[English](running.md) | **简体中文** · [文档目录](README.zh-CN.md)

本指南展开[快速开始](../README.zh-CN.md)中的两条路径：
**A. 通过 OpenCode 原生 OpenAI provider 调用托管模型 API**，或
**B. 通过 API URL 调用自部署的 Chat Completions 服务**。
两条路径都使用原生 Harbor 命令。以下命令均在仓库根目录的 Bash 中执行。
其他 Agent 见[六种 harness 配置](agents.zh-CN.md)。如果只想验收已有 GDS，
无需模型账号，完成安装后可直接阅读[第 8 章](#existing-gds)。

<a id="installation"></a>
<a id="1-检查宿主机并准备-eda-镜像"></a>
## 1. 安装宿主机工具与 Harbor

使用 **Linux/amd64 Docker 主机、Docker Compose v2 和带 `venv` 的 Python 3.12+**。
安装 Git、Docker Engine 及 Compose 插件，然后执行：

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

`docker info` 必须能连接运行中的 Docker 服务；Compose 应为 v2，Python 至少为 3.12。
可编辑安装会固定使用 **Harbor 0.24.0**。`alw list` 应列出本版的 40 道题及稳定任务 ID。
打开新的 shell 后，需要重新激活 `.venv`。

先运行一道题。每个并行 trial 默认申请 **6 CPU、32 GiB 内存**，还需为宿主机保留余量。
磁盘需容纳镜像、harness 安装与结果。任务 Dockerfile 会自动拉取公开预构建 EDA
镜像；镜像详情、可选预下载、运行时检查和源码重建统一见[镜像指南](images.zh-CN.md)。

以下命令由 Harbor 在每个 Agent 容器中安装 **OpenCode 1.19.0**。
EDA 镜像提供 PDK、原生 EDA 工具、Python 和 Node/npm；harness 安装及凭据独立于
该镜像。镜像拉取、harness 安装和模型 API 调用需要网络。
任务指令要求 EDA 工具离线使用；独立验收时禁用网络。

<a id="endpoint"></a>
## 2. 选择 A 或 B 并配置服务地址

在已激活 `.venv` 的新 shell 中选择一条路径。请填写实际模型 ID 和 API 凭据，
仓库不提供这些信息。宿主机上的 OpenCode 交互登录文件不会复制到新任务容器。

| 路径 | 服务协议 | 模型前缀 | 额外 OpenCode 配置 |
|---|---|---|---|
| A：托管模型 API | 原生 OpenAI provider；服务需支持它所选择的协议，可能为 Responses | `openai/` | 无 |
| B：自部署 API URL | OpenAI 兼容的 `/v1/chat/completions` | `litellm_proxy/` | 下方的 `PROVIDER_OPTIONS` |

只支持 Chat Completions 的托管网关也使用 B。仅有 API key 或基础 URL，
不能使 Chat Completions 和 Responses 两种协议互换。

<a id="hosted-api"></a>
### A. 使用原生 OpenAI provider 调用托管模型 API

对于 OpenAI API 账号及该账号可用的模型：

```bash
unset OPENAI_BASE_URL PROVIDER_OPTIONS
export OPENAI_API_KEY='YOUR_API_KEY'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
```

`unset` 会清除先前 shell 配置留下的自定义地址和兼容 provider 选项。
原生 provider 使用 `OPENAI_API_KEY`。随后执行[第 3 章](#single-task)的 A 命令。

<a id="self-hosted-url"></a>
<a id="仅兼容-chat-completions-的网关"></a>
### B. 使用自部署的 Chat Completions API URL

先独立启动模型服务，再使用其文档指定的 API 基础地址，本例以 `/v1` 结尾。
替换下方 URL，并填写该服务接受的精确模型标识：

```bash
export OPENAI_BASE_URL='http://your-model-server.example:8000/v1'
export OPENAI_API_KEY='YOUR_API_KEY'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
export PROVIDER_OPTIONS='{"provider":{"litellm_proxy":{"npm":"@ai-sdk/openai-compatible","options":{"baseURL":"{env:OPENAI_BASE_URL}","apiKey":"{env:OPENAI_API_KEY}"}}}}'
```

此配置显式选择 OpenCode 的兼容 Chat Completions 实现。
Harbor 已有的 `litellm_proxy` 别名负责转发标准 OpenAI 环境变量；该名称不要求额外
运行 LiteLLM 代理。服务未启用鉴权时，可将 `OPENAI_API_KEY` 设为 `not-needed`。
JSON 中保存的是环境变量引用，不是密钥值。
如需设置上下文或输出上限，请依据实际模型服务配置。

OpenCode 从 **Agent 容器**连接模型服务，请在该容器内检查连通性。容器中的 `localhost` 或 `127.0.0.1`
指向该容器，不是运行模型服务的宿主机。请使用能路由到服务的主机名或地址，
并检查服务的监听地址、端口和鉴权。随后执行[第 3 章](#single-task)的 B 命令。

<a id="single-task"></a>
## 3. 运行一道题、一次尝试

只执行与第 2 章所选路径对应的命令。两条命令均使用完整任务预算，创建明确命名的
作业，并显式设置为**一次尝试、一个并行 trial、零次自动重试**。
以下命令会调用模型 API。

**A. 托管 API：**

```bash
harbor run \
  --path tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --model "openai/${MODEL_ID}" \
  --agent-kwarg version=1.19.0 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-api-run
```

**B. 自部署 URL：**

```bash
harbor run \
  --path tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --model "litellm_proxy/${MODEL_ID}" \
  --agent-kwarg version=1.19.0 \
  --agent-kwarg "opencode_config=${PROVIDER_OPTIONS}" \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-url-run
```

每次新运行都使用新的作业名。在任一命令末尾添加 `--print-config`，可查看原生
JobConfig，而不启动容器或调用模型。该操作只检查命令与配置构造，
不检查凭据、API 连通性或模型兼容性。

任务配置规定 **Agent 预算为 10,800 秒**；独立验收在单独容器内执行，
使用 **3,600 秒外层预算和 3,300 秒内部预算**。
以上命令保留任务原有指令和原生 EDA 接口。

<a id="all-tasks"></a>
## 4. 运行完整 40 题

单题运行确认服务配置可用后，复用第 3 章的 A 或 B 命令，仅修改：

| 参数 | 单题 | 全部 40 题 |
|---|---|---|
| `--path` | `tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout` | `tasks` |
| `--job-name` | `first-api-run` 或 `first-url-run` | 新名称，例如 `all-api-run` 或 `all-url-run` |

保留所选 provider 的模型前缀；B 还需保留 `opencode_config`。
`--n-attempts 1 --n-concurrent 1 --max-retries 0` 表示 40 题逐一串行运行，
每题一次，不自动重试。提高并发会按数量增加 Docker 资源需求。
这些设置适合首次完整运行，正式评估的尝试次数见下一章。

<a id="formal-evaluation"></a>
## 5. 正式评估使用三次独立尝试

正式三次尝试的配置复用已验证可用的 A 或 B 命令：使用 `--path tasks`，
将 `--n-attempts 1` 改为 **`--n-attempts 3`**，并选择新作业名，例如
`formal-api-run` 或 `formal-url-run`。保留
`--n-concurrent 1 --max-retries 0` 和固定 harness 版本。
此配置共运行 **40 题 × 3 次独立尝试 = 120 个 trial**，每次均享有完整任务预算。
独立尝试次数与自动重试次数是不同设置。

随结果保存精确模型 ID、provider／协议、harness 版本、模型选项、尝试次数、
资源分配和作业配置。分数解释见[计分协议](protocol.zh-CN.md)。

<a id="results"></a>
<a id="4-检查结果或直接验收已有提交"></a>
## 6. 检查输出与证据

A 命令将以下内容保存在 `jobs/first-api-run/`；B 对应的目录为
`jobs/first-url-run/`：

```text
jobs/first-api-run/
  config.json
  result.json                  # 作业汇总结果与错误
  <trial-name>/
    result.json                # 本次尝试、错误与验收 reward
    agent/                     # harness 输出，轨迹格式因 Agent 而异
    artifacts/
      submission/              # 仅在 Agent 保存了提交产物后存在
        layout.gds
        src/
    verifier/
      evaluation/
        metrics.json           # 物理／电气检查结果与计分事实
        ...                    # 各阶段报告与日志
```

任务声明的提交产物会被转交到一个新建的独立验收容器。查看版图或复验时，
使用对应 trial 的 `artifacts/submission/` 目录。Agent 到达时限后仍可能留下可用
提交，该提交依然会接受独立验收。缺失产物不会用示例版图或成功标记代替。

应结合 `score`、`score_valid`、`pipeline_completed`、`evaluation_error`、
`design_passed` 和 `score_is_lower_bound` 判断结果。下界分数可以保留已验证的部分
证据，未完成的要求仍留在分母中。工具调用完成、验收有效执行、电路通过是不同的
结果。解释 reward 前，请阅读各阶段报告和[计分协议](protocol.zh-CN.md)。

<a id="troubleshooting"></a>
## 7. 排查安装与执行错误

| 现象 | 首先检查 |
|---|---|
| 有 Docker 命令，但无法访问服务端 | 检查 Docker 服务是否运行，以及当前用户访问 socket 的权限。 |
| 任务构建无法拉取 EDA 基础镜像 | 检查 GHCR 连通性及[镜像指南](images.zh-CN.md)中的公开摘要。 |
| 新容器内模型认证失败 | 在启动 Harbor 的进程中导出所选 provider 的凭据环境变量。 |
| 兼容 API 在模型输出前就失败 | 检查 API 协议、模型 ID，以及 B 的模型前缀和 `opencode_config`。 |
| 模型连接超时或被拒绝 | 从 Agent 容器检查 URL、服务监听地址和端口；容器内 `localhost` 不是 Docker 主机。 |
| 作业目录或辅助配置已存在 | 使用新作业名；已有辅助配置可用 `harbor run --config` 启动。 |
| 通过 wheel 安装后，`alw` 找不到任务仓库 | 保留仓库，使用 `alw --repository /path/to/AnalogLayoutWorld list` 或 `verify ...`；可编辑安装会自动定位仓库。 |
| 安装或初始化在模型调用前失败 | 检查 Python 3.12+、Harbor 0.24.0、固定 harness 版本、软件源连通性及磁盘／内存余量。 |
| trial 出现执行或证据错误 | 阅读作业及 trial 的 `result.json` 和验收日志，不能将其视为实际测得的电路不通过。 |
| 有效验收得到较低分数 | 阅读实际测量的阶段证据；工具成功执行不代表版图通过。 |

<a id="existing-gds"></a>
## 8. 不调用模型，直接验收已有 GDS

先阅读该题的 `instruction.md`、`environment/GUIDE.md`、
`environment/DEVICE_API.md` 和 `environment/task/testbench/README.md`，
确认顶层 cell、端口、原生 EDA 命令和公开测试台。

准备提交目录：

```text
my-submission/
  layout.gds
  src/
    generate.py
  README.md          # 可选
```

提交需包含任务要求的 `src/` 下 Python 生成源码；验收器检查 GDS，不执行提交的源码。
若 OTA 提交位于 `my-submission/`，请选择新的输出目录：

```bash
alw verify \
  --task sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --submission "$PWD/my-submission" --out "$PWD/evaluation-ota5t"
```

命令生成 `evaluation-ota5t/summary.json` 和
`evaluation-ota5t/verifier/evaluation/metrics.json`。退出码 **0** 表示设计通过；
**1** 表示验收有效但设计未完全通过；**2** 表示运行器或证据出现错误。
默认分配 6 CPU、`32g` 内存；可用 `--cpus N --memory Ng` 显式覆盖。
比较结果时保留默认资源分配。本地镜像覆盖方式见[镜像指南](images.zh-CN.md)。

宿主机路径由仓库位置及传入参数解析。`/opt/analog-layout`、`/alb-workspace`
和 `/logs/verifier` 均为容器内路径。

<a id="helper"></a>
## 9. 可选：用辅助脚本生成 JobConfig

`scripts/run_harbor.py` 生成原生 Harbor JobConfig；未指定 `--dry-run` 时会调用
`harbor run`。预览原生 provider 的作业配置：

```bash
python scripts/run_harbor.py \
  --task sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout \
  --agent opencode --agent-version 1.19.0 --model "openai/${MODEL_ID}" \
  --attempts 1 --concurrency 1 --job-name helper-api-run --dry-run
harbor run --config jobs/helper-api-run.json
```

第一条命令只写入并打印 `jobs/helper-api-run.json`；检查后再执行第二条命令。
完整 40 题使用 `--task all`，正式评估使用 `--attempts 3`。
辅助脚本默认为三次尝试、一个并行 trial、零次重试，因此请显式指定尝试次数。

B 路径请使用第 3 章的原生命令，辅助脚本未提供 `opencode_config` 命令行选项。
每次调用辅助脚本都需使用新作业名；已有配置或作业目录会被拒绝覆盖。
启动文件 `jobs/helper-api-run.json` 与 Harbor 运行后保存的
`jobs/helper-api-run/config.json` 作业记录是两个文件。
