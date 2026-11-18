[English](DEVICE_API.md) | [简体中文](DEVICE_API.zh-CN.md)

# SKY130 器件接口

以英文版为准；中文版为对应翻译。

本文说明 SKY130 任务可用的原生查询、器件参数、接点、几何单位和图层。
工厂接口存在、满足工艺规则、被 LVS 识别和符合任务允许的物理实现，是不同条件。
在工作区执行 `source ./eda_env.sh` 后即可导入；包路径为
`/opt/analog-layout/pdks/sky130/python/sky130`。

`import sky130` 加载的是已安装的 `gdsfactory/skywater130` 器件库。
通过 open_pdks 提供的 SKY130 工艺还包含下文的 Magic 原生生成器；本环境中
部分电阻系列使用该接口。FOSSI `sky130_klayout_pdk` 提供已安装的 DRC/LVS
规则，其另一套 PCell 库未在这里安装。使用相同 SKY130 工艺，不代表这些
器件生成接口可以互换。

## 官方工艺参考资料（可选）

SKY130 原版工艺文档位于 `/opt/analog-layout/pdks/sky130/docs/skywater-pdk/`。
其中的 RST、CSV、TSV 都是可直接阅读和检索的文本，引用的表格与附图已一并提供。

- `rules.rst`：章节目录。
- `rules/device-details.rst`：MOS、电阻、电容及 BJT 器件说明。
- `rules/layers.rst`、`rules/gds_layers.csv`：层定义与 GDS 映射。
- `rules/periphery.rst`、`rules/periphery-rules.rst`、`rules/summary.rst`：工艺规则。

这些是上游工艺与器件参考文档。已安装的 PCell API、模型入口和验证规则各有固定版本；
PCell 参数按下面的原生接口查询，仿真使用本题选定的模型入口。

## 原生离线查询

直接使用已安装 Python 和 Magic 的接口；以下查询不需要联网。
在任务工作区先执行 `source ./eda_env.sh`。如果只是镜像内的 shell、没有任务工作区，
执行 `source /opt/analog-layout/env.sh`，并使用上文所列的 PDK Python 路径。

```bash
python - <<'PY'
import inspect
import pkgutil
import sky130

sky130.PDK.activate()
print(sky130.__file__)
print([m.name for m in pkgutil.iter_modules(sky130.pcells.__path__)])
print([n for n in dir(sky130.pcells) if n.startswith("sky130_fd_pr__")])
print([n for n in sorted(sky130.PDK.cells) if "cap_" in n or "res_" in n])
factory = sky130.pcells.sky130_fd_pr__res_generic_po
print(inspect.signature(factory))
help(factory)
PY
```

`sky130.PDK.cells` 是当前 PDK 的单元注册表，包含参数化单元和固定单元。
`sky130.cells` 也是注册表字典；生成的固定单元 Python 模块可通过 `sky130.components` 访问。
注册表中存在名字、存在 SPICE 模型、成功生成组件、被已安装 LVS deck 识别，是不同的事实。
`inspect.signature` 和 `help` 可以直接查询参数，不必阅读实现。

## Magic 原生生成器

Magic 为已安装的 SKY130 工艺提供另一套原生接口。参数名属于 Magic，不是 gdsfactory。
先查询准确型号的默认值，再向 `magic::gencell` 传入实例名和成对的参数名、值：

```bash
mkdir -p work/magic-device
(
  cd work/magic-device
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
set generator sky130::sky130_fd_pr__nfet_01v8
puts [info args magic::gencell]
puts [info procs ${generator}_defaults]
puts [${generator}_defaults]
drc off
load native_device
box values 0 0 0 0
magic::gencell $generator M0 w 2 l 0.5 nf 4 m 1 guard 1 doports 1
select top cell
gds write native_device.gds
quit -noprompt
TCL
)
```

直接调用 MOS 的 `gencell` 时，`w` 是**每一指的宽度**，单位为 µm。上例有四指，
每指 2 µm，总宽 8 µm。另一个原生 `_convert` 过程接受 SPICE 风格参数，会把总宽
除以 `nf`；不要重复转换。各栅极和源漏接点仍需按电路连接；确认是否已汇接前，
查询 `conn_gates` 等默认值。GDS 导出再导入不会自动生成 gf 端口。

相同查询方式适用于标准/LVT 1.8 V MOS、已安装的 5 V MOS 变种、
`diode_pw2nd_05v5`、`diode_pd2nw_05v5`、`res_generic_po`、`res_generic_m1`、
固定宽度 high/xhigh poly 电阻、`cap_mim_m3_1`、`cap_mim_m3_2` 和 `cap_var_lvt`。
这些名称均加上 `sky130::sky130_fd_pr__` 前缀。查询各生成器自己的默认值，
不要把 MOS 参数直接套到其他器件。进程退出成功并不保证器件生成成功：
还需查看日志，确认导出的单元确实包含几何。

