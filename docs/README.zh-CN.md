# 使用文档

[English](README.md) | **简体中文** · [Quick Start](../README.zh-CN.md#快速开始)

先完成 README 的 Quick Start：安装评测、选择服务商 API 或自部署地址，再运行一道题。
下列文档用于在这套配置上继续使用，不必全部读完才开始运行。

| 你希望做什么 | 对应文档 | 内容 |
|---|---|---|
| 配置并启动实验 | [运行指南](running.zh-CN.md) | 安装、Quick Start 的两种连接方式、单题或全部 40 题、重复次数、并发、结果与故障排查 |
| 更换 harness 或模型服务 | [Harness 与 API](agents.zh-CN.md) | OpenCode、Kimi Code、Claude Code、Codex、Qwen Code 和 DSH 的凭据、协议及命令 |
| 理解提交要求和评分 | [任务与评分协议](protocol.zh-CN.md) | GDS/源码要求、时间预算、独立验收、计分项目和报告字段 |
| 使用或重建 EDA 环境 | [EDA 镜像](images.zh-CN.md) | 公开镜像、环境要求、可选离线检查与源码构建 |
| 准备 DeepSeek Harness | [DSH 配置](../harnesses/deepseek-harness/README.zh-CN.md) | 构建一次公开运行时，再通过 Harbor 启动 |
| 了解附带的 PDK 资源 | [SKY130 资源](../docker/pdk/README.zh-CN.md) | 资源内容、来源许可及可选打包检查 |

## 跑通 Quick Start 后

- **准备运行更多题目：**阅读[批量运行](running.zh-CN.md#all-tasks)和[正式实验设置](running.zh-CN.md#formal-evaluation)。
- **需要填写自己的模型 URL：**阅读[自部署／兼容服务](running.zh-CN.md#self-hosted-url)。
- **已经有 GDS：**使用[已有 GDS 的独立验收](running.zh-CN.md#existing-gds)，无需模型 API。
- **运行不成功：**先按[结果说明](running.zh-CN.md#results)区分 Agent 报错与设计不通过，再查[故障排查](running.zh-CN.md#troubleshooting)。

每道题的 `instruction.md` 规定电路、顶层 cell、端口和提交要求。
在安装后的仓库中运行 `alw list`，可查看全部 40 道题的 ID。
任务使用固定的 `analoglayoutworld-paper-v1` 验收配置。

全部使用指南均提供中英文对应版本。软件和任务的许可与归属信息见
[许可范围](../LICENSING.md)及[第三方声明](../THIRD_PARTY_NOTICES.md)。
