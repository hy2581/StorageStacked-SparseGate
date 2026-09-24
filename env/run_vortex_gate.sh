#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
destination=${1:?Usage: run_vortex_gate.sh NEW_RESULT_DIRECTORY [small|long]}
profile=${2:-small}
case "$profile" in
    small) workload=sparse_gate_vortex_cp.cpp ;;
    long) workload=sparse_gate_vortex_long.cpp ;;
    *) echo "Unknown gate profile: $profile" >&2; exit 2 ;;
esac
[[ ! -e "$destination" ]] || { echo "Result directory exists: $destination" >&2; exit 1; }
model="$SS_ROOT/build/sparse_gate_model_vortex"
"$AXI_PYTHON" - "$model/build.json" <<'PY'
import json,sys
d=json.load(open(sys.argv[1]))
assert d['status']=='BUILT_NOT_VALIDATED'
assert d['parameters']=={'mem_base':0x190000000,'mem_bytes':0x100000,'reg_base':0x1900f0000}
PY
[[ -f "$model/libsparse_gate_model.so" && -x "$AXI_GEM5_BIN" ]] || { echo 'Missing Vortex gate model or gem5' >&2; exit 1; }
mkdir -p "$destination"
destination=$(cd "$destination" && pwd)
binary="$destination/sparse_gate_vortex_cp"
"$AXI_CXX" -O2 -Wall -Wextra -Werror -std=c++17 \
    -I"$VORTEX_HOME/sw/runtime/include" \
    "$AXI_PROJECT_DIR/workloads/$workload" \
    -L"$VORTEX_BUILD/sw/runtime" -lvortex \
    -Wl,-rpath,"$VORTEX_BUILD/sw/runtime" -o "$binary"
export LD_LIBRARY_PATH="$SS_DEPS_ROOT/xpu-native/lib:$VORTEX_HOME/third_party/ramulator:$LD_LIBRARY_PATH"
case_dir="$destination/case"
mkdir -p "$case_dir"
"$AXI_GEM5_BIN" --listener-mode=off -d "$case_dir" "$AXI_PROJECT_DIR/configs/run_vortex.py" \
    --cmd "$binary" \
    --vortex-library "$VORTEX_BUILD/sim/simx/libvortex-gem5.so" \
    --vortex-host-rt-dir "$VORTEX_BUILD/sw/runtime" \
    --gate-library "$model/libsparse_gate_model.so" \
    --gate-base 0x1900f0000 --max-ticks 100000000000000 \
    > "$case_dir/run.log" 2>&1
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/inspect_link.py" "$case_dir" > "$case_dir/link_verification.log"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_aou.py" "$case_dir" --gate > "$case_dir/aou_verification.log"
"$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_vortex_gate.py" "$case_dir" \
    --binary "$binary" --model-manifest "$model/build.json" --profile "$profile" \
    > "$case_dir/vortex_gate_verification.log"
echo "Vortex CP gate PASS: $case_dir/vortex_gate_check.json"
