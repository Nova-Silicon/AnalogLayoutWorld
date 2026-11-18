[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_loop.spi](tb_loop.spi) | `loop` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_settling.spi](tb_settling.spi) | `settling` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_ranges.spi](tb_ranges.spi) | `ranges` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_cmfb_recovery.spi](tb_cmfb_recovery.spi) | `cmfb_recovery` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=tt; supply_V=1.8; temperature_C=27; seed=41000` | — | simulation.log |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_loop.spi" work/sim-01/testbench.spi
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


- `tb_loop.spi`: 原生标量含环路增益/UGB/相位裕度、闭环差模增益、输出共模误差和功耗。

- `tb_settling.spi`: 原生瞬态测量和let表达式输出静态/动态误差及双向建立时间，保留各题自己的容差和窗口。

- `tb_noise.spi`: 原生noise分析打印积分后的差分输出噪声output_noise_vrms。

- `tb_ranges.spi`: 原生DC扫描按局部增益下降定义输出范围；Gain1原要求仅名义范围，Gain8要求全部30个PVT范围。

- `tb_cmfb_recovery.spi`: 原生瞬态测量共模静态误差、最大偏移和指定恢复时刻的残差。

- `tb_mc.spi`: 原生输出为10Hz共模/电源馈通增益；CMRR/PSRR需用名义loop台闭环差模增益减相应馈通增益(dB)，并覆盖全部20种子。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版后仿计分只执行公开测试台 `tb_cmfb_recovery.spi`, `tb_loop.spi`, `tb_noise.spi`, `tb_ranges.spi`, `tb_settling.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况；将 DUT 换为抽取网表，保留相同测试条件。
失配／蒙特卡洛测试台 `tb_mc.spi` 保留用于参考电路资格检查，按原始完整固定种子集合及其统计或逐样本判据运行；这些资格结果单独记录，不参与提取后 DUT 的后仿计分或通过比例。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
