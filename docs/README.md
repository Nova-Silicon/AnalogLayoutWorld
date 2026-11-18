# Documentation

**English** | [简体中文](README.zh-CN.md) · [Quick Start](../README.md#quick-start)

Start with the README's Quick Start: install the benchmark, choose a model provider’s
API or a self-hosted endpoint, and run one task. The guides below explain how to
extend that same setup; you do not need to read them all before the first run.

| What you want to do | Guide | What it covers |
|---|---|---|
| Configure and run experiments | [Running experiments](running.md) | Installation, the two Quick Start connection modes, one task or all 40, repetitions, concurrency, results and troubleshooting |
| Change the harness or model provider | [Harnesses and APIs](agents.md) | OpenCode, Kimi Code, Claude Code, Codex, Qwen Code and DSH; credentials and supported API protocols |
| Understand submissions and scores | [Task and scoring protocol](protocol.md) | Required GDS/source files, time budgets, independent verification, score components and report fields |
| Use or rebuild the EDA environment | [EDA image](images.md) | Public image, system requirements, an optional offline check and source rebuild |
| Prepare DeepSeek Harness | [DSH setup](../harnesses/deepseek-harness/README.md) | Build its public runtime once and launch it through Harbor |
| Inspect the supplied PDK resources | [SKY130 resources](../docker/pdk/README.md) | Resource contents, source licenses and optional packaging checks |

## Choose your next step

- **The first task ran:** follow [batch runs](running.md#all-tasks) and
  [formal experiment settings](running.md#formal-evaluation).
- **You have a custom model URL:** follow [self-hosted / compatible endpoints](running.md#self-hosted-url).
- **You already have a GDS:** use [independent GDS evaluation](running.md#existing-gds), without a model API.
- **A run failed:** first distinguish an Agent error from a completed nonpassing
  design using [results](running.md#results), then check [troubleshooting](running.md#troubleshooting).

Each task's `instruction.md` defines its circuit, top cell, ports and submission
requirements. Run `alw list` from the installed checkout to see all 40 task IDs.
Tasks use the fixed `analoglayoutworld-paper-v1` evaluation configuration.

All user guides have English and Chinese counterparts. Software and task
attribution are recorded in [license scope](../LICENSING.md) and
[third-party notices](../THIRD_PARTY_NOTICES.md).
