# SKY130 版图任务环境

[English](GUIDE.md) | [简体中文](GUIDE.zh-CN.md)

工作区提供任务输入和软件使用说明。布局、布线、脚本编写及调试由你完成。

## 启用环境与读取任务

```bash
source ./eda_env.sh
```

- `task/circuit.spice`：固定电路及器件尺寸，也是仿真 DUT。
- 任务说明：功能、固定端口/器件、工况、激励、测量和电气规格。
  Harbor 将任务说明作为提示词提供。
- `task/testbench/`：随题提供的仿真输入和外部 fixture。
- [DEVICE_API.zh-CN.md](DEVICE_API.zh-CN.md)：当前安装的 SKY130 器件/接触孔参数、端口、常用层，以及固定 DRC deck 的基础规则索引。

交付 `submission/layout.gds`，顶层名称和端口应符合固定网表和任务说明；
生成代码保存到 `submission/src/`。临时脚本、抽取结果和仿真日志放到 `work/`。
应尽可能紧凑地放置器件与布线，提高面积利用率，同时满足任务电气与工艺要求。
自查结果不作为正式成绩；验收会重新读取提交的 GDS。

## 软件与 PDK

| 能力 | 已安装接口或路径 |
|---|---|
| Python | `/opt/analog-layout/python/bin/python3.12` |
| 编程生成版图 | `gdsfactory`，也可直接使用 `klayout.db` |
| SKY130 PCell | `/opt/analog-layout/pdks/sky130/python/sky130` |
| KLayout | `klayout`；支持批处理及 Python 数据库接口 |
| DRC deck | `/opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc` |
| LVS 比较 | `$ALB_NETGEN_BIN`，上游 SKY130 配置为 `$ALB_NETGEN_SETUP` |
| Magic | `magic` |
| Magic 启动文件 | `/opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc` |
| ngspice | `ngspice` |
| 本题选定的仿真模型入口 | 加载 `eda_env.sh` 后执行 `printf '%s\n' "$ALB_MODEL_LIB"` |

版本见 `/opt/analog-layout/runtime.json`。使用当前安装的 PDK，不要另装同名包替换。
Python 器件入口：

```python
import gdsfactory as gf
import sky130
sky130.PDK.activate()
# Device functions are in sky130.pcells; layers are in sky130.LAYER.
```

常用几何接口示例（只演示 API，不是本题的布局方案）：

```python
c = gf.Component("api_example")
mos = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True,
)
ref = c.add_ref(mos)
ref.drotate(90)       # Angle in degrees.
ref.dmove((10, 10))   # Coordinates in µm.
p = ref.ports["DRAIN"] # Transformed upstream port metadata; see DEVICE_API.zh-CN.md for limits.
print(p.dcenter, p.dwidth, p.orientation, p.layer)
# ports is a container indexed by name; iteration yields Port objects directly.
for port in ref.ports:
    print(port.name, port.dcenter, port.dwidth, port.orientation, port.layer)
c.add_polygon([(0, 0), (2, 0), (2, 1), (0, 1)], layer=sky130.LAYER.met1drawing)
c.add_label("example_label", position=(1, 0.5), layer=sky130.LAYER.met1label)
c.write_gds("work/api_example.gds", with_metadata=False)
```

`add_ref` 保留层级，移动实例不移动原始 PCell；需要修改库组件时先 `mos.copy()`，
避免修改缓存对象。金属重叠不代表跨层连通，必须按 PDK 用接触孔/过孔连接。
当前版本的 `ref.ports` 不是 Python `dict`，没有 `.items()`；需要键值映射时可自行写
`{port.name: port for port in ref.ports}`，不必读取库实现。
器件多个接点不自动形成电路总线；GDS 标签与 Python 端口 metadata 也是两件事。
标准电气布线 API 可用
`gf.routing.route_single_electrical(c, port1, port2, layer=sky130.LAYER.met1drawing, width=0.5, cross_section="metal1")`；
它不替你完成整个电路的放置、避障和工艺检查。

使用 `get_polygons` 读取组件几何。`layers` 指定要查询的图层；
`by="tuple"` 返回以 `(layer, datatype)` 为键、各层多边形列表为值的字典。
`merge=False` 保留各个多边形，不进行合并。

```python
polygons_by_layer = c.get_polygons(
    merge=False, by="tuple", layers=[(68, 20)],
)
for polygon in polygons_by_layer.get((68, 20), []):
    print(polygon.bbox())
```

