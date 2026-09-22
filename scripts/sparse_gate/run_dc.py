#!/usr/bin/env python3
"""Freeze exact core sources and run native Design Compiler in an isolated directory."""
import argparse,hashlib,json,os,shutil,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
DEFAULT_LIB=os.environ.get('SG_LIBRARY')
DEFAULT_DC=os.environ.get('SG_DC') or shutil.which('dc_shell')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out',type=Path,default=ROOT/'results/sparse-gate/dc-h32-k512-l16')
    ap.add_argument('--library',type=Path,default=DEFAULT_LIB,required=not DEFAULT_LIB,help='Authorized .db path; defaults to SG_LIBRARY when set')
    ap.add_argument('--dc',type=Path,default=DEFAULT_DC,required=not DEFAULT_DC,help='dc_shell path; defaults to SG_DC or PATH lookup')
    a=ap.parse_args();a.out=a.out.expanduser().resolve();a.library=a.library.expanduser().resolve()
    # Keep the launcher symlink/name: resolving it can change an EDA wrapper's argv[0].
    a.dc=Path(shutil.which(str(a.dc)) or str(a.dc)).expanduser().absolute()
    if not a.library.is_file():ap.error('The supplied library is not a file')
    if not a.dc.is_file() or not os.access(a.dc,os.X_OK):ap.error('The supplied dc_shell is not an executable file')
    if a.out.exists():raise SystemExit('Output directory already exists; choose a new directory to retain frozen evidence.')
    a.out.mkdir(parents=True);src=a.out/'source';src.mkdir()
    files=[ROOT/'rtl/sparse_gate/sg_fp32_pkg.sv',ROOT/'rtl/sparse_gate/sg_index_core.sv',ROOT/'rtl/sparse_gate/synth/core_dc.tcl']
    locks={}
    for f in files:dest=src/f.name;shutil.copyfile(f,dest);locks[str(f.relative_to(ROOT))]=sha(dest)
    runner=Path(__file__).resolve();shutil.copyfile(runner,src/runner.name)
    assert sha(src/runner.name)==sha(runner),'Launcher changed while being frozen'
    metadata=dict(status='RUNNING',passed=False,source_sha256=locks,library_path=str(a.library),library_sha256=sha(a.library),tool_path=str(a.dc),tool_sha256=sha(a.dc),producer_path=str(Path(__file__).resolve().relative_to(ROOT)),producer_sha256=sha(Path(__file__).resolve()),config=dict(MAX_HEADS=32,TOPK_MAX=512,LANES=16,D=128,G=32),clock_ns=2.0,uncertainty_ns=0.05,input_delay_ns=0.2,output_delay_ns=0.2,output_load_pF=0.02,scope='index arithmetic+heap+register arrays only; no wrapper/DMA/physical SRAM/signoff')
    (a.out/'run.json').write_text(json.dumps(metadata,indent=2)+'\n');env=dict(os.environ,SG_LIBRARY=str(a.library.resolve()))
    start=time.time()
    with (a.out/'dc.log').open('w') as log:
        p=subprocess.Popen([str(a.dc),'-f','source/core_dc.tcl'],cwd=a.out,env=env,stdout=log,stderr=subprocess.STDOUT)
        (a.out/'process.json').write_text(json.dumps(dict(pid=p.pid,runner_pid=os.getpid(),cwd=str(a.out),command=[str(a.dc),'-f','source/core_dc.tcl']),indent=2)+'\n')
        rc=p.wait()
    metadata.update(exit_code=rc,elapsed_seconds=time.time()-start,status='COMPLETED_REPORTS_REQUIRE_REVIEW' if rc==0 and (a.out/'completed.txt').exists() else 'FAILED',passed=False)
    (a.out/'run.json').write_text(json.dumps(metadata,indent=2)+'\n');print(json.dumps(metadata,indent=2));raise SystemExit(rc)
if __name__=='__main__':main()
