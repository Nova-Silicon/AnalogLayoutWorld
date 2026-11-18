[English](README.md) | [简体中文](README.zh-CN.md)

# Public native fixtures

The six published fixtures below are the post-layout scoring cases in this benchmark version. They retain their original TT, SS and FF conditions. Passing these fixtures does not establish the complete 27-point matrix.

The mismatch/Monte Carlo fixture `tb_mismatch_tt.spi` is retained for reference-circuit qualification using the original complete fixed seed set and its statistical or per-sample limits. Qualification results are recorded separately and do not contribute to the extracted DUT post-layout score or pass fraction.

| Native fixture | Acceptance case |
|---|---|
| `tb_ac_tt.spi` | `op_ac__tt__1.8__27` |
| `tb_ac_ss.spi` | `op_ac__ss__1.62__125` |
| `tb_noise_ff.spi` | `noise__ff__1.98__-40` |
| `tb_swing_tt.spi` | `swing__tt__1.8__27` |
| `tb_settling_ss.spi` | `settling__ss__1.62__125` |
| `tb_cm_recovery_ff.spi` | `cm_recovery__ff__1.98__-40` |

From the workspace, run:

```bash
source ./eda_env.sh
mkdir -p work/sim-01
cp "$ALB_TASK_DIR/testbench/tb_ac_tt.spi" work/sim-01/testbench.spi
ln -s "$ALB_TASK_DIR/circuit.spice" work/sim-01/dut.spice
printf '%s' "$ALB_NGSPICE_INIT" > work/sim-01/.spiceinit
(cd work/sim-01; SPICE_USERINIT_DIR="$PWD" ngspice -b -o run.log testbench.spi)
```

Choose the corresponding filename from the table for each analysis. The model
and DUT paths are local. Stimulus values, loads and measurements come from the
original public fixtures. For post-layout checks, make a working copy and point `dut.spice` to your extracted SPICE netlist using the same top-level ports.
Keep original conditions and limits. Logs and waveforms are native ngspice outputs.
Use the measurement definitions in `instruction.md` and the fixture comments;
the common environment guide explains native simulation and extraction commands.
