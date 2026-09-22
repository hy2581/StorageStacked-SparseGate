#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SPARSE_GATE_BUILD_DIR=${SPARSE_GATE_BUILD_DIR:-"$SS_ROOT/build/sparse_gate_model"}
"$AXI_PYTHON" - <<'PY'
import hashlib, json, os, pathlib, re, shutil, subprocess, time
root=pathlib.Path(os.environ['SS_ROOT'])
out=pathlib.Path(os.environ['SPARSE_GATE_BUILD_DIR']).resolve()
out.mkdir(parents=True,exist_ok=True)
obj=out/'obj'; obj.mkdir(exist_ok=True)
sources=['rtl/sparse_gate/sg_fp32_pkg.sv','rtl/sparse_gate/sg_index_core.sv',
 'rtl/sparse_gate_axi/sparse_gate_dma.sv','rtl/sparse_gate_axi/sparse_gate_axi.sv',
 'gem5_axi/sparse_gate_model.cpp','gem5_axi/sparse_gate_abi.h','env/build_sparse_gate.sh']
sha=lambda p:hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
before={p:sha(root/p) for p in sources}
identity=hashlib.sha256(json.dumps(before,sort_keys=True).encode()).hexdigest()
(obj/'sparse_gate_build_id.h').write_text('#define SPARSE_GATE_BUILD_ID "'+identity+'"\n')
(obj/'exports.map').write_text('{ global: sparse_gate_*; local: *; };\n')
compiler=os.environ['AXI_CXX']
verilator=shutil.which(os.environ.get('SPARSE_GATE_VERILATOR','verilator'))
if not verilator:raise RuntimeError('Verilator executable not found')
configuration=subprocess.check_output([verilator,'-V'],text=True)
roots=re.findall(r'^\s*VERILATOR_ROOT\s*=\s*(\S+)\s*$',configuration,re.M)
verilator_root=pathlib.Path(os.environ.get('VERILATOR_ROOT') or (roots[0] if roots else '')).resolve()
runtime=verilator_root/'include'
runtime_sources=[runtime/p for p in ('verilated.cpp','verilated_threads.cpp','verilated_vcd_c.cpp')]
if not all(p.is_file() for p in runtime_sources+[runtime/'verilated.h']):
 raise RuntimeError('Cannot resolve Verilator runtime from VERILATOR_ROOT or verilator -V')
runtime_before={str(p):sha(p) for p in runtime_sources+[runtime/'verilated.h']}
commands=[[verilator,'--cc','--assert','--trace','--timescale-override','1fs/1fs',
 '--top-module','sparse_gate_axi','--Mdir',str(obj),'-Wno-fatal','-CFLAGS','-fPIC -O2 -std=c++17',
 *[str(root/p) for p in sources[:4]]],
 ['make','-C',str(obj),'-f','Vsparse_gate_axi.mk','-j'+os.environ.get('SPARSE_GATE_JOBS','4'),
  'CXX='+compiler,'OPT_FAST=-O2'],
 [compiler,'-shared','-fPIC','-O2','-std=c++17','-I'+str(obj),'-I'+str(root/'gem5_axi'),
  '-I'+str(runtime),'-I'+str(runtime/'vltstd'),
  str(root/'gem5_axi/sparse_gate_model.cpp'),*[str(p) for p in runtime_sources],
  str(obj/'Vsparse_gate_axi__ALL.a'),'-pthread','-Wl,--version-script='+str(obj/'exports.map'),
  '-o',str(out/'libsparse_gate_model.so.tmp')]]
record={'schema':'sparse_gate_model_build_v1','status':'BUILDING','build_id':identity,
 'source_sha256':before,'commands':commands,'time_unit':'1fs',
 'scope':'Verilator cycle model; no SystemC or private memory image',
 'verilator':subprocess.check_output([verilator,'--version'],text=True).strip(),
 'verilator_executable':verilator,'verilator_root':str(verilator_root),'verilator_runtime_sha256':runtime_before,
 'compiler':subprocess.check_output([compiler,'--version'],text=True).splitlines()[0]}
manifest=out/'build.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
started=time.monotonic()
try:
 for cmd in commands: subprocess.run(cmd,cwd=root,check=True)
 after={p:sha(root/p) for p in sources}
 if before!=after: raise RuntimeError('RTL/adapter source changed during build; rebuild required')
 if runtime_before!={p:sha(p) for p in runtime_before}:raise RuntimeError('Verilator runtime changed during build')
 (out/'libsparse_gate_model.so.tmp').replace(out/'libsparse_gate_model.so')
 record.update(status='BUILT_NOT_VALIDATED',library=str(out/'libsparse_gate_model.so'),
  library_sha256=sha(out/'libsparse_gate_model.so'),source_sha256_after=after)
except Exception as exc:
 record.update(status='FAILED',error=str(exc));raise
finally:
 record['elapsed_seconds']=time.monotonic()-started
 manifest.write_text(json.dumps(record,indent=2)+'\n')
PY