两端模型 `sky130_fd_pr__res_generic_po` 的 Magic 原生调用示例如下。
`w`、`l` 是以 µm 表示的物理尺寸，不是以欧姆表示的阻值。使用任务网表
固定的型号和尺寸。这一器件族不同于后文的三端固定宽度精密 poly 电阻。

```tcl
set generator sky130::sky130_fd_pr__res_generic_po
puts [${generator}_defaults]
load generic_resistor
box values 0 0 0 0
magic::gencell $generator R0 w 1.00 l 35.25 m 1 nx 1 guard 0 doports 1
select top cell
gds write generic_resistor.gds
```

在使用上文启动文件的 Magic 会话中运行这些 Tcl 命令。
用 `gf.import_gds` 导入其 GDS，布线前检查实际几何和标签。
LVS 参考网表中保留 generic-poly 的型号及 W/L。

检查即将用于布线的实际实例，包括变换后的坐标：

```bash
python - <<'PY'
import gdsfactory as gf
import sky130

sky130.PDK.activate()
device = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True,
)
layout = gf.Component("device_api_example")
ref = layout.add_ref(device)
ref.drotate(90)
ref.dmove((10, 10))
print(device.info)
print("dbu_um:", device.kcl.dbu, "geometry_layers:", device.layers)
print("instance_bbox_um:", ref.dbbox())
for port in ref.ports:
    print(port.name, port.dcenter, port.dwidth, port.orientation,
          gf.get_layer_tuple(port.layer), port.port_type)
print("M1:", gf.get_layer_tuple(sky130.LAYER.met1drawing))
print([(name, gf.get_layer_tuple(layer))
       for name, layer in sky130.LAYER.__members__.items()
       if name.endswith("drawing")])
PY
```

`ports` 是可迭代、可按端口名索引的容器，不是 `dict`，没有 `.items()`。
需要字典时可使用 `{p.name: p for p in ref.ports}`。端口元数据描述布线连接位置，
不会生成导体、接触孔、总线或 GDS 标签。下文部分电气器件工厂继承了
`port_type="optical"`，只按 electrical 类型过滤会漏掉它们的接点，应明确检查名字和图层。
仅凭端口中心或宽度不能证明每条金属边都位于制造网格上；放置和布线后应检查几何并运行 DRC。

## 普通和 LVT 1.8 V MOS 器件

- `sky130_fd_pr__nfet_01v8`
- `sky130_fd_pr__pfet_01v8`
- `sky130_fd_pr__nfet_01v8_lvt`
- `sky130_fd_pr__pfet_01v8_lvt`

`gate_width` 是请求的每指宽度，单位为 µm；名义总宽为 `gate_width * nf`。
`nf` 应使用正整数。普通/LVT 01v8 SPICE 子电路中，网表的 `w` 是 `nf` 指的总宽，
不是 PCell 的每指宽度。解析网表缩放与单位后，应设置 `gate_width = W_total_um / nf`。
例如总宽 `w=8 µm`、`l=.5 µm`、`nf=4` 对应
`gate_width=2.0, gate_length=.5, nf=4`。SPICE 实例倍乘参数 `m` 与 `nf` 是不同概念，
不要把指数量重复乘入或除出。不能仅凭 `mult` 这个参数名推断标称倍乘：在已安装的标准
1.8 V MOS、MIM 和 PNP 仿真封装中，它用于统计失配。
Python 工厂的 `mult` 则是另一套接口，下文单独说明。
这四个上游工厂只提供以下四个端口：

| 端口 | 含义 | 层 |
|---|---|---|
| `GATE` | 第一指栅极的中心 | poly `(66,20)` |
| `DRAIN` | 最左侧扩散接触列的中心 | LI1 `(67,20)` |
| `SOURCE` | 最右侧扩散接触列的中心 | LI1 |
| `BODY` | 位于 `(0, -(gate_width/2 + gate_to_polycont))` 的元数据；NMOS 的 `gate_to_polycont` 为 `.275`，PMOS 为 `.32` | LI1 |

即使 `guard_ring=False`，也会提供 `BODY` 端口。其名字、图层和坐标不保证该位置
存在物理体接触。有保护环时，应检查环上实际的 tap/LICON/LI 几何来选择体端连接点；
没有保护环时，应在上层版图中提供所需体端连接。连接到 M1 还需要正确的
LI—M1 接触孔及包围导体。
端口坐标单位为 µm；旋转、移动、镜像后的组件，使用实例的 `ports`。

