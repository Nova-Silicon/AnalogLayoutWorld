[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_pvt.spi](tb_pvt.spi) | `pvt` | `corner=tt; supply_V=1.8; temperature_C=27; load=0.001` | — | simulation.log |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=tt; supply_V=1.8; temperature_C=27; seed=12345` | — | simulation.log |

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


- `tb_pvt.spi`: 原生OP/环路/PSRR标量另含有源MOS余量；必须读取原生器件余量输出，不能只看VOUT。静态电流扣除的是实测负载 `load_current_a = i(VLMEAS)`；测试台电流镜晶体管 `XTBLD_*` 不属于 DUT，不参加器件裕量检查。

- `tb_mc.spi`: 每个种子产生1mA和5mA两个VOUT样本；各负载分别在完整种子集合上计算均值±3倍样本标准差。

- 负载与工作点：输出负载由测试台 NMOS 低压共源共栅电流镜（`ETBLD`/`VTBLD` 使共栅管栅压比参考管栅压高 0.2 V）（`XTBLD_*`）吸取，其理想参考电流 `ILOAD` 即指令负载；`i(VLMEAS)` 是实际从 `vout` 拉走的电流。晶体管电流镜不能把 `vout` 拉到地以下。这些带负载的测试台中，所有工作点（包括每个瞬态的初始点）都由瞬态上电求得（`optran 0 0 0 <tstep> <tstop> 0`：不做牛顿/gmin/源步进直流求解），各分析从电路物理上会到达的稳态出发。后仿时保留这些负载与 `optran` 行。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版后仿计分只执行公开测试台 `tb_pvt.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况；将 DUT 换为抽取网表，保留相同测试条件。
失配／蒙特卡洛测试台 `tb_mc.spi` 保留用于参考电路资格检查，按原始完整固定种子集合及其统计或逐样本判据运行；这些资格结果单独记录，不参与提取后 DUT 的后仿计分或通过比例。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
