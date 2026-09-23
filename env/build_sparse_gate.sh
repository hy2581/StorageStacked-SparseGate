#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "${BASH_SOURCE[0]}")/activate.sh"
export SPARSE_GATE_BUILD_DIR=${SPARSE_GATE_BUILD_DIR:-"$SS_ROOT/build/sparse_gate_model_vortex"}
"$AXI_PYTHON" - <<'PY'
import datetime, json, os, pathlib, re, shutil, subprocess, time
root=pathlib.Path(os.environ['SS_ROOT'])
out=pathlib.Path(os.environ['SPARSE_GATE_BUILD_DIR']).resolve()
out.mkdir(parents=True,exist_ok=True)
mem_base=int(os.environ.get('SPARSE_GATE_MEM_BASE','0x190000000'),0)
mem_bytes=int(os.environ.get('SPARSE_GATE_MEM_BYTES','0x100000'),0)
reg_base=int(os.environ.get('SPARSE_GATE_REG_BASE','0x1900f0000'),0)
if mem_base & 4095 or mem_bytes != 0x100000 or reg_base != mem_base+0xf0000:
 raise RuntimeError('SparseGate requires an aligned 1 MiB window with the register page at +0xf0000')
obj=out/'obj'; obj.mkdir(exist_ok=True)
sources=['rtl/sparse_gate/sg_fp32_pkg.sv','rtl/sparse_gate/sg_index_core.sv',
 'rtl/sparse_gate_axi/sparse_gate_dma.sv','rtl/sparse_gate_axi/sparse_gate_axi.sv',
 'gem5_axi/sparse_gate_model.cpp','gem5_axi/sparse_gate_abi.h','env/build_sparse_gate.sh']
version=lambda p:{'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
before={p:version(root/p) for p in sources}
parameters=dict(mem_base=mem_base,mem_bytes=mem_bytes,reg_base=reg_base)
identity='vortex-gate-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S')+'-'+str(os.getpid())
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
runtime_before={str(p):version(p) for p in runtime_sources+[runtime/'verilated.h']}
commands=[[verilator,'--cc','--assert','--trace','--timescale-override','1fs/1fs',
 '--top-module','sparse_gate_axi','--Mdir',str(obj),'-Wno-fatal','-CFLAGS','-fPIC -O2 -std=c++17',
 "-GMEM_BASE=64'h"+format(mem_base,'x'),"-GMEM_BYTES=64'h"+format(mem_bytes,'x'),
 "-GREG_BASE=64'h"+format(reg_base,'x'),
 *[str(root/p) for p in sources[:4]]],
 ['make','-C',str(obj),'-f','Vsparse_gate_axi.mk','-j'+os.environ.get('SPARSE_GATE_JOBS','4'),
  'CXX='+compiler,'OPT_FAST=-O2'],
 [compiler,'-shared','-fPIC','-O2','-std=c++17','-I'+str(obj),'-I'+str(root/'gem5_axi'),
  '-I'+str(runtime),'-I'+str(runtime/'vltstd'),
  str(root/'gem5_axi/sparse_gate_model.cpp'),*[str(p) for p in runtime_sources],
  str(obj/'Vsparse_gate_axi__ALL.a'),'-pthread','-Wl,--version-script='+str(obj/'exports.map'),
  '-o',str(out/'libsparse_gate_model.so.tmp')]]
record={'schema':'sparse_gate_model_build_v1','status':'BUILDING','build_id':identity,
 'source_files':before,'parameters':parameters,'commands':commands,'time_unit':'1fs',
 'scope':'Verilator cycle model; no SystemC or private memory image',
 'verilator':subprocess.check_output([verilator,'--version'],text=True).strip(),
 'verilator_executable':verilator,'verilator_root':str(verilator_root),'verilator_runtime_files':runtime_before,
 'compiler':subprocess.check_output([compiler,'--version'],text=True).splitlines()[0]}
manifest=out/'build.json';manifest.write_text(json.dumps(record,indent=2)+'\n')
started=time.monotonic()
try:
 for cmd in commands: subprocess.run(cmd,cwd=root,check=True)
 after={p:version(root/p) for p in sources}
 if before!=after: raise RuntimeError('RTL/adapter source changed during build; rebuild required')
 if runtime_before!={p:version(pathlib.Path(p)) for p in runtime_before}:raise RuntimeError('Verilator runtime changed during build')
 (out/'libsparse_gate_model.so.tmp').replace(out/'libsparse_gate_model.so')
 record.update(status='BUILT_NOT_VALIDATED',library=str(out/'libsparse_gate_model.so'),
  library_bytes=(out/'libsparse_gate_model.so').stat().st_size,source_files_after=after)
except Exception as exc:
 record.update(status='FAILED',error=str(exc));raise
finally:
 record['elapsed_seconds']=time.monotonic()-started
 manifest.write_text(json.dumps(record,indent=2)+'\n')
PY