`nf` 指的几何包含 `nf+1` 个扩散接触列及独立的各指栅极。这四个端口不会枚举全部
接点，也不会将它们连接成总线。实现并联多指器件时，应按网表将交替的扩散接触列
分别连接到两个源漏网络，并连接全部栅极。`nf` 为偶数时，两侧最外部扩散列属于
同一个交替组：仅凭 `DRAIN`、`SOURCE` 的名字不能确定正确的多指接线。
其余接点应通过实际几何定位。端口元数据本身不会生成导体或 GDS 文本标签。

```python
from sky130.pcells.mosfets import sky130_fd_pr__nfet_01v8_lvt

device = sky130_fd_pr__nfet_01v8_lvt(
    gate_width=2.0, gate_length=0.35, nf=2, guard_ring=True
)
assert {p.name for p in device.ports} == {"GATE", "SOURCE", "DRAIN", "BODY"}
for port in device.ports:
    print(port.name, port.dcenter, port.dwidth)
```

这些是上游端口名称，不是完整的物理端子映射。

## 保留和未实现的选项

这四种工厂接受以下参数，但没有实现相应变化，也不会显式拒绝非默认值：

| 参数 | 默认值 | 上游行为 |
|---|---|---|
| `dnwell` | `False` | 未使用；设置此参数不会生成隔离深 N-well |
| `mult` | `1` | 保留参数；仍只生成一个器件，需要多实例时自行放置并连接 |
| `sd_width` | `0.28` | 保留参数；不影响生成的几何 |
| `end_cap` | `0.13` | 保留参数；不影响生成的几何 |

尺寸应选择有限正数，指数量应为正整数；上游工厂不提供针对这些条件的专门校验约定。
下游 Python、几何或端口报错不能代替工艺规则检查。
上表行为已针对所列四种工厂核对；其他变体应分别查询。

## 其他 MOS 生成器

下列工厂同样从 `sky130.pcells` 和 `sky130.pcells.mosfets` 导出。
它们接受下文 MOS 签名中的相同参数名；表中是实际默认宽长，单位为 µm，不是任务规格。

| 工厂 | `gate_width` | `gate_length` | `sd_width` |
|---|---|---|---|
| `sky130_fd_pr__pfet_01v8_hvt` | `.42` | `.15` | `.28` |
| `sky130_fd_pr__nfet_03v3_nvt` | `.42` | `.50` | `.28` |
| `sky130_fd_pr__nfet_05v0_nvt` | `.42` | `.90` | `.28` |
| `sky130_fd_pr__nfet_g5v0d10v5` / `sky130_fd_pr__pfet_g5v0d10v5` | `.42` | `.50` | `.28` |
| `sky130_fd_pr__nfet_20v0` / `sky130_fd_pr__pfet_20v0` | `.42` | `2.0` | `.50` |

默认组件提供 poly `(66,20)` 上的 `GATE`，以及 LI `(67,20)` 上的
`SOURCE`、`DRAIN`、`BODY`。这些是元数据，不是完整的物理端子映射。
存在 `BODY` 名字不证明已经生成独立体接触；连接前应检查所需参数组合及其几何。
已检查默认参数能够生成组件；这不代表任意参数通过 DRC/LVS，也不代表每个参数都被生成器实现。

## 电阻、MIM 电容、二极管与 BJT

下表所有工厂均从 `sky130.pcells` 导出；模块列给出另一种直接导入路径。
尺寸参数单位为 µm，表示几何尺寸，不是以 Ω 表示的电阻值或以 F 表示的电容值。
尺寸与所需电气值的关系必须遵循任务指定的物理器件及模型。

