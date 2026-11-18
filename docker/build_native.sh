#!/usr/bin/env bash
set -Eeuo pipefail
jobs=${BUILD_JOBS:-4}
[[ "$jobs" =~ ^[0-9]+$ && "$jobs" -ge 1 && "$jobs" -le 16 ]] || { printf 'BUILD_JOBS must be 1..16\n' >&2; exit 2; }
tools=/opt/analog-layout/tools
mkdir -p /build/native "$tools/bin" "$tools/licenses" /opt/analog-layout/agent/bin
cd /build/native

mkdir klayout
dpkg-deb -x /downloads/klayout_0.30.12-1_amd64.deb klayout
mkdir -p "$tools/klayout"
cp -a klayout/usr "$tools/klayout/"
cat > "$tools/bin/klayout" <<'EOF'
#!/usr/bin/env bash
# Native KLayout uses Ubuntu Python 3.10, independently of EDA Python 3.12.
unset PYTHONHOME PYTHONPATH
export LD_LIBRARY_PATH=/opt/analog-layout/tools/klayout/usr/lib/klayout:/opt/analog-layout/tools/klayout/usr/lib/klayout/db_plugins:/opt/analog-layout/tools/klayout/usr/lib/klayout/lay_plugins
export QT_QPA_PLATFORM=${QT_QPA_PLATFORM:-offscreen}
exec /opt/analog-layout/tools/klayout/usr/bin/klayout "$@"
EOF
chmod 0755 "$tools/bin/klayout"

tar --no-same-owner -xzf /downloads/ngspice-46.tar.gz
cd ngspice-46
./configure --prefix="$tools/ngspice" --with-x=no --with-readline=no \
    --enable-xspice --enable-cider --disable-debug CFLAGS=-O2 LDFLAGS=-s
make -j"$jobs"
make install
install -m 0644 COPYING "$tools/licenses/ngspice-COPYING"
ln -s ../ngspice/bin/ngspice "$tools/bin/ngspice"
mkdir -p "$tools/ngspice/share/doc/ngspice"
install -m 0644 /downloads/ngspice-46-manual.pdf "$tools/ngspice/share/doc/ngspice/"
gs -q -dSAFER -dNOPAUSE -dBATCH -sDEVICE=txtwrite \
    -sOutputFile="$tools/ngspice/share/doc/ngspice/ngspice-46-manual.txt" \
    "$tools/ngspice/share/doc/ngspice/ngspice-46-manual.pdf"
cd /build/native

tar --no-same-owner -xzf /downloads/magic-bed8d4ff84333767aa923d469d339cd05c56a00a.tar.gz
cd magic-bed8d4ff84333767aa923d469d339cd05c56a00a
test "$(cat VERSION)" = 8.3.685
./configure --prefix="$tools/magic" --with-tcl=/usr/lib/x86_64-linux-gnu/tcl8.6 \
    --with-tk=/usr/lib/x86_64-linux-gnu/tk8.6 --with-tclincls=/usr/include/tcl8.6 \
    --with-tkincls=/usr/include/tcl8.6 --with-tcllibs=/usr/lib/x86_64-linux-gnu \
    --with-tklibs=/usr/lib/x86_64-linux-gnu --with-wish=/usr/bin/wish8.6 \
    --with-x --without-opengl --without-cairo --disable-readline --disable-threads \
    --disable-ccache CFLAGS=-O2 LDFLAGS=-s
make -j"$jobs" MAGIC_COMMIT=bed8d4ff84333767aa923d469d339cd05c56a00a
make install MAGIC_COMMIT=bed8d4ff84333767aa923d469d339cd05c56a00a
install -m 0644 LICENSE "$tools/licenses/magic-LICENSE"
ln -s ../magic/bin/magic "$tools/bin/magic"
cd /build/native

tar --no-same-owner -xzf /downloads/netgen-3cb047bd6b55ae09c8eefeb479b4fe746cfdb948.tar.gz
cd netgen-3cb047bd6b55ae09c8eefeb479b4fe746cfdb948
test "$(cat VERSION)" = 1.5.324
./configure --prefix="$tools/netgen" --with-interpreter=tcl \
    --with-tcl=/usr/lib/x86_64-linux-gnu/tcl8.6 --with-tk=/usr/lib/x86_64-linux-gnu/tk8.6 \
    --with-tclincls=/usr/include/tcl8.6 --with-tkincls=/usr/include/tcl8.6 \
    --with-tcllibs=/usr/lib/x86_64-linux-gnu --with-tklibs=/usr/lib/x86_64-linux-gnu \
    --with-x CFLAGS=-O2 LDFLAGS=-s
make -j"$jobs" EXTRA_CFLAGS=-I/usr/include/tcl8.6 tcllibrary
make EXTRA_CFLAGS=-I/usr/include/tcl8.6 install
test -f "$tools/netgen/lib/netgen/tcl/tclnetgen.so"
install -m 0644 Copying "$tools/licenses/netgen-Copying"
ln -s ../netgen/bin/netgen "$tools/bin/netgen"
cd /build/native

tar --no-same-owner -xJf /downloads/node-v22.23.3-linux-x64.tar.xz
cp -a node-v22.23.3-linux-x64/. /opt/analog-layout/agent/
tar --no-same-owner -xzf /downloads/ripgrep-15.1.0-x86_64-unknown-linux-musl.tar.gz
install -m 0755 ripgrep-15.1.0-x86_64-unknown-linux-musl/rg /opt/analog-layout/agent/bin/rg
mkdir -p /opt/analog-layout/agent/share/licenses
for name in COPYING LICENSE-MIT UNLICENSE; do
    install -m 0644 "ripgrep-15.1.0-x86_64-unknown-linux-musl/$name" \
        "/opt/analog-layout/agent/share/licenses/ripgrep-$name"
done
# No model harness, credentials, startup configuration or benchmark task is installed.
