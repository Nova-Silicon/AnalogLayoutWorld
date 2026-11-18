# 固定版本的 SKY130 运行时资源

[English](README.md) | [简体中文](README.zh-CN.md) · [文档索引](../../docs/README.zh-CN.md)

`sky130/` 是经审阅并随仓库提供的资源目录，会被复制到 EDA 镜像中的
`/opt/analog-layout/pdks/sky130/`。正常运行和从源码构建镜像均直接使用
这份已纳入版本控制的资源，无需单独准备 PDK。

资源包含 Python PCell 源码和固定单元库 GDS、DRC/LVS 规则、Magic 技术文件、
Netgen 比较配置、连续模型和分箱 SPICE 模型的完整 include 依赖，
以及可离线查阅的工艺/API 参考。单元库 GDS 是上游组件，而非任务提交产物。
适用范围见[运行时说明](sky130/README.md)。

## 校验资源

在仓库根目录检查打包文件集合和选定资源的哈希：

```bash
python3 docker/pdk/verify.py
python3 -m unittest discover -s tests -p test_pdk_assets.py
```

在 EDA 镜像内部，使用以下命令检查已安装的资源目录：

```bash
python -I -B /opt/analog-layout/build-checks/verify_pdk.py \
  --root /opt/analog-layout/pdks/sky130
```

这些检查验证资源打包情况，不代表版图已通过物理验收。Manifest 检查会拒绝
缺失、新增、修改和符号链接文件；测试还独立于 manifest 校验部分已确认资源。

## 来源与许可

| 组件 | 固定来源 | 保留的许可 |
|---|---|---|
| Python PCell 与固定单元库 GDS | `gdsfactory/skywater130` 的 `5c7b9ba5f13b5411e53bbb5e35ed3db4f4e79986` | MIT |
| KLayout 规则 | `fossi-foundation/sky130_klayout_pdk` 的 `4ea0975391feacbdac697bf07029d8908d292613` | DRC GPL-3.0；LVS Apache-2.0 |
| Magic 技术文件与 Netgen 配置 | `RTimothyEdwards/open_pdks` 的 `0ec4fa67eade28cd0a4352c04df981840809427b` | 上游 LICENSE 与原始文件声明 |
| 连续模型 | Volare 发布版 `sky130-c6d73a35f524070e85faff4a6a9eef49553ebc2b` | Apache-2.0 文件头 |
| 分箱模型 | 同一 Volare 发布版；独立的 `libs.tech/ngspice` 入口和 `libs.ref` 依赖 | Apache-2.0 文件头 |
| 工艺参考 | `google/skywater-pdk` 的 `7198cf647113f56041e02abf3eb623692820c5e1` | Apache-2.0 |

[asset-manifest.json](sky130/asset-manifest.json) 记录文件、公开来源版本、
来源 URL、归档哈希和许可位置。原始文件头和许可全文均保留在资源目录中。
连续模型和分箱模型具有各自的 include 依赖图；请使用每道题测试台指定的模型入口。

## 可选：资源开发

有意更新资源时，可先查看准备工具的选项：

```bash
python3 docker/pdk/prepare.py --help
```

工具接受显式指定的本地来源路径和新的目标目录。替换已确认的资源时，
需要审阅新的资源包；首次使用者可直接使用仓库中的资源和预构建 EDA 镜像。
镜像构建和正确性检查见 [EDA 镜像指南](../../docs/images.zh-CN.md)。