| `sky130.pcells` 下的模块 | 工厂 | 尺寸默认值 | 已提供的端口及图层 |
|---|---|---|---|
| `resistors` | `sky130_fd_pr__res_generic_po` | `res_width=.33, res_length=1.65` | `PLUS`、`MINUS`：M1 `(68,20)` |
| `resistors` | `sky130_fd_pr__res_generic_nd` | `res_width=.42, res_length=2.10` | `PLUS`、`MINUS`：M1 |
| `resistors` | `sky130_fd_pr__res_high_po_0p35` | `res_width=.35, res_length=.50` | `PLUS`、`MINUS`：M1 |
| `resistors` | `sky130_fd_pr__res_high_po` | `sky130_fd_pr__res_high_po_0p35` 的直接别名 | 相同端口 |
| `capacitors` | `sky130_fd_pr__cap_mim_m3_1` | `cap_width=2.0, cap_length=2.0` | `BOTTOM`：M3 `(70,20)`；`TOP`：M4 `(71,20)` |
| `capacitors` | `sky130_fd_pr__cap_mim_m3_2` | `cap_width=2.0, cap_length=2.0` | `BOTTOM`：M4；`TOP`：M5 `(72,20)` |
| `diodes` | `sky130_fd_pr__diode_pw2nd_05v5` | `diode_width=.45, diode_length=.45` | `CATHODE`：M1；`ANODE`：LI `(67,20)` |
| `diodes` | `sky130_fd_pr__diode_pd2nw_05v5` | `diode_width=.45, diode_length=.45` | `ANODE`：M1；`CATHODE`：LI |
| `bjts` | `sky130_fd_pr__npn_05v5` | `emitter_width=1.0, emitter_length=1.0` | `EMITTER`、`BASE`、`COLLECTOR`：LI |
| `bjts` | `sky130_fd_pr__pnp_05v5` | `emitter_width=.68, emitter_length=.68` | `EMITTER`、`BASE`、`COLLECTOR`：LI |

两个 BJT 工厂还接受 `base_ring_width=.4`、`np_spacing=.27`、
`sdm_enclosure=.125`、`nwell_enclosure=.18` 和 `li_enclosure=.08`。
电阻、MIM 和 BJT 工厂当前的 `port_type` 为 `"optical"`，二极管工厂为
`"electrical"`；这些元数据类型不改变器件的物理图层。
上游 generic-poly 电阻在主体上使用 `polyres` `(66,13)`，high-poly 电阻使用
`rpmdrawing` `(86,20)`。工厂名称不能证明当前抽取 deck 会将这些图层识别为何种电阻模型。

电阻端口中没有体/保护环接点；P+/N-well 二极管的外部衬底环也没有提供衬底端口。
任务要求的体端或衬底接触应根据实际几何连接。MIM 组件不对称：下极板端口位于下层金属，
右侧还有下极板的上层金属引出区。不要用组件包围盒猜测端子位置。
MIM 的 Python 端口名为 `TOP/BOTTOM`，现有 GDS 标签为 `C1/C2`；
映射端子时应依据实际抽取网表和任务端口声明。

当前默认 `sky130_fd_pr__npn_05v5` 几何有已知限制：其 `BASE` 和 `COLLECTOR`
元数据位置属于同一个合并后的 LI 区域，collector 条带没有独立的 tap/LICON 接触堆叠。
不能把它当作已验证的三个端子相互独立的实现。这是几何检查结果，不是 LVS 结果。
PNP 默认端口位于不同 LI 区域，也不构成 DRC/LVS 有效性证明。
对上述所有器件，工厂调用成功和 SPICE 模型名存在都不代表 LVS 一定兼容。

### 固定 BJT 单元

PDK 原生注册表还包含固定的工艺 BJT 版图，例如：

```python
import gdsfactory as gf
import sky130

sky130.PDK.activate()
print([n for n in sorted(sky130.PDK.cells) if "rf_npn" in n or "rf_pnp" in n])
npn = gf.get_component("sky130_fd_pr__rf_npn_05v5_W1p00L1p00")
pnp = gf.get_component("sky130_fd_pr__rf_pnp_05v5_W0p68L0p68")
print(npn.dbbox(), pnp.dbbox())
print([(t.string, t.x, t.y) for t in pnp.get_labels((67, 5), recursive=True)])
```

这些固定单元没有 gf 端口。PNP 带有 LI 标签 `Base`、`Collector`、`Emitter`，
该 NPN 没有对应的端子标签。通过几何与抽取定位接点，并保持指定模型、发射极尺寸
和 bulk 端子。Magic 原生 BJT 生成器需要先加载其固定库单元；可以先通过 Magic
的 `gds read` 导入已安装的 RF GDS，再调用生成器。不要仅因存在 Tcl 过程就认为
相应 `.mag` 文件也已安装。

### MIM 尺寸

`cap_width` 和 `cap_length` 描述有效 capm 矩形，不是整个组件包围盒或引出金属。
矩形极板的几何面积为 `W*L`（µm²），周长为 `2*(W+L)`（µm）。固定 LVS deck
比较这些几何参数；电气电容值来自任务指定的 SPICE 模型。
如提供了仅供 reader 使用的 LVS 参考网表，就直接使用，不要把其中的几何参数
替换成电容值。阵列倍数与模型失配参数含义不同，应保留网表参数。

当前 Magic 原生 MIM 生成器会将 `w`、`l` 限制到其 2–30 µm 的范围。
这是生成器限制，不是宣称工艺存在统一的最大尺寸。Python MIM 工厂的接口不同；
使用前仍需检查实际生成的尺寸并验证。

