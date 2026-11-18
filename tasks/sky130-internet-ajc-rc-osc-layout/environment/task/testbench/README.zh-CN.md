[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 模型选择

早期独立测试台使用了基准自行编写的别名，因为 continuous 库缺少
`sky130_fd_pr__res_xhigh_po_1p41`；该别名不是 SKY130 官方模型。
本测试台通过 `/opt/analog-layout/pdks/sky130/sky130A/libs.tech/ngspice/sky130.lib.spice` 加载原生定义。
请使用本题已经给出的模型路径和初始化。当前完整前仿验证对应此原生 binned
入口，并不证明它与早期 continuous 加自建别名的模型电气等价。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_rc_osc.spi](tb_rc_osc.spi) | `rc_osc` | `corner=tt; supply_V=1.8; temperature_C=27` | — | `wave.tsv` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_rc_osc.spi" work/sim-01/testbench.spi
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

瞬态测试台输出 wave.tsv，四列依次为时间、使能电压、输出电压和 I(VDD)，不直接打印振荡器的派生指标。保留完整 6 ms 波形。对输出穿越 VDD/2 的时刻作插值：使用严格位于 1–2.5 ms 的上升沿，计算频率 = 1/周期中位数、周期变化率 =（最大周期－最小周期）/平均周期，以及每个周期的高电平时间占比。启动、重启时间分别是 100.01 us、4.00001 ms 之后首个上升沿相对该起点的延迟。启用功耗为 1–2.5 ms 采样窗口内电源电流的时间平均值乘以 -VDD；关闭电流为 3.3–3.8 ms 内 I(VDD) 的负采样均值，关闭输出为该窗口内的最大输出电压。依据任务定义自行处理波形；测试台本身不输出通过或失败结论。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_rc_osc.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
