#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../../.." && pwd)
cd "$root"
mkdir -p build/sparse-gate-axi results/sparse-gate-axi
python3 - <<'PYLOCK'
from pathlib import Path
import json,subprocess
files=['rtl/sparse_gate/sg_fp32_pkg.sv','rtl/sparse_gate/sg_index_core.sv','rtl/sparse_gate_axi/sparse_gate_dma.sv','rtl/sparse_gate_axi/sparse_gate_axi.sv','rtl/sparse_gate_axi/tests/test_axi.cpp','rtl/sparse_gate_axi/tests/run.sh']
record={'schema':'sparse_gate_wrapper_validation_v1','status':'NOT_RUN','source_files':{f:{'bytes':Path(f).stat().st_size,'mtime_ns':Path(f).stat().st_mtime_ns} for f in files},'verilator':subprocess.check_output(['verilator','--version'],text=True).strip(),'compiler':subprocess.check_output(['g++','--version'],text=True).splitlines()[0],'seed':918273,'command':'bash rtl/sparse_gate_axi/tests/run.sh'}
Path('results/sparse-gate-axi/provenance.json').write_text(json.dumps(record,indent=2)+'\n')
PYLOCK
verilator --cc --exe --build -j 4 -Wno-fatal --top-module sparse_gate_axi \
  --Mdir "$root/build/sparse-gate-axi" -CFLAGS '-std=c++17 -O2' \
  rtl/sparse_gate/sg_fp32_pkg.sv rtl/sparse_gate/sg_index_core.sv \
  rtl/sparse_gate_axi/sparse_gate_dma.sv rtl/sparse_gate_axi/sparse_gate_axi.sv \
  "$root/rtl/sparse_gate_axi/tests/test_axi.cpp" \
  > results/sparse-gate-axi/build.log 2>&1
build/sparse-gate-axi/Vsparse_gate_axi | tee results/sparse-gate-axi/test.log
python3 - <<'PYCHECK'
from pathlib import Path
import json,re
p=Path('results/sparse-gate-axi/provenance.json');r=json.loads(p.read_text())
assert r['source_files']=={f:{'bytes':Path(f).stat().st_size,'mtime_ns':Path(f).stat().st_mtime_ns} for f in r['source_files']},'Source changed during run'
log=Path('results/sparse-gate-axi/test.log').read_text();assert 'PASS AXI256' in log and 'FAIL' not in log
r.update(status='PASS',binary_bytes=Path('build/sparse-gate-axi/Vsparse_gate_axi').stat().st_size,log_bytes=Path('results/sparse-gate-axi/test.log').stat().st_size,total_test_cycles=int(re.search(r'cycles=(\d+)\n?$',log).group(1)),jobs=[dict((k,int(v)) for k,v in re.findall(r'(\w+)=(\d+)',line)) for line in log.splitlines() if line.startswith('CASE ')],scope='AXI256 RTL simulation with independent byte-addressed test memory; separate from native-system integration')
p.write_text(json.dumps(r,indent=2)+'\n')
Path('evidence/sparse_gate').mkdir(parents=True,exist_ok=True)
Path('evidence/sparse_gate/wrapper.json').write_text(json.dumps(r,indent=2)+'\n')
PYCHECK