## Magic 原生精密 poly 电阻接口

已安装的 Magic SKY130 PDK 为固定宽度的 P+ 精密电阻提供了有明确型号的 PCell。
应选择与固定网表模型名一致的生成器：

| Magic 生成器及 SPICE 模型 | 固定宽度 `w`（µm） |
|---|---:|
| `sky130_fd_pr__res_high_po_0p35` | 0.35 |
| `sky130_fd_pr__res_high_po_0p69` | 0.69 |
| `sky130_fd_pr__res_high_po_1p41` | 1.41 |
| `sky130_fd_pr__res_high_po_2p85` | 2.85 |
| `sky130_fd_pr__res_high_po_5p73` | 5.73 |

对应的五种 `sky130_fd_pr__res_xhigh_po_*` 原生生成器使用相同的固定宽度后缀。
high 和 xhigh 是不同器件模型，名称不能互换；使用任务网表指定的系列。

Magic 的 `l` 是两端长条接触孔内边缘之间的电阻主体长度，单位为 µm。
固定宽度 SPICE 模型接受 `l`，宽度由模型名称确定。使用网表给定的尺寸；
电阻值取决于模型、温度和工艺条件，并非给一个形状赋上理想电阻值即可。
`m` 和 `nx` 控制两个阵列方向上的器件个数；单个电阻保持二者为 1。
`guard=1` 生成衬底保护接点，`doports=1` 生成器件标签。应将该接点连接到网表的 bulk 节点。

Python 中的 `sky130_fd_pr__res_high_po` 只是 Python `0p35` 工厂的别名。
修改它的 `res_width` 不是选择其他固定宽度型号的受支持接口。
下述 Magic 原生接口可以直接调用具名的 `1p41` 生成器。

原生 `res_high_po_0p35` 几何需检查 RPM 注入层 `(86,20)`：本环境 DRC 规则
`MR_rpm.WID.1` 要求宽度至少为 1.27 µm。Magic 原生生成器可能给出 0.75 µm
宽的 RPM 条。可以适当扩展该掩膜，同时保持指定的电阻 poly 宽度、电气长度和
端子连接，再运行 DRC 和 LVS。

下面的独立示例采用 `w=1.41`、`l=42.36`，已使用当前 DRC、LVS 和 Magic 抽取工具检查。
应根据任务替换型号与尺寸；示例不是通用的电阻值，也不是电路版图解答。
在任务工作区执行 `source ./eda_env.sh` 后运行：

```bash
mkdir -p work/precision-res-example
(
  cd work/precision-res-example
  magic -dnull -noconsole \
    -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
puts [info procs sky130::*res_high_po*_defaults]
puts [sky130::sky130_fd_pr__res_high_po_1p41_defaults]
drc off
load precision_res_example
box values 0 0 0 0
magic::gencell sky130::sky130_fd_pr__res_high_po_1p41 R0 \
    w 1.41 l 42.36 m 1 nx 1 guard 1 doports 1
select top cell
save precision_res_example
gds write precision_res_example.gds
quit -noprompt
TCL
)
```

`_defaults` 返回原生参数字典，上述查询不需要查看源码。
`magic::gencell` 接收生成器、非空实例名，以及成对的参数名与值。
`drc off` 只是在绘图时关闭 Magic 的交互后台检查；生成后应运行 `GUIDE.md`
中的独立 DRC、LVS 命令。生成的 GDS 可以导入 gdsfactory 设计：

```python
import gdsfactory as gf
import sky130

sky130.PDK.activate()
resistor = gf.import_gds("work/precision-res-example/precision_res_example.gds")
print([(t.string, t.x, t.y)
       for t in resistor.get_labels((67, 5), recursive=True)])
layout = gf.Component("precision_res_import_example")
ref = layout.add_ref(resistor)
ref.dmove((10, 10))
```

打印的坐标属于导入组件自身的坐标系，还没有应用实例移动。
GDS 保留几何、层级和标签，但这次导入不会自动创建 gdsfactory `Port` 对象。
应根据实际几何和标签定位接点，在布线时应用实例变换。

| LI 标签 `(67,5)` | 精密电阻 SPICE 子电路中的端子 |
|---|---|
| `R1` | `r0`，第一个电阻端子 |
| `R2` | `r1`，第二个电阻端子 |
| `B` | `b`，衬底/bulk 端子 |

例如，`XR0 net_a net_b vss sky130_fd_pr__res_high_po_1p41 l=42.36`
要求 `R1` 接 `net_a`、`R2` 接 `net_b`、`B` 接 `vss`。
展平抽取后，标签可能带实例名前缀，例如 `R0.R1`。
该示例实际抽取为 `sky130_fd_pr__res_high_po_1p41 l=42.36`，无需替代模型或修改 PDK。
保留要求的 bulk 连接，并在放置、布线后重新检查。

