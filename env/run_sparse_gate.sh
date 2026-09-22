#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
destination=${1:?Usage: run_sparse_gate.sh NEW_RESULT_DIRECTORY [cpu|three|all|cpu-slow|top512]}
mode=${2:-all}
[[ "$mode" == cpu || "$mode" == three || "$mode" == all || "$mode" == cpu-slow || "$mode" == top512 ]] || { echo 'Invalid suite mode' >&2; exit 1; }
[[ ! -e "$destination" ]] || { echo "Result directory exists: $destination" >&2; exit 1; }
mkdir -p "$destination" "$SS_ROOT/build/sparse_gate_workloads"
destination=$(cd "$destination" && pwd)
gate_library="$SS_ROOT/build/sparse_gate_model/libsparse_gate_model.so"
gate_manifest="$SS_ROOT/build/sparse_gate_model/build.json"
[[ -f "$gate_library" && -f "$gate_manifest" && -x "$AXI_GEM5_BIN" ]] || { echo 'Build gem5 and the RTL model first' >&2; exit 1; }
"$AXI_PYTHON" "$SS_ROOT/env/check_sources.py"
"$AXI_PYTHON" "$SS_ROOT/env/record.py" "$destination/environment"
cp "$gate_manifest" "$destination/environment/gate_model_build.json"
export LD_LIBRARY_PATH="$SS_DEPS_ROOT/xpu-native/lib:$VORTEX_HOME/third_party/ramulator:$LD_LIBRARY_PATH"
record_case() {
    "$AXI_PYTHON" - "$1" "$binary" <<'PY'
import hashlib,json,os,pathlib,sys
root=pathlib.Path(os.environ['SS_ROOT']);d=pathlib.Path(sys.argv[1])
names=['gem5_axi/Gem5Axi.py','gem5_axi/SConscript','gem5_axi/axi_demo.cc','gem5_axi/axi_master.cc','gem5_axi/aou_backend.cc',
'gem5_axi/memsim_backend.cc','gem5_axi/sparse_gate_backend.cc','gem5_axi/sparse_gate_backend.hh',
'gem5_axi/sparse_gate_abi.h','gem5_axi/sparse_gate_model.cpp','gem5_axi/configs/run.py',
'gem5_axi/configs/run_xpu.py','gem5_axi/workloads/sparse_gate_client.h','gem5_axi/workloads/sparse_gate_check.c',
'gem5_new/workloads/three_source_gate/host_main.cpp','research/fixtures/system_smoke.h',
'research/fixtures/csa2_real_weights_fixture.h','gem5_axi/scripts/check_sparse_gate.py',
'research/fixtures/csa2_top512_fixture.h','gem5_axi/workloads/sparse_gate_top512.c',
'gem5_axi/scripts/check_aou.py','gem5_axi/scripts/inspect_link.py','env/run_sparse_gate.sh']
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
hashes={p:sha(root/p) for p in names};file=d/'integration_sources.json';binary=pathlib.Path(sys.argv[2])
if file.exists():
 old=json.loads(file.read_text())
 if old['source_sha256']!=hashes or old['workload_sha256']!=sha(binary):raise SystemExit('Integration source/workload changed while running')
 old['verified_after_run']=True;file.write_text(json.dumps(old,indent=2)+'\n')
else:file.write_text(json.dumps({'source_sha256':hashes,'workload_path':str(binary),'workload_sha256':sha(binary),'verified_after_run':False},indent=2)+'\n')
PY
}
verify_case() {
    local dir=$1 fixture=$2
    record_case "$dir"
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/inspect_link.py" "$dir" > "$dir/link_verification.log" 2>&1
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_aou.py" "$dir" --gate > "$dir/aou_verification.log" 2>&1
    "$AXI_PYTHON" "$AXI_PROJECT_DIR/scripts/check_sparse_gate.py" "$dir" --fixture "$fixture" --model-manifest "$gate_manifest" > "$dir/gate_verification.log" 2>&1
    trace_options=();[[ "$dir" != */cpu_* ]] || trace_options+=(--allow-single-source)
    "$AXI_PYTHON" -m hettrace validate "$dir/hettrace" --ticks-per-second 1000000000000000 "${trace_options[@]}" > "$dir/hettrace/validation.txt"
}
if [[ "$mode" == cpu || "$mode" == all || "$mode" == cpu-slow || "$mode" == top512 ]]; then
    fixtures=(smoke real-weights);scale=1;suffix=''
    if [[ "$mode" == cpu-slow ]]; then fixtures=(real-weights);scale=4;suffix=_slow;fi
    if [[ "$mode" == top512 ]]; then fixtures=(top512);fi
    for fixture in "${fixtures[@]}"; do
        flags=();[[ "$fixture" != real-weights ]] || flags+=(-DSG_USE_REAL_FIXTURE)
        binary="$destination/environment/cpu_$fixture"
        source="$AXI_PROJECT_DIR/workloads/sparse_gate_check.c"
        if [[ "$fixture" == top512 ]];then source="$AXI_PROJECT_DIR/workloads/sparse_gate_top512.c";fi
        "$AXI_CC" -O2 -Wall -Wextra -Werror -static -nostdlib -ffreestanding -fno-stack-protector -fno-pie -no-pie -Wl,-e,_start \
            "${flags[@]}" "$source" -o "$binary"
        dir="$destination/cpu_$fixture$suffix";mkdir -p "$dir";record_case "$dir"
        echo "Running CPU gate $fixture"
        "$AXI_GEM5_BIN" --listener-mode=off -d "$dir" "$AXI_PROJECT_DIR/configs/run.py" \
            --mode cpu --binary "$binary" --backend aou --memory-backend memsim --het-trace \
            --gate-enable --gate-library "$gate_library" --memsim-scale "$scale" --max-ticks 200000000000000 > "$dir/run.log" 2>&1
        verify_case "$dir" "$fixture"
    done
