# DeepSeek Harness runtime

[English](README.md) | [简体中文](README.zh-CN.md) · [Documentation](../../docs/README.md)

The optional `analoglayoutworld_agents.deepseek_harness:DeepSeekHarnessAgent`
adapter uses the public DSH `0.2.1-rc.5` headless CLI through Harbor 0.24's standard
upload/exec interfaces. Harbor owns the Agent deadline.
Automatic model-generated session titles and Web tools are disabled by default.

Build the runtime from public npm before running a task. DSH is MIT-licensed;
dependency licenses and notices remain with their packages.

## Prepare once on Linux x86_64

Use Node 22 and the checked pnpm 11.7.0. The base EDA image already includes
Node 22 and native build tools; the build can also run on a Linux host with
Node 22, Python 3.12+, a C/C++ compiler and make. Nothing is installed globally.

From the benchmark checkout:

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

Choose a new output directory for each build. Use the reported `manifest_sha256`
with that exact bundle; the adapter checks the bundle before upload.
Keep `pnpm-lock.yaml` and `.pnpmfile.cjs` together for the frozen installation.

## Use with native Harbor

Install the benchmark's Harbor extra on the controller:

```bash
python -m pip install -e '.[harbor]'
```

Save the following JobConfig, replacing the checkout paths and manifest hash.
Keep the key in an environment variable; `${...}` is Harbor's credential reference.

The configuration uses three independent full-budget attempts. For a setup
diagnostic, set `n_attempts` to `1`.

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

Run it after exporting the selected key:

```bash
read -r -s -p 'Moonshot API key: ' MOONSHOT_API_KEY
export MOONSHOT_API_KEY
harbor run --config /path/to/job.json
```

The example selects DSH's shipped Moonshot provider. The native
`deepseek-official` route uses DSH's Messages provider, while other supported
routes use its shipped pi-ai provider. Do not route a chat-completions endpoint
through the native DeepSeek Messages adapter.

`max_output_tokens` is the per-response cap, not a whole-task token budget.
Set it for the actual model and context policy. The defaults retain a 256,000
context, a 196,000-token compaction trigger and an 8,192-token reserve, so an
output cap above 51,808 requires an explicit larger context or different
compaction setting. Invalid reserve combinations are rejected before execution.

Harbor collects stdout, session logs, tool records and the adapter's ATIF
projection. Inspect submission artifacts and verifier reports separately from
the Agent's completion status; see [result paths](../../docs/running.md#6-inspect-outputs-and-evidence).
