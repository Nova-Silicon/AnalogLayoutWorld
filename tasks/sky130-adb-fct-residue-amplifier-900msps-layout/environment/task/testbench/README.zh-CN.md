[English](README.md) | [简体中文](README.zh-CN.md)

# FCT 原生仿真测试台

这两个 TT 示例保持 AnalogDesignBench 原始完整验收测试台的时钟、
测量语句和负载。原始 `fct_fixture.spi`、`samples_32.inc` 已内联，
每份文件都能直接作为原生 SPICE 测试台运行。

| 文件 | 输入 | 工况 |
|---|---|---|
| `tb_10mv_tt.spi` | 差分峰值 10 mV，FFT 第 5 频点 | TT、1.8 V、27 C |
| `tb_20mv_tt.spi` | 差分峰值 20 mV，FFT 第 3 频点 | TT、1.8 V、27 C |

两者都使用 900 MS/s、64 个启动周期和 32 个计分保持样本。
完整规格要求将两种幅度分别运行 `tt`、`ss`、`ff`、`fs`、`sf`；
修改 `.lib` 工艺角即可。保持 continuous 模型及其微米参数约定；
模型库的 `models_global.spice` 已设置 `.option scale=1.0u`，
无需在测试台另加 scale 选项。

从工作区运行：

```bash
source ./eda_env.sh
mkdir -p work/fct-10mv-tt
cp "$ALB_TASK_DIR/testbench/tb_10mv_tt.spi" work/fct-10mv-tt/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/fct-10mv-tt/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/fct-10mv-tt/.spiceinit
(
  cd work/fct-10mv-tt
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

每次运行使用新目录。源 DUT 使用 `task/circuit.spice` 固定的真实 MIM
电容。后仿时令 `dut.spice` 指向 PEX 网表，必要时只适配 DUT 子电路名称
和端口顺序；不得为了通过而更改激励、负载、连接或指标。

日志提供保持样本 `outp_NNN`、`outn_NNN`，跟踪样本
`outp_early_NNN`、`outn_early_NNN`（NNN=000..031）和 `power_w`。
按任务说明计算增益、SFDR、共模、范围、保持变化和功耗。
全部 129 个必需原始数值都应完整且有限；退出码 0 不代表满足 SPEC。
不需要 256 点 FFT 或额外启动周期。测试台的理想开关、电容属于外部测试
条件，不属于应生成版图的 DUT。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_10mv_tt.spi`, `tb_20mv_tt.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
