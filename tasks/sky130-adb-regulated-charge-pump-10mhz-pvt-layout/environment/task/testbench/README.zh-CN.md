[English](README.md) | [简体中文](README.zh-CN.md)

# 原生电荷泵测试台

`tb_charge_pump_regulated_ff_hot.spi` 来自 ADB 原始公开电气诊断测试台，
保留其电路、激励、负载、分析和测量区间。只调整本地路径、补充明确的标题及
几何单位，并加入提取后的 0.69 µm 电阻名称所需的静态 SPICE 模型绑定。
固定 DUT 网表没有修改。

| 分析 | 工况 | 测量 |
|---|---|---|
| 单次双实例瞬态 | FF、1.98 V、125°C；10 MHz；200 µs | 50 µA 负载使能态的输出和供电电流，无恒流负载关断态的供电电流；190–200 µs 测量 |

## 运行

在工作区执行：

```bash
source ./eda_env.sh
mkdir -p work/pump-sim
cp "$ALB_TASK_DIR/testbench/tb_charge_pump_regulated_ff_hot.spi" work/pump-sim/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/pump-sim/dut.spice
printf '%s\n' "${ALB_NGSPICE_INIT:?}" > work/pump-sim/.spiceinit
(
  cd work/pump-sim
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.spi
)
```

每次运行使用独立目录。本题使用原始 continuous 模型库、`.option scale=1e-6`
和 `set num_threads=1`，不启用 `ngbehavior=hsa`。
`.measure` 测量值写在 `simulation.log`。不要加 `-r`，否则 ngspice 可能不执行
瞬态 `.measure`。

后仿时让 `dut.spice` 指向提取的 DUT；如果提取器给出的子电路接口不同，只调整
实例的子电路名称及端口顺序。测试台内的 `sky130_fd_pr__res_xhigh_po_0p69`
三端子封装把实际提取长度和固定的 0.69 µm 宽度传给原 continuous
`sky130_fd_pr__res_xhigh_po` 模型。它不替换原电路电阻，不修改提取尺寸，
也不修改 PDK 模型。

## 本版检查的测量

| 标量 | 本版限值 |
|---|---|
| `vout_en_avg` | 2.4453–2.7027 V |
| `ripple_vpp` | 0–5 mVpp |
| `abs(i_avdd_en_avg)` | ≤200 µA |
| `abs(i_avdd_pd_avg)` | 此公开持续时钟瞬态中 ≤100 nA |

完整原始 SPEC 保留在 `instruction.md`。其中原始关断电流要求采用时钟保持低电平
的静态 DC 测量；此公开测试台对关断实例仍施加时钟。公开使能态的
FF/1.98 V/125°C/50 µA 压力点也不属于原始八个使能验收点。本版仅在这个公开
测试台中检查上表数值，不据此推断未测试的 DC/PVT 结果。私有后仿验收使用相同
公开激励、分析、模型、初始化和限值，将 DUT 换为提取网表。
