ARG ALW_BASE_IMAGE=ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338
FROM ${ALW_BASE_IMAGE}
USER root
WORKDIR /alb-workspace
COPY environment/GUIDE.md environment/GUIDE.zh-CN.md environment/DEVICE_API.md environment/DEVICE_API.zh-CN.md environment/eda_env.sh /alb-workspace/
COPY environment/task/ /alb-workspace/task/
COPY tests/ /tests/
ENTRYPOINT []
CMD ["sleep", "infinity"]
