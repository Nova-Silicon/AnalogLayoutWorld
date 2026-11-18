# Build context is the repository root. First release targets Linux/amd64.
FROM ubuntu:22.04@sha256:45e9ddc6895604674618a409ca9f73d301da8fdb75fe330e8e9a27b3b219e4ad AS build-deps
ARG DEBIAN_FRONTEND=noninteractive
RUN test "$(dpkg --print-architecture)" = amd64 \
    && apt-get update && apt-get install -y --no-install-recommends \
       ca-certificates curl python3 build-essential pkg-config \
       autoconf automake libtool bison flex \
       libssl-dev zlib1g-dev libffi-dev liblzma-dev libbz2-dev \
       libreadline-dev libsqlite3-dev libgdbm-dev libncursesw5-dev uuid-dev \
       tcl8.6-dev tk8.6-dev libx11-dev libxext-dev libxt-dev \
       ghostscript xz-utils \
    && rm -rf /var/lib/apt/lists/*

FROM build-deps AS sources
COPY docker/sources.lock.json docker/fetch_sources.py /build-input/
RUN python3 /build-input/fetch_sources.py --destination /downloads

FROM sources AS python-build
ARG BUILD_JOBS=4
COPY docker/build_python.sh /build-input/
RUN BUILD_JOBS="$BUILD_JOBS" bash /build-input/build_python.sh
COPY docker/requirements.lock docker/python-artifacts.lock.json docker/build-requirements.lock /build-input/
RUN /opt/analog-layout/python/bin/python -I -m pip install \
      --index-url https://pypi.org/simple --disable-pip-version-check \
      --no-cache-dir --no-compile --require-hashes --only-binary=:all: \
      -r /build-input/build-requirements.lock \
    && /opt/analog-layout/python/bin/python -I -m pip install \
      --index-url https://pypi.org/simple --disable-pip-version-check \
      --no-cache-dir --no-compile --require-hashes --no-build-isolation \
      --only-binary=:all: --no-binary=rectpack \
      --report /opt/analog-layout/provenance/python-install-report.json \
      -r /build-input/requirements.lock \
    && /opt/analog-layout/python/bin/python -I -m pip uninstall --yes setuptools \
    && /opt/analog-layout/python/bin/python -I -m pip check \
    && cp /build-input/requirements.lock /build-input/python-artifacts.lock.json /build-input/build-requirements.lock /opt/analog-layout/provenance/

FROM sources AS native-build
ARG BUILD_JOBS=4
COPY docker/build_native.sh /build-input/
RUN BUILD_JOBS="$BUILD_JOBS" bash /build-input/build_native.sh

FROM ubuntu:22.04@sha256:45e9ddc6895604674618a409ca9f73d301da8fdb75fe330e8e9a27b3b219e4ad AS runtime
ARG DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      bash ca-certificates curl wget git less jq file unzip xz-utils \
      build-essential pkg-config patch procps time \
      python3 libpython3.10 libruby3.0 tcl8.6 tk8.6 \
      libqt5core5a libqt5designer5 libqt5gui5 libqt5multimedia5 \
      libqt5multimediawidgets5 libqt5network5 libqt5opengl5 libqt5printsupport5 \
      libqt5sql5 libqt5svg5 libqt5widgets5 libqt5xml5 libqt5xmlpatterns5 \
      libgit2-1.1 libstdc++6 libgomp1 libx11-6 libxext6 libxt6 \
      libssl3 libffi8 liblzma5 libbz2-1.0 libreadline8 libsqlite3-0 libgdbm6 \
      libncursesw6 libuuid1 zlib1g fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=python-build /opt/analog-layout/python/ /opt/analog-layout/python/
COPY --from=python-build /opt/analog-layout/provenance/ /opt/analog-layout/provenance/
COPY --from=native-build /opt/analog-layout/tools/ /opt/analog-layout/tools/
COPY --from=native-build /opt/analog-layout/agent/ /opt/analog-layout/agent/
COPY docker/pdk/sky130/ /opt/analog-layout/pdks/sky130/
COPY docker/sources.lock.json /opt/analog-layout/provenance/sources.lock.json
# Plain-text editions of the five Magic help pages used in the paper environment.
COPY docker/magic-docs/text/ /opt/analog-layout/tools/magic/lib/magic/doc/text/
COPY docker/finalize_runtime.py docker/check_runtime.py /opt/analog-layout/build-checks/
COPY docker/pdk/verify.py /opt/analog-layout/build-checks/verify_pdk.py
ENV PATH=/opt/analog-layout/python/bin:/opt/analog-layout/tools/bin:/opt/analog-layout/agent/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PDK_ROOT=/opt/analog-layout/pdks/sky130 \
    PYTHONDONTWRITEBYTECODE=1 \
    MPLBACKEND=Agg \
    QT_QPA_PLATFORM=offscreen \
    ALB_PYTHON=/opt/analog-layout/python/bin/python3.12
RUN /opt/analog-layout/python/bin/python -I -B /opt/analog-layout/build-checks/verify_pdk.py --root /opt/analog-layout/pdks/sky130 \
    && /opt/analog-layout/python/bin/python -I -B /opt/analog-layout/build-checks/finalize_runtime.py \
    && /opt/analog-layout/python/bin/python -I -B /opt/analog-layout/build-checks/check_runtime.py --out /opt/analog-layout/provenance/runtime-check \
    && /opt/analog-layout/python/bin/python -I -m pip check \
    && dpkg-query -W -f='${Package}\t${Version}\n' > /opt/analog-layout/provenance/system-packages.tsv
WORKDIR /alb-workspace
CMD ["sleep", "infinity"]