fi
if [[ "$mode" == three || "$mode" == all ]]; then
    binary="$destination/environment/three_source_gate"
    "$AXI_CXX" -O2 -Wall -Wextra -std=c++17 -I"$VORTEX_HOME/sw/runtime/include" \
        "$HET_PROJECT_ROOT/workloads/three_source_gate/host_main.cpp" \
        -L"$VORTEX_BUILD/sw/runtime" -lvortex -Wl,-rpath,"$VORTEX_BUILD/sw/runtime" -o "$binary"
    dir="$destination/three_smoke";mkdir -p "$dir";record_case "$dir"
    echo 'Running original three-source calculations followed by gate commands (coexistence)'
    "$AXI_GEM5_BIN" --listener-mode=off -d "$dir" "$AXI_PROJECT_DIR/configs/run_xpu.py" \
        --cmd "$binary" --options="-k $VORTEX_BUILD/tests/regression/vecadd/kernel.vxbin" \
        --vortex-library "$VORTEX_BUILD/sim/simx/libvortex-gem5.so" --vortex-host-rt-dir "$VORTEX_BUILD/sw/runtime" \
        --npu-library "$CORALNPU_HOME/bazel-bin/gem5int/libcoralnpu-gem5.so" --npu-kernel "$SS_ROOT/build/xpu/ddr_touch.elf" \
        --gate-enable --gate-library "$gate_library" > "$dir/run.log" 2>&1
    verify_case "$dir" smoke
fi
"$AXI_PYTHON" - "$destination" "$mode" <<'PY'
import hashlib,json,pathlib,sys
root=pathlib.Path(sys.argv[1]);mode=sys.argv[2]
required=(['cpu_smoke','cpu_real-weights'] if mode in ('cpu','all') else [])+(['three_smoke'] if mode in ('three','all') else [])
if mode=='cpu-slow':required=['cpu_real-weights_slow']
if mode=='top512':required=['cpu_top512']
cases={}
for name in required:
 p=root/name/'sparse_gate_check.json';d=json.loads(p.read_text())
 if not d['passed']:raise SystemExit('Case not passed: '+name)
 cases[name]={'passed':True,'summary':str(p),'summary_sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
result={'schema':'sparse_gate_system_suite_v1','passed':True,'suite':mode,'cases':cases,
 'scope':'Real CPU MMIO and RTL DMA through shared online memory; three-source case is configuration coexistence, not overlap stress'}
(root/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
PY