返回的 `klayout.db.Polygon` 坐标及包围盒使用数据库单位；
将坐标值乘以 `c.kcl.dbu` 即可换算成 µm。
使用 `help(c.get_polygons)` 可查询当前安装版本的接口说明。

开始布线前可查 [DEVICE_API.zh-CN.md](DEVICE_API.zh-CN.md) 的“参数、坐标与接触孔接口”和“当前 DRC deck 的基础规则索引”：
切孔函数不一定生成上下层金属；满足最小线宽也不代表满足最小面积、接触孔包围或浮空金属规则。
其中列出的 5 nm 网格、常用 LI/M1/M2 与 contact/via 数值都带固定 deck 的位置，
完整工艺条件以本环境安装的 deck 为准。

## 离线参考资料（可选）

如需完整或高级用法，可按需查阅以下本地官方资料。
下列路径均相对于 `/opt/analog-layout/`：

| 资料 | 本地文件 |
|---|---|
| Magic 8.3 命令参考 | `tools/magic/lib/magic/doc/html/commands.html`；GDS、展开与抽取命令的纯文本在 `tools/magic/lib/magic/doc/text/` |
| ngspice 46 手册 | `tools/ngspice/share/doc/ngspice/ngspice-46-manual.txt`；同目录的 `.pdf` 保留原版附图和公式排版 |
| SKY130 工艺、图层与器件 | `pdks/sky130/docs/skywater-pdk/rules.rst`；具体入口见 [DEVICE_API.zh-CN.md](DEVICE_API.zh-CN.md) |

KLayout 自带内置手册；gdsfactory 和 `klayout.db` 提供原生 API 说明，
可按需通过 Python 的 `help()` 或 `pydoc` 离线查阅类、函数和方法的参数、返回值及用法。

## KLayout 原生 DRC

本题继续使用已安装的 KLayout DRC 规则。将 `TOP` 替换为固定网表的顶层名。
从工作区根目录运行，每次使用新目录并保存报告。

```bash
mkdir -p work/drc-01
klayout -b -r /opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc \
  -rd input="$PWD/submission/layout.gds" -rd top_cell=TOP \
  -rd report="$PWD/work/drc-01/report.lyrdb" -rd thr=2 \
  -rd feol=true -rd beol=true -rd offgrid=true -rd floating_met=true \
  -rd sram_exclude=false -rd seal=false -rd info=false
```

查看 `report.lyrdb` 中的违例；可以用 KLayout 打开这个报告。

## Magic + Netgen 原生 LVS

本题由 Magic 从 GDS 抽取器件和连接，再由 Netgen 使用已安装的上游 SKY130
配置，与 **`task/circuit.spice`** 比较。
不要修改上游工艺文件或 Netgen 配置，也不要关闭器件参数检查。

保留固定电路中每个 MOS 的体端连接，包括独立 NMOS 体端网络。
`ext2spice global off` 保留实际抽取连接，不会替你创建隔离阱或补接体端。

建立 `work/lvs-01/`，将以下内容保存为 `work/lvs-01/extract.tcl`。
按本题替换 `TOP` 和按顺序排列的端口列表。GDS 中必须已有落在正确导体上的
同名端口标签。临时展平单元 `TOP_lvs` 不能与输入 GDS 中已有单元重名。

```tcl
set gds_file [file normalize ../../submission/layout.gds]
set top TOP
set ordered_ports {PORT_1 PORT_2 PORT_3}
set flat_top ${top}_lvs

drc off
gds readonly true
gds rescale false
gds read $gds_file
load $top
select top cell
flatten $flat_top
load $flat_top
select top cell
expand

# Set port attributes on existing conductor labels. Do not add labels or wires.
set index 1
foreach pin $ordered_ports {
    if {[port $pin exists]} {
        port $pin index $index
    } else {
        port $pin make $index
    }
    incr index
}

extract style {ngspice()}
extract do local
extract no capacitance
extract no resistance
extract no coupling
extract no adjust
extract all

ext2spice lvs
ext2spice format ngspice
ext2spice scale off
ext2spice merge none
ext2spice hierarchy off
ext2spice subcircuit top on
ext2spice global off
ext2spice short none
ext2spice extresist off
ext2spice rthresh infinite
ext2spice cthresh infinite
ext2spice -o extracted.spice ${flat_top}.ext
quit -noprompt
```

先运行 Magic，再运行 Netgen。Netgen 命令中的 `TOP_lvs` 和 `TOP` 也要替换。