## MOS 电容与变容管

当前 Python 包提供 MIM 工厂和固定 VPP 电容单元，但 `sky130.pcells` 或
`sky130.PDK.cells` 中没有 `cap_var`、`cap_mos`、`cap_nfet`、`cap_pfet`
版图工厂。将模型名当作 Python 函数前，应先查询注册表。

已安装的 Magic 工艺提供 `sky130_fd_pr__cap_var_lvt`、
`sky130_fd_pr__cap_var_hvt` 和 `sky130_fd_pr__cap_var` 的原生 Tcl 生成器。
它们的 `_draw` 过程接受一个 `parameters` 字典；`_defaults`、`_convert` 和
`_check` 过程提供原生参数处理接口。可离线查询：

```bash
magic -dnull -noconsole \
  -rcfile /opt/analog-layout/pdks/sky130/sky130A/libs.tech/magic/sky130A.magicrc <<'TCL'
puts [info procs sky130::*cap_var*_defaults]
puts [info args sky130::sky130_fd_pr__cap_var_lvt_draw]
puts [sky130::sky130_fd_pr__cap_var_lvt_defaults]
quit -noprompt
TCL
```

LVT/HVT 的默认参数包括 `w=1.0`、`l=.18`、`nf=1`、`m=1`、`guard=1`；
普通 `cap_var` 的默认长度为 `.50`。其余接触孔和覆盖选项可由 `_defaults` 查询；
这些名称与行为属于 Magic 接口，不是 Python MOS 工厂参数。
LVT 绘制过程使用 Magic 类型 `var`、`nnd`、`nsc`、`poly`、`pc`、`nwell` 和 `psub`。
它不提供 Python `Port` 对象，也不继承上述四种 MOS 的端口名。
默认字典没有要求 `doports`；定义任务端口前应检查生成的标签和物理接点。

ngspice 模型树包含 `sky130_fd_pr__cap_var_lvt` 与 `...__cap_var_hvt`，
SPICE 端子顺序为 `c0 c1 b`，参数为 `w`、`l`、`vm`；逻辑端子不会自动成为版图标签。
模型文件位于 `/opt/analog-layout/pdks/sky130/sky130A/libs.ref/sky130_fd_pr/spice/`，
由 `libs.tech/ngspice/all.spice` 引入，不在当前 combined continuous 模型视图中。
应使用任务声明的模型视图与物理器件；存在 Magic 生成器或模型文件本身并不能确立允许的器件替换或 LVS 匹配。

## 参数、坐标与接触孔接口

上述四种 MOS 的参数名称相同，普通 NMOS 的签名如下，长度参数均为 µm：

```python
sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=0.42, gate_length=0.15, sd_width=0.28,
    nf=1, guard_ring=True, dnwell=False, end_cap=0.13, mult=1,
)
```

普通 PMOS、LVT NMOS 的默认值与上例相同；LVT PMOS 的 `gate_length` 默认值为 `.35`。
`guard_ring=True` 为 NMOS 生成 P+ 衬底接触环，为 PMOS 生成 N+ 阱接触环；
实际体端仍须按网表接线。上述默认尺寸只是函数默认值，任务尺寸以网表为准。
`ref.ports` 返回实例变换后的元数据。上游 MOS 几何把多边形顶点量化到 5 nm 网格，
四个端口的宽度却直接使用 `gate_width`。因此任意请求宽度可能与实际扩散宽度不同，
也可能导致端口构造失败。当前安装环境的 DBU 为 1 nm，kfactory 要求以 DBU 表示的
端口宽度为偶数；这个检查本身并不保证满足 5 nm 制造网格。
端口的 `dwidth` 既不是 M1 接触垫宽度，也不是建议布线宽度。

这些 MOS 几何以原点为中心，完整宽度取 10 nm 网格可使两侧半宽边界落在 5 nm 网格上。
可用 gdsfactory 原生接口计算能够表示的宽度：

```python
import gdsfactory as gf
import sky130

width_total_um, nf = 8.0, 4
width_per_finger_um = gf.snap.snap_to_grid(width_total_um / nf, nm=10)
print(width_per_finger_um, width_per_finger_um * nf)  # 2.0, 8.0
device = sky130.pcells.sky130_fd_pr__nfet_01v8(
    gate_width=width_per_finger_um, gate_length=0.5, nf=nf,
)
```

