#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
out=${1:?Usage: test_sparse_gate_backend.sh NEW_RESULT_DIRECTORY}
[[ ! -e "$out" ]] || { echo 'Output exists' >&2; exit 1; }
mkdir -p "$out";out=$(cd "$out" && pwd)
contract_cxx=${SPARSE_GATE_TEST_CXX:-g++}
"$contract_cxx" --version >"$out/compiler.txt"
"$contract_cxx" -std=c++17 -O2 -Wall -Wextra -Werror \
  -I"$root/gem5_axi/tests/clock_shim" -I"$root/gem5_axi" -I"$root/axi2flit/systemc/include" \
  "$root/gem5_axi/sparse_gate_backend.cc" "$root/gem5_axi/tests/sparse_gate_backend_test.cc" \
  -lsystemc -ldl -o "$out/test"
"$out/test" "$root/build/sparse_gate_model/libsparse_gate_model.so" "$out" >"$out/run.log" 2>&1
python3 - "$root" "$out" <<'PY'
import csv,hashlib,json,pathlib,sys
r,d=map(pathlib.Path,sys.argv[1:]);sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
s=json.loads((d/'sparse_gate_summary.json').read_text());e=list(csv.DictReader((d/'sparse_gate_events.csv').open()))
assert s['drained'] and s['mmio_rejected']==4 and s['host_completed']==7 and s['memory_issued']==s['dma_reads']==s['dma_writes']==0
assert len([v for v in e if v['event']=='mmio_reject'])==4 and not any(v['event'].startswith('M_') for v in e)
assert 'BACKEND CONTRACT PASS' in (d/'run.log').read_text()
sources=['gem5_axi/sparse_gate_backend.cc','gem5_axi/sparse_gate_backend.hh','gem5_axi/tests/sparse_gate_backend_test.cc','gem5_axi/tests/clock_shim/sim/cur_tick.hh','env/test_sparse_gate_backend.sh']
result={'passed':True,'cases':7,'exclusive_rejections':4,'compiler':(d/'compiler.txt').read_text().splitlines()[0],'scope':'Actual C++ adapter plus actual RTL DLL under standalone SystemC; test-only curTick shim, no gem5 or memory performance claim','source_sha256':{p:sha(r/p) for p in sources},'library_sha256':sha(r/'build/sparse_gate_model/libsparse_gate_model.so'),'artifacts_sha256':{p.name:sha(p) for p in d.iterdir() if p.is_file()}}
(d/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
PY
