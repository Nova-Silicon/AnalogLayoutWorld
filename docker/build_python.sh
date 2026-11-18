#!/usr/bin/env bash
set -Eeuo pipefail
jobs=${BUILD_JOBS:-4}
[[ "$jobs" =~ ^[0-9]+$ && "$jobs" -ge 1 && "$jobs" -le 16 ]] || { printf 'BUILD_JOBS must be 1..16\n' >&2; exit 2; }
prefix=/opt/analog-layout/python
mkdir -p /build/python /opt/analog-layout/provenance
tar --no-same-owner -xJf /downloads/Python-3.12.14.tar.xz -C /build/python
cd /build/python/Python-3.12.14
# Preserve the qualified configure flags. This does not replace OS Python.
CFLAGS='-O2 -g0' ./configure --prefix="$prefix" --with-ensurepip=install \
    --disable-test-modules --without-static-libpython
make -j"$jobs"
make altinstall
ln -s python3.12 "$prefix/bin/python3"
ln -s python3.12 "$prefix/bin/python"
ln -s pip3.12 "$prefix/bin/pip"
ln -s pip3.12 "$prefix/bin/pip3"
"$prefix/bin/python" -I -c 'import ssl,sqlite3,bz2,lzma,ctypes,readline,hashlib; import sys; assert sys.version_info[:3] == (3,12,14); print(sys.version)'
install -m 0644 LICENSE /opt/analog-layout/provenance/Python-LICENSE
