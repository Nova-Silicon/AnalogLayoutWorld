# EDA 镜像

[English](images.md) | **简体中文** · [文档索引](README.zh-CN.md)

## 普通使用

无需自行构建镜像。各题 Dockerfile 会自动拉取公开的 Linux/amd64 EDA 基础镜像，
版本由下面的 digest 固定：

```bash
docker pull ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338
```

提前下载是可选步骤，无需登录镜像仓库。下载量约 595 MB，解压后约 1.88 GB；
还需为任务镜像和结果留出空间。每个并行任务默认使用 6 CPU、32 GiB 内存。

镜像提供 gdsfactory、KLayout、Magic、Netgen、ngspice、Python 和 SKY130 资源。
Harbor 另外安装所选 harness；模型 key 在运行时传入。Agent 与验收器使用同一个
EDA 基础镜像，验收器独立接收可信任务文件。

## 可选：检查环境

以下命令不调用模型 API，只检查已安装的 EDA 软件和 PDK：

```bash
docker run --rm --network none \
  ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338 \
  python -I -B /opt/analog-layout/build-checks/check_runtime.py --out /tmp/eda-check
```

退出码为 0 表示组件检查通过，不表示某份任务 GDS 已通过验收。

## 可选：从源码构建

在仓库根目录执行：

```bash
docker build --platform linux/amd64 --build-arg BUILD_JOBS=4 \
  -f docker/Dockerfile -t analoglayoutworld/eda:local .
```

构建会下载公开依赖。`docker/sources.lock.json`、`docker/requirements.lock` 和
`docker/pdk/sky130/asset-manifest.json` 记录源版本及资源；镜像完成前会执行构建检查。
`BUILD_JOBS` 控制编译并行度，不是实验并发数。

独立验收时，在 `alw verify` 的任务、提交和输出参数之外，增加
`--base-image analoglayoutworld/eda:local` 即可选择自建镜像。通过 Harbor 运行时，
应同时覆盖 **Agent 和验收容器**任务镜像的 `ALW_BASE_IMAGE` 构建参数；仅导出宿主机
环境变量不会覆盖 Dockerfile 的 `ARG`。普通实验使用已发布的固定 digest。
