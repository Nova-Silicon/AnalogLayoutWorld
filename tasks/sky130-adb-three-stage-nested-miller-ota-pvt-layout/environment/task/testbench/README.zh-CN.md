[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_pvt.spi](tb_pvt.spi) | `pvt` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_input_bias.spi](tb_input_bias.spi) | `input_bias` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_swing.spi](tb_swing.spi) | `swing` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_slew.spi](tb_slew.spi) | `slew` | `corner=tt; supply_V=1.8; temperature_C=27` | `-r analysis.raw` | `analysis.raw` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_pvt.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -r analysis.raw -o simulation.log testbench.spi
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


- `tb_pvt.spi`: 从原始OP/AC波形计算增益、UGB、相位裕度、共模误差、功耗及规定驱动FoM。

- `tb_input_bias.spi`: 从OP原始结果读取两输入源电流绝对值。

- `tb_swing.spi`: 根据源误差定义，从跟随器DC扫描取得连续有效输出区间。

- `tb_settling.spi`: 按原始目标与窗口从瞬态波形求最后进入容差带的时间和误差比例。

- `tb_slew.spi`: 按源阈值交点定义从瞬态波形计算上升/下降压摆率。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版后仿计分只执行公开测试台 `tb_pvt.spi`, `tb_settling.spi`, `tb_slew.spi`, `tb_swing.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况；将 DUT 换为抽取网表，保留相同测试条件。
`tb_input_bias.spi` 保留为诊断测试台；MOS 栅输入的直流电流在该模型中恒为零，因此此项不参与后仿计分。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