```bash
mkdir -p work/lvs-01
# Save work/lvs-01/extract.tcl from the example above first.
(
  cd work/lvs-01
  "$ALB_MAGIC_BIN" -dnull -noconsole -rcfile "$ALB_MAGIC_RC" \
    extract.tcl > magic.log 2>&1
)
"$ALB_NETGEN_BIN" -batch lvs \
  "$PWD/work/lvs-01/extracted.spice TOP_lvs" \
  "$PWD/task/circuit.spice TOP" \
  "$ALB_NETGEN_SETUP" "$PWD/work/lvs-01/report.out" -json \
  > work/lvs-01/netgen.log 2>&1
```

输出包括 `magic.log`、`extracted.spice`、`netgen.log`、`report.out` 和
`report.json`。比较前先核对抽取 `.subckt` 的名称和端口顺序。
缺少标签、未知抽取方式、工具报错都不算成功，即使进程退出码为零。

`ext2spice short none` 不会为了保留同网端口而插入人工电阻。
如果顶层端口丢失，应检查真实导体上的标签及连接，不能后改抽取网表制造匹配。
`merge none` 把器件合并与参数比较交给未修改的 Netgen 配置处理。

阅读完整 Netgen 报告：拓扑匹配不够，器件参数、网络、器件和顶层端口也必须匹配。
尤其是 `Circuits match uniquely` 可能与器件参数错误同时出现。
不能仅凭该行文字、退出码或 `report.out` 存在认定 LVS 通过。

本 LVS 抽取不包含寄生 R/C。后仿使用下一节单独的 PEX 流程。

## Magic 原生寄生抽取

以下是**当前镜像的 SKY130 `ngspice()` 抽取方式**，不是任意 PDK 通用配方。
运行前先看固定网表和任务说明中的顶层、端口顺序与衬底连接要求。
GDS 必须已有这些端口的文字标签，标签落在正确的导体上；仅在 Python 对象中定义
`port` metadata 不等于 GDS 中已有标签。

先在工作区创建新的输出目录 `work/pex-01/`，自行将下列内容保存为
`work/pex-01/extract.tcl`。替换 `TOP` 以及 `PORT_1 PORT_2 ...`；它们是占位符，
不是某道题的电路名或端口。脚本从 `work/pex-01/` 内运行，因此输入 GDS 使用
相对该目录的路径；也可以改成绝对路径。

```tcl
set gds_file [file normalize ../../submission/layout.gds]
set top TOP
set ordered_ports {PORT_1 PORT_2 PORT_3}
set flat_top ${top}_pex

drc off
gds readonly true
gds rescale false
gds read $gds_file
load $top
select top cell
# Create a flattened copy in memory with a name distinct from every existing cell.
flatten $flat_top
load $flat_top
select top cell
expand

# Set port attributes on existing physical labels of the same name; add no labels or connections.
set index 1
foreach pin $ordered_ports {
    if {[port $pin exists]} {
        port $pin index $index
    } else {
        port $pin make $index
    }
    incr index
}

extract style {ngspice()}
extract do local
extract no corners
extract no resistance
extract do capacitance
extract do coupling
extract do adjust
extresist threshold 0
extresist minres 1
extresist mindelay 0
extresist simplify on
extresist extout on
extresist silent off
extract do resistance
extract all

ext2spice default
ext2spice format ngspice
ext2spice scale off
ext2spice merge none
ext2spice hierarchy off
ext2spice subcircuit top on
ext2spice global off
ext2spice short none
ext2spice rthresh infinite
ext2spice cthresh 0
ext2spice extresist on
ext2spice -o extracted.spice ${flat_top}.ext
# Optionally save a Magic copy here for inspection; do not write back to the input GDS.
save $flat_top
puts "PEX_COMPLETE rc"
quit -noprompt
```

独立执行这一步：

```bash
mkdir -p work/pex-01
# Save work/pex-01/extract.tcl as shown above before running:
(
  cd work/pex-01
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc \
    extract.tcl > magic.log 2>&1
)
```

输出包括 `magic.log`、展平 cell 的 `.ext` / `.res.ext`、`extracted.spice`，
以及可选的 `.mag`。`threshold`、`minres` 单位为毫欧，`mindelay` 为皮秒。
当前版本用 `extract do resistance` 后的 `extract all` 完成 RC 抽取，
不需要再运行旧式 `ext2sim` 或重复调用 `extresist all`。