这使实际传入的宽度明确，不授权修改任务的固定尺寸。
例如，把 `8/3` 取整到 `2.67` µm 会产生 `8.01` µm 的总宽，而不是 `8` µm；
不能把这种运算当作严格保持原尺寸的实现。
若等宽分指不能落在网格上，允许把器件实现为并联的网格内分指，保持同一型号、
沟道长度、总宽及 D/G/S/B 连接。例如总宽 `8` µm 可用
`2.66 + 2.67 + 2.67` µm，保持总宽。这是固定器件的物理分割，
不改变参考网表或电气尺寸。生成的版图仍需满足 DRC、LVS 和后仿电气要求。
生成几何和抽取尺寸仍需满足任务与 LVS 要求。当前安装的 gdsfactory 中，显式 `nm`
会覆盖 `grid_factor`，因此 `snap_to_grid2x(value, nm=5)` 不能替代
`snap_to_grid(value, nm=10)`。默认 cell 装饰器的端口量化发生在构造之后，
不能修复传给端口构造函数的不合法宽度。

现有切孔接口可直接从 `sky130.pcells` 访问：

```python
contact_array(width=0.29, height=0.29, contact_layer=(66, 44),
              contact_size=(0.17, 0.17), contact_spacing=(0.17, 0.17),
              enclosure=(0.06, 0.06))
licon_array(width=0.29, height=0.29)
mcon_array(width=0.29, height=0.29)
via_generator(width=1, length=1, via_size=(0.17, 0.17),
              via_layer=(66, 44), via_enclosure=(0.06, 0.06),
              via_spacing=(0.17, 0.17))
```

- `contact_array` 只返回切孔矩形，不生成上下层导体、implant、well 或端口。
  `width/height` 是用于排孔的假想包围区域；切孔阵列中心在该区域中心
  `(width/2, height/2)`，不是坐标原点。`contact_spacing` 是孔边到孔边距离，
  阵列节距为孔尺寸加该间距。区域放不下一个孔时返回空组件。
- `licon_array` 是上述接口的固定参数版本：LICON `(66,44)`，孔尺寸 `.17×.17`，
  孔间距 `.17`，排孔边界余量 `.06`。这不代表任意 poly/LI 包围规则只需 `.06`。
- `mcon_array` 使用 MCON `(67,44)`，孔尺寸 `.17×.17`，孔间距 `.19`，
  排孔边界余量 `(x=.03, y=.06)`。仍需已有或自行绘制 LI 与 M1 导体。
- `via_generator` 同样只画切孔；`width/length` 用于计算行列数，切孔阵列从原点开始，
  不自动居中。其当前实现至少生成一行一列，因此输入窗口太小也不能据此认为合法。
  调整实例位置前可查看 `ref.dbbox()`，或用 `ref.dcenter=(x,y)` 对齐实际阵列中心。
  默认生成 LICON；做 M1—M2 过孔时必须显式指定 VIA 图层、尺寸、间距与包围参数。

这些函数的 `enclosure` 参数只控制排孔位置，不会补画包围金属。
两层金属只有几何重叠而没有正确的切孔层，仍不构成跨层连接。
安装库中另有 `from sky130.pcells.vias import via_m1_m2`，签名为
`via_m1_m2(width=0.5, length=0.5)`，它会画 M1/VIA/M2
并提供 `e1/e2` 端口；它不在顶层 `sky130.pcells` 导出列表中，且任意参数仍需 DRC。
需要查接口说明时可直接使用 Python `help(sky130.pcells.contact_array)`；
阅读实现是可选的，接口返回几何的边界已列在这里。

## 常用层与连接关系

`sky130.LAYER` 的属性如下；括号是 GDS `(layer, datatype)`。
导体标签使用 `add_label` 放在对应的 label 层并位于实际导体内。
文字不等于几何连接；不要把 label 层画成导体。

