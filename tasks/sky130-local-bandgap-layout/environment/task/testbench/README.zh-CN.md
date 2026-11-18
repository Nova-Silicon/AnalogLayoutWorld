[English](README.md) | [简体中文](README.zh-CN.md)

# 原生带隙仿真示例

以英文版本为准。

这里是用于固定 DUT 的普通 ngspice 测试台。`tb_temperature.spi`
演示 `tt`、VDD=1.8 V 下完整的 −40–125 °C 温度扫描。
`tb_startup.spi` 演示 `tt`、27 °C、VDD=1.8 V 下的启动。
两者均使用 10 pF 和 100 MΩ 外部负载。
任务说明给出了全部 27 条温扫、53 条启动条件以及所有限值。

## 运行原理图仿真

从工作区执行：

```bash
source ./eda_env.sh
mkdir -p work/sim-temperature
cp "$ALB_TASK_DIR/testbench/tb_temperature.spi" work/sim-temperature/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-temperature/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-temperature/.spiceinit
(
    cd work/sim-temperature
    SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

运行启动仿真时，新建工作目录并改为复制 `tb_startup.spi`。
测试台选择的 continuous 模型库位于
`/opt/analog-layout/pdks/sky130/sky130A/libs.tech/combined/continuous/`。
保留 `set ngbehavior=hsa`、`set num_threads=1` 和 `.option scale=1e-6`。
不要使用 `ngspice -n`，它会禁止读取初始化文件。

检查其他必测条件时，在 `.lib` 中选择角点，并设置电源值。
温扫仍须以 5 °C 步长覆盖全部 34 个点。
启动仿真则设置 `.temp` 和 `alter @VDD[pwl]` 命令中的目标电压，
保留 10 µs 斜坡及 2 ms 仿真时长。

## 读取原生输出

`simulation.log` 包含 ngspice 消息和 `.meas` 标量结果。

- 温扫：`ref_min`、`ref_max` 和 `ref_25` 是电压测量。
  `temp_curve.dat` 有四列数值：温度、Vref、再次出现的温度、I(VDD)。
  确认包含 −40、−35、…、125 °C 共 34 行，且所有值有限。
  盒式温度系数计算为
  `(max(Vref) − min(Vref)) / Vref(25 °C) / 165 × 10^6` ppm/K。
  静态电流取同一组数据的 `max(−I(VDD))`。
  电流符号对应测试台中的电源方向。
- 启动：`ref_end` 测量 1 ms 时的 Vref；
  `ref_min_steady` 和 `ref_max_steady` 测量 1–2 ms 内的电压极值。
  它们均须位于任务规定的电压窗口内。
  名称中的 `steady` 指该测量窗口，并不额外要求完全稳态。
  1 µs 时的 `ref_start` 只是诊断值，不是另一项指标。
  `startup.dat` 包含时间和 Vref，可用于查看瞬态波形。

测量缺失、非有限数值或温扫不完整都不算检查成功。

## 仿真提取后的 DUT

在新的工作目录中，将原生提取网表链接或复制为 `dut.spice`。
按照实际 `.subckt` 声明修改 `XDUT` 的子电路名称及端口顺序；
原理图参考使用 `bandgap vdd vss vref`。
保持规定的外部激励和负载，保留提取的寄生元件及器件几何。

每个示例均包含以下原生 SPICE 模型绑定：

```spice
.subckt sky130_fd_pr__res_high_po_0p35 p n b l=1 mult=1
XR p n b sky130_fd_pr__res_high_po w=0.35 l={l} mult={mult}
.ends sky130_fd_pr__res_high_po_0p35
```

原始原理图使用 continuous 模型 `sky130_fd_pr__res_high_po`，
显式指定 W=0.35 µm；原生提取则以 `sky130_fd_pr__res_high_po_0p35`
命名该物理宽度。上述绑定向原 continuous 模型提供固定宽度，并传递
实际提取长度、统计 `mult` 参数和三个端子。
实例自身的并联 `m` 倍数保留在该实例上。
其余提取器件和寄生均保持不变。

仿真原始 `circuit.spice` 时，该绑定没有被调用。
后仿时，它不会代入原理图长度、标称电阻值或不同的电阻宽度。
不得将 continuous 库替换为 binned 库，也不得使用
`lvs_reference.spice` 进行仿真。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_startup.spi`, `tb_temperature.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