核对输出时至少查看：

- `.subckt TOP_pex ...` 的端口数量、名称、顺序是否与任务相符；实际仿真要按这行接线。
- MOS/BJT/R/C 模型名及器件尺寸；衬底/阱端是否来自真实接点及连接。
  `ext2spice global off` 不会替你把所有体端接到地，不能靠后改网表补接 GDS 中缺失的连接。
- 日志中的技术文件加载失败、未知抽取 style、缺标签、端口错误及抽取警告。
  Magic 可能在报错后继续执行，所以退出码或 `PEX_COMPLETE` 本身不证明抽取有效。
- `.res.ext` 是分布电阻抽取的证据之一；原电路本就含电阻时，看到 `R...` 语句不等于寄生电阻已抽出。

**单位：**本镜像 SKY130 `ngspice()` + `ext2spice scale off` 实测输出的 PDK
子电路 `w/l` 数字是 **µm**，如 `w=8 l=1`；`ad/as` 等面积数字按 µm² 表示。
这里的 `off` 不表示所有数字都变成 SI 米。原生寄生 `R` 以 Ω、`C` 以 F 或显式
SPICE 后缀表示，例如 `C1 n1 n2 2.5f` 是 2.5 fF；不要再给这些数值乘 `1e-6`。

RC 模式保留 `ext2spice short none`。不要为保留两个同网端口而盲目设置
`short resistor`，0Ω 别名可能旁路真实导线电阻；若输出缺少某个同网端口，要先检查
标签、端口与电阻网络。若只做 C-only 诊断，应关闭 `extract do resistance` 和
`ext2spice extresist on`，分别改为 `extract no resistance`、`ext2spice extresist off`；
此时可用 `short resistor` 表示理想同网端口。C-only 不能冒充包含互连电阻的后仿。

这份命令表与本镜像实测流程一致；抽取结果仍需结合 DRC/LVS 和电路行为检查，
不是任意器件、任意版图均已获得物理精度认证。

## ngspice 原生仿真

原生仿真测试台位于 `task/testbench/`，完整工况和指标见任务说明。
保持所给模型库、初始化、激励、负载和测量。
可执行示例见 `task/testbench/README.zh-CN.md`；
使用 `eda_env.sh` 给出的 `ALB_NGSPICE_INIT`。

仿真需要模型库、DUT 网表、提供电源/激励/负载/测量的测试台。
前仿 DUT 是 `task/circuit.spice`，后仿 DUT 是新抽取的 PEX 网表。
上一节 LVS 抽取网表没有寄生，不能把它当作 PEX 结果。

每次使用新仿真目录。旧环境示例采用以下 `.spiceinit`：

```text
set ngbehavior=hsa
set num_threads=1
```

这只是初始化示例，不是所有 SKY130 模型视图的统一要求。
前仿和后仿均应保留随题测试台指定的模型及初始化，不要静默切换兼容模式或
continuous/binned 模型。本次 LVS 后端切换没有改变这些选择。
不要使用会跳过初始化的 `-n`。

```bash
(
  cd work/sim-01
  SPICE_USERINIT_DIR="$PWD" ngspice -b -o simulation.log testbench.cir
)
```

相对 `.include` 和波形路径基于运行目录解析。模型路径见 `eda_env.sh`；
在 `.lib` 中填写实际路径，ngspice 不会在字符串中展开 shell 环境变量。
用 `.lib "MODEL_PATH" tt` 选择工艺角，用 `.temp` 设置温度。
不要静默更换 R/C 工艺角，或在要求完整矩阵时只测 TT。

按抽取 `.subckt` 声明的顺序连接 DUT。如果测试台调用 `TOP`、PEX 输出为
`TOP_pex`，只调整 DUT 子电路名称和端口位置绑定；保持电气连接、激励、负载、
容差和测量定义。外部偏置及负载 fixture 不属于 GDS 内部。

核对单位：已安装 Magic 的 `ngspice()` 方式配合 `ext2spice scale off`，PDK
`w/l` 数字使用 µm。相容测试台可能使用 `.option scale=1e-6`，不要重复缩放。
原生寄生 R/C 保留 SPICE 单位。核对收敛、有限测量值及要求的波形；
缺失测量或模型不算 SPEC 通过。

部分源文件仍包含历史路径，适配副本在 `task/testbench/adapted/`。
运行前应正确解析 include 路径和外部 fixture 依赖。
来源诊断测试台本身不证明全部要求工况都已通过。