| 作用 | drawing 属性 / GDS 层 | label 属性 / GDS 层 |
|---|---|---|
| N-well | `nwelldrawing` `(64,20)` | `nwelllabel` `(64,5)` |
| 器件 diffusion | `diffdrawing` `(65,20)` | `difflabel` `(65,6)` |
| 体/阱接触区域 | `tapdrawing` `(65,44)` | `taplabel` `(65,5)` |
| Poly | `polydrawing` `(66,20)` | `polylabel` `(66,5)` |
| Poly/diff/tap → LI | `licon1drawing` `(66,44)` | — |
| LI | `li1drawing` `(67,20)` | `li1label` `(67,5)` |
| LI → M1 | `mcondrawing` `(67,44)` | — |
| M1 | `met1drawing` `(68,20)` | `met1label` `(68,5)` |
| M1 → M2 | `viadrawing` `(68,44)` | — |
| M2 | `met2drawing` `(69,20)` | `met2label` `(69,5)` |
| M2 → M3 | `via2drawing` `(69,44)` | — |
| M3 | `met3drawing` `(70,20)` | `met3label` `(70,5)` |
| M3 → M4 | `via3drawing` `(70,44)` | — |
| M4 | `met4drawing` `(71,20)` | `met4label` `(71,5)` |
| M4 → M5 | `via4drawing` `(71,44)` | — |
| M5 | `met5drawing` `(72,20)` | `met5label` `(72,5)` |
| MIM 极板标记 | `capm` `(89,44)`；`cap2m` `(97,44)` | — |
| 电阻标记 | `polyres` `(66,13)`；`diffres` `(65,13)`；`rpmdrawing` `(86,20)` | — |
| BJT 识别 | `npndrawing` `(82,20)`；`pnpdrawing` `(82,44)` | — |

表中的属性对应当前安装的 `sky130.LAYER`。
LVS/PEX 顶层端口宜放在本任务使用的 LI/金属导体及对应 label 层；
本表列出某个 label 属性，不代表所有抽取器都将其识别为顶层端口。

## 当前 DRC deck 的基础规则索引

以下供普通低压模拟外围区域查询，**不是完整设计规则，也不能代替 DRC**。
宽、间距、包围量单位为 µm，面积为 µm²。当前 deck 固定为 AL backend；
core、精密电阻、MIM、特殊器件、seal 等另有条件规则，不能套用本表全部数值。

本地依据：`/opt/analog-layout/pdks/sky130/klayout/sky130A_mr.drc`，
release `2025.11.17_01.10`。下表行号对应这份已安装的文件。

| 对象 | 普通区域常用规则 | 固定 deck 位置 / 报告规则名 |
|---|---|---|
| 网格 | 顶点在 `.005`（5 nm）网格；浮点计算、旋转/镜像后仍应核对 | L1675 起，`*_OFFGRID` |
| N-well | 最小宽 `.84`；不同多边形间距 `1.27`；能否合并还取决于电路体端网络 | L331，`MR_nwell.WID.1/SP.1` |
| Diff/tap | 外围区域最小宽 `.15`；diff/tap 组合间距 `.27` | L425–465，`difftap.1_a`、`MR_diff.WID.2`、`difftap.3` |
| Poly | 最小宽 `.15`，普通外围间距 `.21`；这不是更改网表 L 的授权 | L515–524，`MR_poly.WID.2/SP.1` |
| LICON | 普通非 bar/非精密电阻孔 `.17×.17`，孔间距 `.17`；不能同时跨到 poly 与 diff/tap | L805–836、L952，`MR_licon.SP.1/WID.1`、`licon.1/17` |
| LI | 非 core 区域宽/间距 `.17/.17`，最小面积 `.0561`；包围 LICON 还有 `.08` 的相邻边条件 | L1070–1090，`li.1/3/5/6` |
| MCON | 普通孔 `.17×.17`，孔间距 `.19`，必须被 LI 覆盖 | L1119–1151，`MR_mcon.WID.1/LEN.1/SP.1/CON.10` |
| M1 | 普通线宽/间距 `.14/.14`，最小面积 `.083`；3 µm 级宽金属相关间距为 `.28`；包围 MCON 至少 `.03`，还有 `.06` 的相邻边条件 | L1157–1235，`MR_met1.WID.1/SP.1/AR.1/ENC.1`、`MRW_met1.SP.2`、`m1.5` |
| VIA（M1→M2） | 普通孔 `.15×.15`，孔间距 `.17`；M1 和 M2 包围至少 `.055`，二者另有 `.085` 的相邻边条件 | L1256–1306、L1343–1363，`via.1a/2/5a`、`MR_via1.ENC.1`、`m2.4/5` |
| M2 | 普通线宽/间距 `.14/.14`，最小面积 `.0676`；3 µm 级宽金属相关间距为 `.28` | L1314–1331，`MR_met2.WID.1/AR.1`、`m2.2`、`MRW_met2.SP.2` |

“相邻边条件”表示：对孔的每个角，两条相邻边的包围量中至少一条须达到较大值。
对于矩形落脚垫，常见的满足方式是在一对相对边增加包围量；不是随便选两条相邻边加长。
例如 MCON 的 M1 四边至少 `.03`，并满足上述 `.06` 条件。
落脚垫满足孔包围，仍可能因金属面积过小而报错；PCell 不承诺独立接点无需外围引线就过所有面积规则。
`floating_met=true` 还会检查浮空金属：M1 必须接触 MCON/VIA、M2 必须接触 VIA/VIA2 等。
