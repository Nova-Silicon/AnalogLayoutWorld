# 选择 Agent 与模型 API

[English](agents.md) | **简体中文** · [文档目录](README.zh-CN.md)

以下配置使用 **Harbor 0.24.0**，以及下表固定的 harness 版本。
先完成[Harbor 扩展与 Docker 环境安装](running.zh-CN.md#installation)，
随后在已激活的 Python 环境中，从仓库根目录运行命令。
Harbor 会将所选 harness 安装到每个 Agent 容器内，无需在主机上安装，
也无需重新构建 EDA 基础镜像。镜像内容、下载及可选重建见[镜像指南](images.zh-CN.md)。

API 订阅、服务地址和模型标识由模型服务商提供。开始前将
`MODEL_AVAILABLE_TO_YOUR_ACCOUNT` 替换为账号实际可用的模型。
某种协议的有效 API key 不意味着服务支持其他协议；
特别是 Chat Completions、Responses 和 Anthropic Messages 是不同的接口。
请按照服务实际提供的 API 选择配置。

下面的命令运行一道完整预算任务：一次尝试、一个并行 trial、零次自动重试。
这些命令会调用模型 API。[运行全部 40 题](running.zh-CN.md#all-tasks)时，
将 `--path "$TASK"` 改成 `--path tasks`；
[正式评估](running.zh-CN.md#formal-evaluation)使用 `--n-attempts 3`，每题三次独立尝试。
重复运行时使用新的作业名。
只有 Docker 主机资源充足时才提高 `--n-concurrent`；
默认每个并行任务需要 6 CPU 和 32 GiB 内存。
随结果保存 harness 版本、精确模型 ID、服务商、模型选项和尝试次数。

```bash
export TASK='tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout'
export MODEL_ID='MODEL_AVAILABLE_TO_YOUR_ACCOUNT'
```

切换服务商时使用新的 shell，或先清除上一种配置留下的服务地址变量。
不要把 key 值粘贴到 shell 命令、任务 JSON 或源码里；下方 `read` 示例不会将输入的
key 写进 shell 历史。处理凭据时不要开启 shell 跟踪。
主机上 harness 的交互式登录状态不会自动传入任务容器。

## 支持的选项

| Harness | Harbor Agent 名称 | 固定版本 | 示例使用的连接方式 |
|---|---|---|---|
| OpenCode | `opencode` | 1.19.0 | 内置 OpenAI 服务商；Chat Completions 网关需显式配置兼容服务商 |
| Kimi Code | `kimi-code` | 2.2.0 | 显式传入 Kimi 模型 API 环境变量 |
| Claude Code | `claude-code` | 2.1.302 | Anthropic Messages |
| Codex | `codex` | 0.163.0 | OpenAI Responses |
| Qwen Code | `qwen-coder` | 0.26.1 | OpenAI 兼容的 Chat Completions |
| DeepSeek Harness（DSH） | 自定义 `import_path` | 0.2.1-rc.5 | 通过 JobConfig 选择原生服务商 |

## OpenCode

对于[快速开始](../README.zh-CN.md)中的托管 API 路径，使用内置 OpenAI provider：

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

内置 provider 可能使用 Responses。对于自部署 API URL 或只提供 Chat Completions
的托管网关，请使用完整的[B 路径配置](running.zh-CN.md#self-hosted-url)和
[原生运行命令](running.zh-CN.md#single-task)，模型前缀为 `litellm_proxy/`。
其中的 `opencode_config` 仅适用于 OpenCode，不是其他 harness 共用的参数。

## Kimi Code

这里使用 `kimi-code` 选中的 npm Kimi Code CLI，
不是 Harbor 另一个独立的 `kimi-cli` 集成。
需要填写账号对应的 API 地址及模型能力。
例如，Moonshot 中国区公开的 Chat Completions 基础地址为
`https://api.moonshot.cn/v1`；Kimi Coding 订阅可能使用不同的服务地址和模型权限。
网页版聊天登录不能代替 API 访问权限。

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

上述上下文大小和能力配置需要模型实际支持，请依据服务商规格调整。
`--model` 会成为 Agent 内的 `KIMI_MODEL_NAME`。
用单引号包围的 `${...}` 是 Harbor 环境变量引用，Harbor 从启动进程中读取值。
保留引号，避免 shell 将密钥直接展开到命令参数里。

## Claude Code

使用 Anthropic API 账号：

```bash
read -r -s -p 'Anthropic API key: ' ANTHROPIC_API_KEY
export ANTHROPIC_API_KEY
harbor run \
  --path "$TASK" --agent claude-code --model "anthropic/${MODEL_ID}" \
  --agent-kwarg version=2.1.302 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-claude-run
```

使用 **Anthropic Messages 兼容**网关时，另行导出服务商指定的 `ANTHROPIC_BASE_URL`，
并通过 `--model "$MODEL_ID"` 传入精确模型名，不额外添加服务商前缀。
设置自定义基础地址后，Harbor 0.24 会保留模型名。
适配器接受 `ANTHROPIC_API_KEY` 或 `ANTHROPIC_AUTH_TOKEN`；
请按服务商要求选择鉴权方式。这种设置不能将 Chat Completions 服务转化为 Messages 服务。

## Codex

使用 OpenAI API 账号及 Codex 支持的模型：

```bash
read -r -s -p 'OpenAI API key: ' OPENAI_API_KEY
export OPENAI_API_KEY
harbor run \
  --path "$TASK" --agent codex --model "openai/${MODEL_ID}" \
  --agent-kwarg version=0.163.0 \
  --env docker --n-concurrent 1 --n-attempts 1 --max-retries 0 \
  --job-name first-codex-run
```

自定义服务地址必须实现本配置所需的 Responses 协议。
启动 Harbor 前导出服务商给出的 `OPENAI_BASE_URL`。
Harbor 会读取 `OPENAI_API_KEY`，传入 Codex 鉴权，并上传生效的服务地址配置。
只支持 Chat Completions 的网关需要其他客户端；仅替换 URL 不能使其支持 Responses。

## Qwen Code

原生 Harbor 名称为 **`qwen-coder`**。此适配器显式使用 OpenAI 兼容鉴权和 Chat Completions：

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

将示例 URL 替换为服务商实际的 API 基础地址。
Harbor 会转发 `OPENAI_API_KEY` 和 `OPENAI_BASE_URL`，
并在将模型 ID 传给 Qwen Code 前移除开头的 `openai/`。
这里使用 API 凭据，不使用交互式 Qwen OAuth。

## DeepSeek Harness（DSH）

请按[完整 DSH 构建与 JobConfig 指南](../harnesses/deepseek-harness/README.md)操作。
其中包括固定 Node/pnpm 运行时构建、bundle 清单校验、服务商选择、凭据引用，
以及 `harbor run --config` 命令。
DSH 不是 Harbor 0.24 的内置 Agent：需要通过 `import_path` 选择
`analoglayoutworld_agents.deepseek_harness:DeepSeekHarnessAgent`，
不能使用 `--agent dsh`。

指南中的 Moonshot 路径使用运行时自带的 Chat Completions 服务商。
原生 `deepseek-official` 路径需要 DSH 的 DeepSeek Messages 接口，
不能用于通用 `/v1/chat/completions` 网关。
bundle 在控制端构建一次，并在任务初始化时上传。

## 检查配置与查看结果

在原生命令末尾添加 `--print-config`，即可查看 JobConfig，而不启动容器或调用模型。
此操作仅检查 CLI 和配置的构造，不验证 API 凭据、服务可达性或模型兼容性。
保存或分享配置时使用密钥占位引用。

真实运行后，查看 `jobs/` 下的任务批次 `result.json`、各 trial 的 `result.json`、
`agent/` 记录和 `verifier/` 报告。Agent 到达时限后仍可能留下可用提交，
该提交依然会接受独立验收。工具调用完成、验收有效执行、电路通过是不同的结果；
解释分数前请阅读 `evaluation/metrics.json` 与各阶段报告。
运行指南中另有[结果路径](running.zh-CN.md#results)、
[故障排查](running.zh-CN.md#troubleshooting)和
[已有 GDS 验收](running.zh-CN.md#existing-gds)。
