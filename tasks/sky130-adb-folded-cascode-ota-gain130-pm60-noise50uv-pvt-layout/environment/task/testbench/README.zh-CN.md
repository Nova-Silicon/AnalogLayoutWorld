[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_op_ac.spi](tb_op_ac.spi) | `op_ac` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vdd=1.8; temp_c=27` | — | simulation.log |
| [tb_range.spi](tb_range.spi) | `range` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_op_ac.spi" work/sim-01/testbench.spi
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


- `tb_op_ac.spi`: 从 analysis.raw 计算返回比 -v(vout)/v(vinn)。增益取 10 Hz；带宽取首次下降穿越 0 dB 的频率，相位裕度使用该点展开后的相位。工作点输出偏差相对 0.9 V，功耗为 -VDD*i(vdd)。

- `tb_noise.spi`: 原生噪声测量输出文件指定频率范围内的积分输入参考噪声。

- `tb_range.spi`: 从原生 121 点直流扫描读取指令 v(vinp) 和输出 v(vout)。跟踪误差为 abs(Vout-command)，计算满足误差带的最大连续跟踪区间，并在区间边界插值。

- `tb_settling.spi`: 从 analysis.raw 读取时间、v(vinp)、v(vout)。分别处理上升和下降跳变：在各自原有窗口中求最后一次进入且此后保持在指定误差带内的时刻；静态误差取该窗口最后 5 ns 的平均输出。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_noise.spi`, `tb_op_ac.spi`, `tb_range.spi`, `tb_settling.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
