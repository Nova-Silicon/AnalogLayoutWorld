[English](README.md) | [简体中文](README.zh-CN.md)

# 原生仿真测试台

以下文件来自本题已验证的前仿真测试电路，使用当前固定网表及对应的
SKY130 模型。每种分析提供一个代表条件，
不是完整 PVT/负载/随机种子矩阵。完整要求以任务英文说明为准。
具体电源、激励、负载和分析参数直接写在 SPICE 文件中。

## 文件与条件

| 文件 | 分析 | 示例条件 | ngspice 额外参数 | 原生输出 |
|---|---|---|---|---|
| [tb_noise.spi](tb_noise.spi) | `noise` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_pvt_dc.spi](tb_pvt_dc.spi) | `pvt_dc` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw`, `result.raw` |
| [tb_dropout_pvt.spi](tb_dropout_pvt.spi) | `dropout_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.03` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_nominal.spi](tb_loop_nominal.spi) | `loop_nominal` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_pvt.spi](tb_loop_pvt.spi) | `loop_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_loop_output_network.spi](tb_loop_output_network.spi) | `loop_output_network` | `corner=tt; vin=1.8; temp=27; cap=8e-07; esr=0.02; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_psrr_nominal.spi](tb_psrr_nominal.spi) | `psrr_nominal` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.001` | `-r analysis.raw` | `analysis.raw` |
| [tb_psrr_pvt.spi](tb_psrr_pvt.spi) | `psrr_pvt` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.03` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup_dynamic.spi](tb_startup_dynamic.spi) | `startup_dynamic` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_load_tran_dynamic.spi](tb_load_tran_dynamic.spi) | `load_tran_dynamic` | `corner=tt; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_tran_dynamic.spi](tb_line_tran_dynamic.spi) | `line_tran_dynamic` | `corner=tt; vin=1.98; temp=27; cap=1e-06; esr=0.05; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_startup_output_network.spi](tb_startup_output_network.spi) | `startup_output_network` | `corner=ss; vin=1.62; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_load_tran_output_network.spi](tb_load_tran_output_network.spi) | `load_tran_output_network` | `corner=ss; vin=1.62; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_line_tran_output_network.spi](tb_line_tran_output_network.spi) | `line_tran_output_network` | `corner=ss; vin=1.98; temp=125; cap=8e-07; esr=0.02; load=0.01` | `-r analysis.raw` | `analysis.raw` |
| [tb_mc.spi](tb_mc.spi) | `mc` | `corner=mc; vin=1.8; temp=27; cap=1e-06; esr=0.05; load=0.01; seed=72000` | `-r analysis.raw` | `analysis.raw` |

## 运行

从工作区执行下面的示例。每次新建一个运行目录，避免覆盖测量和波形。
换用其他测试台时，按照上表决定是否加 `-r analysis.raw`。

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_noise.spi" work/sim-01/testbench.spi
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


- `tb_noise.spi`: 对规定频带输出噪声谱积分。

- `tb_pvt_dc.spi`: 注意原生control把九个单点工作点（按负载 1、10、30 mA × VIN 1.62、1.8、1.98 V 的顺序）追加到result.raw，而非analysis.raw；每个点各自由瞬态上电求得，不是直流扫描。静态电流为 `abs(i(@vin[i])) - i(vlmeas)`，即扣除实测负载电流。

- `tb_dropout_pvt.spi`: VIN改为缓慢瞬态斜坡（10 ms内1.15→1.8 V，准静态）而非DC扫描；按输出误差边界插值，得到固定负载下压差。

- `tb_loop_nominal.spi`: 在gate_drive/gate断点作Middlebrook双注入：control块把两个AC plot依次追加到analysis.raw，第一个为VLOOP ac=1、IINJ ac=0，第二个为VLOOP ac=0、IINJ ac=1（向gate注入1 A）。由第一个求Tv=-v(gate_drive)/v(gate)，由第二个求Ti=-i(vloop)/(i(vloop)+1)，环路增益T=(Tv*Ti-1)/(Tv+Ti+2)；再由T求低频增益、首个单位增益交点、相位裕度和UGB。穿越频率附近OTA输出阻抗相对功率管栅阻抗不够小，只用电压注入会高估相位裕度，故不单独使用。保留各工况的负载/COUT/ESR。

- `tb_loop_pvt.spi`: 在gate_drive/gate断点作Middlebrook双注入：control块把两个AC plot依次追加到analysis.raw，第一个为VLOOP ac=1、IINJ ac=0，第二个为VLOOP ac=0、IINJ ac=1（向gate注入1 A）。由第一个求Tv=-v(gate_drive)/v(gate)，由第二个求Ti=-i(vloop)/(i(vloop)+1)，环路增益T=(Tv*Ti-1)/(Tv+Ti+2)；再由T求低频增益、首个单位增益交点、相位裕度和UGB。穿越频率附近OTA输出阻抗相对功率管栅阻抗不够小，只用电压注入会高估相位裕度，故不单独使用。保留各工况的负载/COUT/ESR。

- `tb_loop_output_network.spi`: 在gate_drive/gate断点作Middlebrook双注入：control块把两个AC plot依次追加到analysis.raw，第一个为VLOOP ac=1、IINJ ac=0，第二个为VLOOP ac=0、IINJ ac=1（向gate注入1 A）。由第一个求Tv=-v(gate_drive)/v(gate)，由第二个求Ti=-i(vloop)/(i(vloop)+1)，环路增益T=(Tv*Ti-1)/(Tv+Ti+2)；再由T求低频增益、首个单位增益交点、相位裕度和UGB。穿越频率附近OTA输出阻抗相对功率管栅阻抗不够小，只用电压注入会高估相位裕度，故不单独使用。保留各工况的负载/COUT/ESR。

- `tb_psrr_nominal.spi`: 从VIN/VOUT的AC响应计算100Hz、1kHz、100kHz、1MHz抑制比。

- `tb_psrr_pvt.spi`: 从VIN/VOUT的AC响应计算100Hz、1kHz、100kHz、1MHz抑制比。

- `tb_startup_dynamic.spi`: 从对应输出网络的瞬态波形计算t90、电源爬升后的建立时间和过冲。

- `tb_load_tran_dynamic.spi`: 从规定负载电流阶跃后的VOUT波形计算偏移和最后稳定时间。

- `tb_line_tran_dynamic.spi`: 从VIN/VOUT电源阶跃波形求偏移和最后稳定时间；部分组名标高电源，实际激励以测试台PWL为准。

- `tb_startup_output_network.spi`: 从对应输出网络的瞬态波形计算t90、电源爬升后的建立时间和过冲。

- `tb_load_tran_output_network.spi`: 从规定负载电流阶跃后的VOUT波形计算偏移和最后稳定时间。

- `tb_line_tran_output_network.spi`: 从VIN/VOUT电源阶跃波形求偏移和最后稳定时间；部分组名标高电源，实际激励以测试台PWL为准。

- `tb_mc.spi`: 单个失配工作点产生VOUT；输出电压良率必须用完整原始种子集合。

- 负载与工作点：输出负载由测试台 NMOS 共源共栅电流镜（`XTBLD_*`）吸取，其理想参考电流 `ILOAD` 即指令负载；`i(VLMEAS)` 是实际从 `vout` 拉走的电流。晶体管电流镜不能把 `vout` 拉到地以下。这些带负载的测试台中，所有工作点（包括每个瞬态的初始点）都由瞬态上电求得（`optran 0 0 0 <tstep> <tstop> 0`：不做牛顿/gmin/源步进直流求解），各分析从电路物理上会到达的稳态出发。后仿时保留这些负载与 `optran` 行。

## 本版验收覆盖范围

任务指令中的完整 SPEC（包括完整 PVT、负载范围及统计要求）仍是设计目标，没有删减。
本版后仿计分只执行公开测试台 `tb_dropout_pvt.spi`, `tb_line_tran_dynamic.spi`, `tb_line_tran_output_network.spi`, `tb_load_tran_dynamic.spi`, `tb_load_tran_output_network.spi`, `tb_loop_nominal.spi`, `tb_loop_output_network.spi`, `tb_loop_pvt.spi`, `tb_noise.spi`, `tb_psrr_nominal.spi`, `tb_psrr_pvt.spi`, `tb_pvt_dc.spi`, `tb_startup_dynamic.spi`, `tb_startup_output_network.spi` 中已经写明的工况、激励与分析，不再自动展开其余工况；将 DUT 换为抽取网表，保留相同测试条件。
失配／蒙特卡洛测试台 `tb_mc.spi` 保留用于参考电路资格检查，按原始完整固定种子集合及其统计或逐样本判据运行；这些资格结果单独记录，不参与提取后 DUT 的后仿计分或通过比例。
只对这些测试实际覆盖的指标计分；未覆盖的全范围性质和多样本统计标为未评测，不能把有限测试通过解释为完整 SPEC 通过。DRC、LVS 和提交要求不变。
