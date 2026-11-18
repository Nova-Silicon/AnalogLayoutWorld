# EDA image

**English** | [简体中文](images.zh-CN.md) · [Documentation](README.md)

## Normal use

You do not need to build an image. Task Dockerfiles automatically pull the
public Linux/amd64 EDA base, fixed by this digest:

```bash
docker pull ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338
```

Pulling it in advance is optional. No registry login is required. The download
is about 595 MB, expanding to 1.88 GB; allow additional space for task images and
results. Each concurrent task defaults to 6 CPU and 32 GiB memory.

The image supplies gdsfactory, KLayout, Magic, Netgen, ngspice, Python and the
SKY130 resources. Harbor installs the selected harness separately; model keys
are supplied at runtime. Agent and verifier use the same EDA base, while the
verifier receives its own trusted task files.

## Optional environment check

This checks the installed EDA software and PDK without a model API:

```bash
docker run --rm --network none \
  ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338 \
  python -I -B /opt/analog-layout/build-checks/check_runtime.py --out /tmp/eda-check
```

Exit code 0 means the component check passed. It does not evaluate a task GDS.

## Optional source build

From the repository root:

```bash
docker build --platform linux/amd64 --build-arg BUILD_JOBS=4 \
  -f docker/Dockerfile -t analoglayoutworld/eda:local .
```

The build downloads public dependencies. `docker/sources.lock.json`,
`docker/requirements.lock` and `docker/pdk/sky130/asset-manifest.json` identify
the source versions and assets. Build checks run before the image completes.
`BUILD_JOBS` controls compilation parallelism, not experiment concurrency.

For standalone evaluation, select a custom image with `alw verify --base-image
analoglayoutworld/eda:local` alongside the required task, submission and output
arguments. For Harbor, override the `ALW_BASE_IMAGE` build argument for **both**
Agent and verifier task images; a host environment variable alone does not
override a Dockerfile `ARG`. Normal experiments use the published digest.
