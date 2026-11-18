[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_source_combined.spi](tb_source_combined.spi) | `source_combined` | `corner=tt; temperature_C=27` | — | `result_op.raw`, `result_dc.raw`, `result_ac_vtran.raw`, `result_ac_vdd.raw`, `result_ac_vdc.raw`, `result_dc_vout.raw`, `result_tran.raw` |
| [tb_closed_loop_step.spi](tb_closed_loop_step.spi) | `closed_loop_step` | `corner=tt; temperature_C=27` | — | `transient.tsv` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_source_combined.spi" work/sim-01/testbench.spi
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

综合测试台输出 result_op.raw、result_dc.raw、result_ac_vtran.raw、result_ac_vdd.raw、result_ac_vdc.raw、result_dc_vout.raw 和 result_tran.raw。日志会打印部分中间测量，但源任务的最终 AC 指标由原始采样计算：1 Hz 增益；在 0 dB 两侧采样间作线性插值取得单位增益频率和相位；相位先减去首个 AC 采样的相位，再展开；CMRR/PSRR = 10 Hz 差模增益减去对应 DC .tf 增益。功耗、失调使用单位增益跟随器的工作点；直流范围按任务说明中的交越定义计算。独立阶跃测试台输出 transient.tsv（时间、输入、输出）；分别计算 4–4.9、9–9.9、14–14.9、19–19.9 us 内的最大绝对跟踪误差，再取最大值。保留本题初始化和模型/scale 设置，不要替换为其他任务的默认值。这些文件提供原生分析，不自动判断 SPEC 是否通过。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_closed_loop_step.spi`, `tb_source_combined.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
