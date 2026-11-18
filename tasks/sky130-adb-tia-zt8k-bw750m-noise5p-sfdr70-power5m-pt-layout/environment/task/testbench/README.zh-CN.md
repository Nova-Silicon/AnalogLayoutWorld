[English](README.md) | [简体中文](README.zh-CN.md)

# 公开原生测试台

本版电气验收采用下表三份 TT/1.80 V/27°C 公开测试台。公开 SFDR 激励为 100 MHz、10 µA 峰值，即规格要求的条件。公开测试通过不表示全部 15 个工艺温度点通过。

| Native fixture | Acceptance case |
|---|---|
| `tb_ac_tt.spi` | `ac_power__tt__27` |
| `tb_noise_tt.spi` | `noise__tt__27` |
| `tb_sfdr_tt.spi` | `sfdr__tt__27` |

从工作区执行 `source ./eda_env.sh`，建立独立的 `work/sim-01`，将选中的
测试台复制为该目录的 `testbench.spi`，再用
`ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice` 指向待测网表。
把 `ALB_NGSPICE_INIT` 写入运行目录 `.spiceinit`，进入该目录后执行
`SPICE_USERINIT_DIR="$PWD" ngspice -b -o run.log testbench.spi`。
英文版本给出完整命令。每次仿真使用新目录，以免覆盖原始日志。

逐项选择表中对应文件，保留激励、负载及测量阈值。后仿时让 `dut.spice`
指向提取网表并保持同一顶层端口顺序。`.meas` 输出在日志中，波形分析可以通过
原生 `write`、`wrdata` 或 `-r` 保存所需数据；零退出码不表示电气规格通过。
