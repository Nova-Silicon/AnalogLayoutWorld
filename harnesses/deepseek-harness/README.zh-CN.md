# DeepSeek Harness 运行时

[English](README.md) | [简体中文](README.zh-CN.md) · [文档索引](../../docs/README.zh-CN.md)

可选的 `analoglayoutworld_agents.deepseek_harness:DeepSeekHarnessAgent`
适配器通过 Harbor 0.24 的标准上传与执行接口，使用公开发布的 DSH
`0.2.1-rc.5` 无界面 CLI。Agent 的运行时限由 Harbor 管理。
默认关闭由模型自动生成会话标题的功能和 Web 工具。

运行任务前，先使用公开 npm 源构建运行时。DSH 采用 MIT 许可；
依赖项的许可和声明保留在各自的软件包中。

## 在 Linux x86_64 上准备一次

使用 Node 22 和已核对的 pnpm 11.7.0。基础 EDA 镜像已经包含
Node 22 和原生构建工具；也可以在具备 Node 22、Python 3.12+、
C/C++ 编译器及 make 的 Linux 主机上构建。所有组件均无需全局安装。

在基准仓库根目录执行：

```bash
npm --userconfig harnesses/deepseek-harness/npmrc.empty \
  --globalconfig /dev/null install --prefix .cache/alw-pnpm --no-save \
  --ignore-scripts --no-audit --no-fund --registry https://registry.npmjs.org \
  pnpm@11.7.0
python scripts/build_dsh_bundle.py \
  --node "$(command -v node)" \
  --pnpm .cache/alw-pnpm/node_modules/pnpm/bin/pnpm.cjs \
  --output .cache/dsh-0.2.1-rc.5 --cache .cache/pnpm-store
```

每次构建都应选择新的输出目录。将报告中的 `manifest_sha256`
与对应的运行时包一起使用；适配器会在上传前检查运行时包。
冻结依赖安装时，需将 `pnpm-lock.yaml` 和 `.pnpmfile.cjs` 保持在一起。

## 使用原生 Harbor 运行

在控制端安装基准的 Harbor 可选依赖：

```bash
python -m pip install -e '.[harbor]'
```

保存以下 JobConfig，并替换仓库路径和 manifest 哈希。
将密钥保存在环境变量中；`${...}` 是 Harbor 的凭据引用语法。

此配置运行三次相互独立、完整预算的尝试。
诊断安装配置时，可将 `n_attempts` 设为 `1`。

```json
{
  "job_name": "my-dsh-run",
  "n_attempts": 3,
  "n_concurrent_trials": 1,
  "retry": {"max_retries": 0},
  "environment": {"type": "docker", "delete": true},
  "agents": [{
    "import_path": "analoglayoutworld_agents.deepseek_harness:DeepSeekHarnessAgent",
    "model_name": "kimi-k2.6",
    "env": {"MOONSHOT_API_KEY": "${MOONSHOT_API_KEY}"},
    "kwargs": {
      "bundle_path": "/YOUR/CHECKOUT/.cache/dsh-0.2.1-rc.5",
      "manifest_sha256": "REPLACE_WITH_THE_64_HEX_DIGIT_BUILD_RESULT",
      "provider": "moonshotai-cn",
      "api": "openai-completions",
      "api_url": "https://api.moonshot.cn/v1",
      "api_key_env": "MOONSHOT_API_KEY",
      "max_output_tokens": 32768,
      "generate_titles": false,
      "disable_web_tools": true
    }
  }],
  "tasks": [{"path": "/YOUR/CHECKOUT/tasks/sky130-adb-ota-5t-gain40-pm60-noise50uv-pvt-layout"}]
}
```

导出所选服务的密钥后运行：

```bash
read -r -s -p 'Moonshot API key: ' MOONSHOT_API_KEY
export MOONSHOT_API_KEY
harbor run --config /path/to/job.json
```

示例选择 DSH 自带的 Moonshot provider。原生的 `deepseek-official`
路由使用 DSH 的 Messages provider，其他受支持的路由则使用其自带的
pi-ai provider。请勿将 Chat Completions 接口交给原生 DeepSeek Messages
适配器处理。

`max_output_tokens` 是单次响应的上限，而非整个任务的 token 预算。
应根据实际模型和上下文策略设置。默认保留 256,000 token 上下文、
196,000 token 压缩触发阈值和 8,192 token 预留，因此输出上限超过
51,808 时，需要显式扩大上下文或调整压缩设置。
无效的预留组合会在执行前被拒绝。

Harbor 会收集标准输出、会话日志、工具记录，以及适配器生成的 ATIF 投影。
请分别检查提交产物、验收报告和 Agent 完成状态；相关位置见
[结果路径](../../docs/running.zh-CN.md#6-检查输出与证据)。
