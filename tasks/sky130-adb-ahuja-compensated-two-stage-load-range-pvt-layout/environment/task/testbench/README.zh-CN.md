[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 模型选择

源测试台的 continuous 库缺少本题使用的固定宽度真实电阻定义：
`sky130_fd_pr__res_high_po_1p41`。
因此，本测试台使用原生 binned 入口
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice`。
请使用已给出的模型路径和本题初始化。当前完整前仿验证对应此入口，
不表示 continuous 与 binned 电气模型等价。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_light.spi](tb_light.spi) | `light` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_heavy.spi](tb_heavy.spi) | `heavy` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_step.spi](tb_step.spi) | `step` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |
| [tb_guard.spi](tb_guard.spi) | `guard` | `corner=tt; supply_v=1.8; temperature_C=27` | — | simulation.log |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_light.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

初始化由本题 `eda_env.sh` 中的 `ALB_NGSPICE_INIT` 给出，不能统一添加或删除
`ngbehavior=hsa`。每个测试台已经写入该题使用的模型路径、尺寸缩放和激励。
不要加跳过初始化的 `-n`。运行目录里的 `dut.spice` 指向被测电路。

进行后仿时，将 `dut.spice` 改为 PEX 网表。按实际提取的 `.subckt` 名称和
端口顺序调整测试台的 DUT 实例；只能适配名称和端口顺序，不能通过修改
电气连接、激励、负载或限值制造通过结果。详见工作区 `GUIDE.md`。

`.meas` 和 `print` 的结果在 `simulation.log` 中；`wrdata` / `write` 以及
`-r` 的波形文件在运行目录中。部分指标需要根据任务给定的测量定义从波形
计算，不能把 ngspice 返回码为 0 当成满足 SPEC。单个 MC 种子也不能代替
任务要求的失配统计。其他 PVT、负载、共模和种子需要按完整任务说明设置。

## 测量说明

四份原生测试台分别覆盖轻载 AC（20 pF）、重载 AC（200 pF）、跟随器阶跃（200 pF）及中间负载 AC 稳定性检查（63 pF），测量结果打印在 simulation.log。检查是否再次上穿 0 dB 时，如果不存在上升交越，ngspice 对 return_above_0db_hz 可能报告 out of interval 或测量失败；只有 AC 分析完整结束且其他必需 AC 测量有效时，这种预期的无交越结果才支持该项要求。分析中断造成的结果缺失不能证明稳定。阶跃测试从输入指令的 1% 交越开始，测量至 2–12 us 或 12–20 us 内最后一次 6 mV 误差边界交越的时间，并打印 12/20 us 的目标误差。保留所给 binned 模型及 scale=1e-6；旧上游示例采用不同模型/路径，不能直接互换。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_guard.spi`, `tb_heavy.spi`, `tb_light.spi`, `tb_step.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
