[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_loopgain.spi](tb_loopgain.spi) | `loopgain` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_swing.spi](tb_swing.spi) | `swing` | `corner=tt; supply_V=1.8; temperature_C=27` | — | simulation.log |
| [tb_thd.spi](tb_thd.spi) | `thd` | `corner=tt; supply_V=1.8; temperature_C=27` | — | `thd_wave.dat` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_loopgain.spi" work/sim-01/testbench.spi
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


- `tb_loopgain.spi`: 原生测量输出环路增益、单位增益带宽、相位裕度和静态功耗。

- `tb_swing.spi`: 原生直流扫描测量闭环输出摆幅和跟踪情况。

- `tb_thd.spi`: thd_wave.dat 保存时间与 v(vout)。在 20 kHz 下跳过前 4 个启动周期，将后 4 周期（200..400 us）插值为 2048 个均匀样点，去除均值后投影第 1..9 次谐波。THD%=100*sqrt(sum(A2^2..A9^2))/A1。指定驱动电流测量还需把原生峰值电源电流与 loopgain 的静态功耗结合。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版电气验收只执行公开测试台 `tb_loopgain.spi`, `tb_swing.spi`, `tb_thd.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况。后仿使用同一测试条件，将 DUT 换为抽取网表。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
