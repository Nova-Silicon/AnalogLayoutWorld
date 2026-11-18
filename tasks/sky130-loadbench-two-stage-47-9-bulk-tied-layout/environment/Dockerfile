ARG ALW_BASE_IMAGE=ghcr.io/nova-silicon/analoglayoutworld@sha256:f922e79ebbac026ed9d15987924867ba6fef4270a5c4994579500e9138bf8338
FROM ${ALW_BASE_IMAGE}
USER root
WORKDIR /alb-workspace
COPY GUIDE.md GUIDE.zh-CN.md DEVICE_API.md DEVICE_API.zh-CN.md eda_env.sh /alb-workspace/
COPY task/ /alb-workspace/task/
ENTRYPOINT []
CMD ["sleep", "infinity"]
