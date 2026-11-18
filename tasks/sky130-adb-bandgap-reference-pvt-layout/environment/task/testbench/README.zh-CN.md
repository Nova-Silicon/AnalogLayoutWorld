[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_op.spi](tb_op.spi) | `op` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup.spi](tb_startup.spi) | `startup` | `corner=tt; vdd=1.8; temp_c=27; ramp_s=1e-06` | `-r analysis.raw` | `analysis.raw` |
| [tb_ac.spi](tb_ac.spi) | `ac` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_step.spi](tb_line_step.spi) | `line_step` | `corner=tt; vdd=1.8; temp_c=27` | `-r analysis.raw` | `analysis.raw` |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=mc; vdd=1.8; temp_c=27; seed=61000` | `-r analysis.raw` | `analysis.raw` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_op.spi" work/sim-01/testbench.spi
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


- `tb_op.spi`: 读取工作点VREF和供电电流；功耗为max(0,-VDD*I(VDD))。温漂与线性调整率需要完整温度/电压扫描。

- `tb_startup.spi`: 对瞬态波形按规定电源爬升后的窗口测稳态范围、过冲、峰值电流，积分供电功率得到启动能量。

- `tb_ac.spi`: 从单位供电扰动的AC波形求规定频段内最大VREF传递幅值。

- `tb_noise.spi`: 对规定频带内输出噪声谱密度平方积分后开方。

- `tb_line_step.spi`: 根据对应工作点目标，从供电阶跃波形求参考电压偏移及最后进入容差带的时间。

- `tb_mc.spi`: 这里只产生一个工艺/失配工作点样本；保存种子和VREF，良率及样本标准差需要全部30个原始种子。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版后仿计分只执行公开测试台 `tb_ac.spi`, `tb_line_step.spi`, `tb_noise.spi`, `tb_op.spi`, `tb_startup.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况；将 DUT 换为抽取网表，保留相同测试条件。
失配／蒙特卡洛测试台 `tb_mc.spi` 保留用于参考电路资格检查，按原始完整固定种子集合及其统计或逐样本判据运行；这些资格结果单独记录，不参与提取后 DUT 的后仿计分或通过比例。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
