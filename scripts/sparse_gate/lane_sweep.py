#!/usr/bin/env python3
"""Matched arithmetic-parallelism sweep, holding fixture, heap, ordering and stalls fixed."""
import argparse,concurrent.futures,hashlib,importlib.util,json,random,shutil,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('sg_oracle',ROOT/'research/csa2_oracle.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--fixture',type=Path,default=ROOT/'results/research/inputs/pretrained-layer20-random-activation-top512.json');ap.add_argument('--out',type=Path,default=ROOT/'results/sparse-gate/lane-sweep');a=ap.parse_args();a.out=a.out.resolve();a.out.mkdir(parents=True,exist_ok=True)
    fixture=json.loads(a.fixture.read_text());q,qs,k,ks,w,candidate=o.fixture_arrays(fixture);assert q.shape==(32,128) and k.shape==(640,128) and fixture['topk']==512 and candidate.all()
    expected=o.scores(q,qs,k,ks,w);selected=o.stable_topk(expected,512);rows=[]
    def emit(op,x=0,y=0,z=0,t=0):rows.append(f'{op} {int(x):08x} {int(y):08x} {int(z):08x} {int(t):08x}\n')
    emit(0);emit(1,32,512,1)
    for h in range(32):
        data=o.pack_e2m1(q[h])+bytes(qs[h])+int(w[h]).to_bytes(2,'little')
        for off,v in enumerate(data):emit(2,h,off,v)
    order=list(range(640));random.Random(1922).shuffle(order)
    for idx in order:
        data=o.pack_e2m1(k[idx])+bytes(ks[idx])
        for off,v in enumerate(data):emit(3,off,v)
        emit(4,idx,expected[idx])
    emit(5,512);stream=a.out/'commands.txt';stream.write_text(''.join(rows))
    sources=[ROOT/'rtl/sparse_gate/sg_fp32_pkg.sv',ROOT/'rtl/sparse_gate/sg_index_core.sv',ROOT/'tests/sparse_gate/tb_lane_sweep.sv']
    source_locks={str(p.relative_to(ROOT)):sha(p) for p in [*sources,ROOT/'research/csa2_oracle.py',Path(__file__).resolve()]};fixture_sha=sha(a.fixture)
    def run(lanes):
        out=a.out/f'lanes{lanes}';out.mkdir(exist_ok=True);obj=out/'obj';binary=obj/'Vtb_lane_sweep';cmd=['verilator','--binary','--timing','-Wno-fatal','--top-module','tb_lane_sweep',f'-GLANES={lanes}','--Mdir',str(obj),'-j','4',*map(str,sources)]
        p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True);(out/'compile.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr
        p=subprocess.run([str(binary),f'+commands={stream}'],cwd=ROOT,capture_output=True,text=True);(out/'simulation.log').write_text(p.stdout+p.stderr);assert p.returncode==0 and 'CORE_STREAM_PASS' in p.stdout,p.stdout[-4000:]
        got={};ph=None;measured=None;score_count=0
        for line in p.stdout.splitlines():
            z=line.split()
            if z and z[0]=='RESULT':assert z[2] not in got;got[z[2]]=z[3]
            elif z and z[0]=='SCORE':score_count+=1;assert int(z[4])==0 and int(z[3],16)==expected[int(z[2])]
            elif z and z[0]=='PHASE':ph=dict(zip(['ready_cycles','arithmetic_cycles','heap_cycles','score_output_cycles','result_output_cycles','q_load_bytes','k_load_bytes'],map(int,z[2:])))
            elif z and z[0]=='MEASURE':measured=dict(zip(['cycles','keys_scored','mac_terms','error'],map(int,z[2:])))
        assert got=={str(i):f'{expected[i]:08x}' for i in selected} and score_count==640
        assert measured['mac_terms']==640*32*128 and measured['keys_scored']==640 and measured['error']==0
        assert sum(ph[z] for z in ['ready_cycles','arithmetic_cycles','heap_cycles','score_output_cycles','result_output_cycles'])==measured['cycles']
        assert ph['q_load_bytes']==32*70 and ph['k_load_bytes']==640*68
        result=dict(passed=True,lanes=lanes,heads=32,dimension=128,topk=512,positions=640,score_checks=score_count,selected_count=len(got),selected_sha256=hashlib.sha256(json.dumps(got,sort_keys=True).encode()).hexdigest(),measured=measured,phases=ph,source_sha256=source_locks,fixture_sha256=fixture_sha,command_sha256=sha(stream),artifacts={str(p.relative_to(out)):sha(p) for p in [binary,out/'compile.log',out/'simulation.log']},compile_command=cmd)
        (out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');return result
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:results=list(pool.map(run,[8,16,32]))
    assert source_locks=={rel:sha(ROOT/rel) for rel in source_locks} and fixture_sha==sha(a.fixture)
    for field in ['ready_cycles','heap_cycles','score_output_cycles','result_output_cycles','q_load_bytes','k_load_bytes']:assert len({r['phases'][field] for r in results})==1,field
    for slow,fast in zip(results,results[1:]):assert slow['measured']['cycles']-fast['measured']['cycles']==640*32*4*(32//slow['lanes']-32//fast['lanes'])
    out=dict(passed=True,schema_version=1,contract=o.CONTRACT,scope='Actual cycle counters, same Q/K/weights, arrival order and output stalls. Byte loading is this core interface, not modeled DMA. No PPA for lanes8/32 claimed.',fixture_path=str(a.fixture.resolve().relative_to(ROOT)),fixture_sha256=fixture_sha,source_sha256=source_locks,tool_sha256={t:sha(shutil.which(t)) for t in ['verilator','g++']},results=results)
    (a.out/'summary.json').write_text(json.dumps(out,indent=2)+'\n')
    compact={k:v for k,v in out.items() if k!='results'};compact['results']=[{k:v for k,v in r.items() if k not in ['artifacts','compile_command','source_sha256']} for r in results];compact['source_summary_path']=str((a.out/'summary.json').relative_to(ROOT));compact['source_summary_sha256']=sha(a.out/'summary.json')
    dest=ROOT/'evidence/core/lane_sweep.json';dest.write_text(json.dumps(compact,indent=2)+'\n');print(json.dumps(compact,indent=2))
if __name__=='__main__':main()
