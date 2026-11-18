[English](README.md) | [简体中文](README.zh-CN.md)

# 公开原生测试台

本版后仿计分采用下表六份公开测试台，保留各自原有的 TT、SS、FF 条件。通过这些测试不表示完整 27 点矩阵通过。

失配／蒙特卡洛测试台 `tb_mismatch_tt.spi` 保留用于参考电路资格检查，按原始完整固定种子集合及其统计或逐样本判据运行；这些资格结果单独记录，不参与提取后 DUT 的后仿计分或通过比例。

| Native fixture | Acceptance case |
|---|---|
| `tb_ac_tt.spi` | `op_ac__tt__1.8__27` |
| `tb_ac_ss.spi` | `op_ac__ss__1.62__125` |
| `tb_noise_ff.spi` | `noise__ff__1.98__-40` |
| `tb_swing_tt.spi` | `swing__tt__1.8__27` |
| `tb_settling_ss.spi` | `settling__ss__1.62__125` |
| `tb_cm_recovery_ff.spi` | `cm_recovery__ff__1.98__-40` |

从工作区执行 `source ./eda_env.sh`，建立独立的 `work/sim-01`，将选中的
测试台复制为该目录的 `testbench.spi`，再用
`ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice` 指向待测网表。
把 `ALB_NGSPICE_INIT` 写入运行目录 `.spiceinit`，进入该目录后执行
`SPICE_USERINIT_DIR="$PWD" ngspice -b -o run.log testbench.spi`。
英文版本给出完整命令。每次仿真使用新目录，以免覆盖原始日志。

逐项选择表中对应文件，保留激励、负载及测量阈值。后仿时让 `dut.spice`
指向提取网表并保持同一顶层端口顺序。`.meas` 输出在日志中，波形分析可以通过
原生 `write`、`wrdata` 或 `-r` 保存所需数据；零退出码不表示电气规格通过。
