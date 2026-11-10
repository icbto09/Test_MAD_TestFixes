#!/usr/bin/env bash
# Compile DXMT's .metal airconv shaders to .air and embed them as C headers.
# The DXMT meson flow does this via its metalir/hexdump generators; the iOS
# static-library flow consumes the headers directly, so this step reproduces
# that generation with the same compiler, flags, and xxd embedding.
set -euo pipefail
ROOT="${ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
SRC="$ROOT/dxmt/src/airconv/shaders"
OUT="$ROOT/build/dxmt-ios/shader-headers"
SHADERS=(air_msad air_samplepos air_tessellation)

# Metal toolchain 32023 (Xcode 27) gave __metal_atomic_fetch_add_explicit a fifth
# memory-flags argument. Xcode 26.6's toolchain (17F109) already defines
# __METAL_MEMORY_FLAGS_NONE__ but its builtin still takes four arguments, so an
# #ifdef on the macro picks the wrong form there. Ask the compiler instead: build
# a one-line probe with five arguments and use four if it is refused.
probe_dir="$(mktemp -d)"
trap 'rm -rf "$probe_dir"' EXIT
cat > "$probe_dir/probe.metal" <<'METAL'
#include <metal_stdlib>
using namespace metal;
int probe_next_index(threadgroup int *out_count) {
  return __metal_atomic_fetch_add_explicit(out_count, 1, int(memory_order_relaxed), __METAL_MEMORY_SCOPE_THREADGROUP__, __METAL_MEMORY_FLAGS_NONE__);
}
METAL
if xcrun -sdk macosx metal -o "$probe_dir/probe.air" -c "$probe_dir/probe.metal" \
     -std=metal3.1 --target=air64-apple-macos14.0 >/dev/null 2>&1; then
  ATOMIC_FLAGS_ARG=1
else
  ATOMIC_FLAGS_ARG=0
fi
echo "shader atomic: memory-flags argument=$ATOMIC_FLAGS_ARG"

python3 - "$SRC/air_tessellation.metal" "$ATOMIC_FLAGS_ARG" <<'PY'
import sys
from pathlib import Path
p = Path(sys.argv[1])
five = sys.argv[2] == "1"
s = p.read_text()
old4 = "  return __metal_atomic_fetch_add_explicit(out_count, 1, int(memory_order_relaxed), __METAL_MEMORY_SCOPE_THREADGROUP__);\n"
old5 = old4.replace("__);", "__, __METAL_MEMORY_FLAGS_NONE__);")
block = "#ifdef __METAL_MEMORY_FLAGS_NONE__\n" + old5 + "#else\n" + old4 + "#endif\n"
want = old5 if five else old4
if block in s:
    s = s.replace(block, want, 1)
elif want not in s:
    other = old4 if five else old5
    if other not in s:
        raise SystemExit(f"expected atomic call not found in {p}")
    s = s.replace(other, want, 1)
p.write_text(s)
PY

for name in "${SHADERS[@]}"; do
  [[ -f "$SRC/$name.metal" ]] || { echo "ERROR: missing shader source $SRC/$name.metal (is the dxmt submodule checked out?)" >&2; exit 1; }
  echo "shader $name: compiling"
  mkdir -p "$OUT"
  xcrun -sdk macosx metal -o "$OUT/$name.air" -c "$SRC/$name.metal" \
    -std=metal3.1 --target=air64-apple-macos14.0
  xxd -n "$name" -i "$OUT/$name.air" "$OUT/$name.h"
done
