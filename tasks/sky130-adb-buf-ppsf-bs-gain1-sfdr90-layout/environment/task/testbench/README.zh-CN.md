[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

这些文件沿用来源 AnalogDesignBench 的电气测试台，仅适配本地模型和 DUT
路径，删除重复打印 `.meas` 结果的 AC `print` 语句。
测量、激励、分析设置和限值保持不变。
前仿、后仿均使用 `ALB_MODEL_LIB` 选择的原 continuous SKY130 模型库，
并使用 `ALB_NGSPICE_INIT` 中的本题初始化。

| 文件 | 默认条件 | 原生输出 |
|---|---|---|
| `tb_ac_power.spi` | `tt`、1.80 V、27 C；1–40 MHz AC 及工作点 | `simulation.log` 中的增益、输入电流、功耗 |
| `tb_sfdr.spi` | `tt`、1.80 V、27 C；1 MHz 大信号正弦 | `dynamic.dat`，以及日志中的完成标记 |

完整矩阵包含 `tt`、`ff`、`ss`、`fs`、`sf` 五个工艺角。
每角运行一次 AC/DC，以及 1、11、41 MHz 三次 SFDR，共 20 次分析。
其他条件只需修改 `.lib` 工艺角和 `.param test_freq`。
保留固定的电源、偏置、共模源、负载及测量定义；完整限值见任务说明。

## 运行

从工作区执行：

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_ac_power.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/sim-01/.spiceinit
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

SFDR 使用新运行目录和 `tb_sfdr.spi`，同样设置 DUT 软链接及初始化。
不要使用会跳过初始化的 `-n`。这些 continuous 模型按微米解释网表中的
器件数字尺寸，不要静默增加缩放或替换模型库。

后仿时，将 `dut.spice` 指向 PEX 网表，并按抽取子电路的名称和端口顺序绑定
同一测试台。保持激励、负载及电气连接不变。

## 测量

AC 测试台以每十倍频程 100 点扫描 1–40 MHz。
`gain_min_vv` 是整个扫描上的最小差分电压增益。
同时报告 1 MHz、40 MHz 增益，以及 40 MHz 差分输入电流。
直流功耗为
`abs(VDD*I(VDD)) + abs(VCM*I(VCM)) + abs(VIN*I(VIN)) + abs(VIP*I(VIP))`。

瞬态仿真到 50 us，从 40 us 开始保存输出，最大步长为 1 ns。
`wrdata` 的四列为时间、VOP、时间、VON。
计算差分波形 `VOP - VON`，选取 `49 us <= time < 50 us` 的样点，
然后线性插值到 `49 us + k * 1 ns`、`k=0..999` 共 1000 点。
原始窗口至少应有 900 个样点；必要时用首对或末对样点外推端点。

对这 1000 个值执行矩形窗 DFT。基波频点索引为
`round(frequency_hz * 1e-9 * 1000)`，即 1、11 或 41。
频点 `b` 的幅值为复数 DFT 系数绝对值乘 2 再除以 1000。
除基波外，在索引 1 到 500 的全部频点中查找最大杂散，不包含直流。

- 基波增益 = 基波幅值 / 0.8。
- SFDR = `20 * log10(基波幅值 / max(最大杂散幅值, 1e-30))`。

来源规格均使用严格不等式。仿真进程退出码为零不能单独证明 SPEC 通过；
应检查每个要求的有限测量结果。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_ac_power.spi`, `tb_sfdr.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
