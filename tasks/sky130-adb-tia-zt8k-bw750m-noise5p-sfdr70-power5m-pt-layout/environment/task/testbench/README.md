[English](README.md) | [简体中文](README.zh-CN.md)

# Public native fixtures

Electrical acceptance in this benchmark version uses the three published TT/1.80 V/27°C fixtures below. The published SFDR fixture applies 100 MHz and 10 µA peak, the specified condition. Passing the public cases does not establish all 15 process-temperature points.

| Native fixture | Acceptance case |
|---|---|
| `tb_ac_tt.spi` | `ac_power__tt__27` |
| `tb_noise_tt.spi` | `noise__tt__27` |
| `tb_sfdr_tt.spi` | `sfdr__tt__27` |

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
