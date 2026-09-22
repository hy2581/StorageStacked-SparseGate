#!/usr/bin/env python3
"""Exercise actual FP4 score/heap RTL with independent numeric reference."""
import argparse, hashlib, importlib.util,json,random,re,shutil,subprocess
from pathlib import Path
import numpy as np
ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('sg_oracle',ROOT/'research/csa2_oracle.py');o=importlib.util.module_from_spec(spec);spec.loader.exec_module(o)
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,default=ROOT/'results/sparse-gate/core');ap.add_argument('--quick',action='store_true');ap.add_argument('--only-fixtures',action='store_true');ap.add_argument('--fixture-manifest',type=Path);ap.add_argument('--fixture',action='append',type=Path,default=[]);ap.add_argument('--simulator',choices=['iverilog','verilator'],default='verilator');a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True)
    manifest_locks={}
    if a.fixture_manifest:
        manifest=json.loads(a.fixture_manifest.read_text());assert manifest['passed']
        manifest_locks={str(a.fixture_manifest):sha(a.fixture_manifest)}
        for rel,digest in manifest['locked_sha256'].items():
            assert sha(ROOT/rel)==digest,(rel,'source hash');manifest_locks[rel]=digest
        for c in manifest['cases']:
            f=ROOT/c['path'];assert sha(f)==c['sha256'];a.fixture.append(f)
    fixture_locks={str(f):sha(f) for f in a.fixture}
    rng=np.random.default_rng(7291);order_rng=random.Random(1922);cmds=[];cases=[];cid=0
    def emit(op,x=0,y=0,z=0,w=0):cmds.append(f'{op} {int(x):08x} {int(y):08x} {int(z):08x} {int(w):08x}\n')
    def arrays(h,n):
        q=rng.integers(0,16,(h,128),dtype=np.uint8);k=rng.integers(0,16,(n,128),dtype=np.uint8)
        qs=rng.integers(119,130,(h,4),dtype=np.uint8);ks=rng.integers(119,130,(n,4),dtype=np.uint8)
        weights=rng.choice([0,0x8000,0x3f80,0xbf80,0x3f00,0xbf00,0x3e80,0xbe80,0x4000,0xc000],h).astype(np.uint16)
        return q,qs,k,ks,weights
    def loadq(q,qs,w,omit=False):
        for h in range(len(q)):
            data=o.pack_e2m1(q[h])+bytes(qs[h])+int(w[h]).to_bytes(2,'little')
            for off,v in enumerate(data):
                if not(omit and h==0 and off==69):emit(2,h,off,v)
    def loadk(k,ks,omit=False):
        data=o.pack_e2m1(k)+bytes(ks)
        for off,v in enumerate(data):
            if not(omit and off==67):emit(3,off,v)
    def success(name,ar,topk,indices=None):
        nonlocal cid
        cid+=1;q,qs,k,ks,w=ar;n=len(k);ids=list(range(n)) if indices is None else list(indices)
        expected=o.scores(q,qs,k,ks,w);ordered=sorted(ids,key=lambda i:(-o.fp32_order_key(expected[i]),i))[:topk]
        emit(1,len(q),topk,cid);loadq(q,qs,w)
        # Address rejects do not mutate valid data.
        emit(2,63,0,0,1);emit(2,0,127,0,1);emit(3,127,0,1)
        order_rng.shuffle(ids)
        for i in ids:loadk(k[i],ks[i]);emit(4,i,expected[i])
        emit(5,len(ordered));cases.append(dict(id=cid,name=name,heads=len(q),positions=n,submitted=len(ids),topk=topk,expected_error=0,selected={str(i):f'{expected[i]:08x}' for i in ordered},mac_terms=len(ids)*len(q)*128))
    emit(0)
    if not a.only_fixtures:
        success('one_head',arrays(1,7),3)
        if not a.quick:
            for h,n,top in [(2,31,1),(4,40,17),(8,33,32),(32,11,8),(1,521,512),(1,533,1),(32,521,512)]:success(f'random_h{h}_n{n}_k{top}',arrays(h,n),top)
            ar=arrays(4,35);ar[0][:]=0;success('all_equal_shuffled_ids',ar,9)
            ar=arrays(2,20);ar[4][:]=0xbf80;success('negative_head_weights',ar,7)
            ar=arrays(3,5);ar[1][:]=0;ar[3][:]=0;success('gradual_underflow_zero',ar,4)
            ar=arrays(1,13);ar[1][:]=53;ar[3][:]=53;ar[4][:]=0x3f80;success('subnormal_scores',ar,8)
            ar=arrays(1,4);ar[0][:]=2;ar[1][:]=127;ar[3][:]=127;ar[4][:]=0xbf80
            for row,groups in enumerate([(2,10,10,2),(10,2,10,2),(10,10,10,2),(2,2,2,10)]):
                for g,code in enumerate(groups):ar[2][row,g*32:(g+1)*32]=code
            success('relu_after_complete_dot_signed_weight',ar,3)
            success('candidate_subset',arrays(4,64),12,indices=range(0,64,3))
            # Empty scan returns no results, not a phantom token.
            cid+=1;emit(1,1,1,cid);emit(5,0);cases.append(dict(id=cid,name='empty_scan',expected_error=0,selected={},mac_terms=0))
            for name,err in [('missing_q',2),('missing_k',3),('bad_q_scale',4),('bad_k_scale',4),('bad_weight',5),('overflow',6)]:
                cid+=1;ar=arrays(1,1);q,qs,k,ks,w=ar;w[:]=0x3f80
                if name=='bad_q_scale':qs[0,0]=255
                if name=='bad_k_scale':ks[0,0]=255
                if name=='bad_weight':w[0]=0x7f80
                if name=='overflow':q[:]=7;k[:]=7;qs[:]=254;ks[:]=254
                emit(1,1,1,cid);loadq(q,qs,w,omit=name=='missing_q');loadk(k[0],ks[0],omit=name=='missing_k');emit(4,0,0,err);emit(6,err)
                cases.append(dict(id=cid,name=name,expected_error=err,selected={}))
            for h,top in [(0,1),(33,1),(1,0),(1,513)]:
                cid+=1;emit(1,h,top,cid);emit(6,1);cases.append(dict(id=cid,name=f'bad_config_{h}_{top}',expected_error=1,selected={}))
            cid+=1;ar=arrays(2,1);emit(1,2,1,cid);loadq(ar[0],ar[1],ar[4]);loadk(ar[2][0],ar[3][0]);emit(7,0,7)
            success('recovery_after_reset',arrays(2,4),3)
    for f in a.fixture:
        case=json.loads(f.read_text());q,qs,k,ks,w,candidates=o.fixture_arrays(case)
        if case['dimension']!=128:raise ValueError('core D=128')
        result=o.evaluate_fixture(case)
        if result['status']=='OK':
            success('external:'+f.name,(q,qs,k,ks,w),case['topk'],np.flatnonzero(candidates))
        else:
            assert len(k)==1,'multi-key error fixture requires precise first error sequencing'
            err=6 if result['status']=='ARITHMETIC_ERROR' else 4 if np.any(qs==255) or np.any(ks==255) else 5
            cid+=1;emit(1,len(q),case['topk'],cid);loadq(q,qs,w);loadk(k[0],ks[0]);emit(4,0,0,err);emit(6,err)
            cases.append(dict(id=cid,name='external:'+f.name,expected_error=err,selected={}))
    stream=a.out/'commands.txt';stream.write_text(''.join(cmds));(a.out/'expected.json').write_text(json.dumps(cases,indent=2)+'\n')
    sources=[ROOT/'rtl/sparse_gate/sg_fp32_pkg.sv',ROOT/'rtl/sparse_gate/sg_index_core.sv',ROOT/'tests/sparse_gate/tb_index_core.sv']
    locked_sources=[*sources,Path(__file__).resolve(),ROOT/'research/csa2_oracle.py']
    before_sha={str(p.relative_to(ROOT)):sha(p) for p in locked_sources}
    if a.simulator=='iverilog':
        binary=a.out/'tb_core.vvp';compile_cmd=['iverilog','-g2012','-s','tb_index_core','-o',str(binary),*map(str,sources)];run_cmd=['vvp',str(binary),f'+commands={stream.resolve()}'];toolnames=['iverilog','vvp']
    else:
        obj=a.out/'obj';binary=obj/'Vtb_index_core';compile_cmd=['verilator','--binary','--timing','-Wno-fatal','--top-module','tb_index_core','--Mdir',str(obj.resolve()),'-j','4',*map(str,sources)];run_cmd=[str(binary.resolve()),f'+commands={stream.resolve()}'];toolnames=['verilator','g++']
    p=subprocess.run(compile_cmd,cwd=ROOT,capture_output=True,text=True);(a.out/'compile.log').write_text(p.stdout+p.stderr);assert p.returncode==0,p.stderr
    p=subprocess.run(run_cmd,cwd=ROOT,capture_output=True,text=True);(a.out/'simulation.log').write_text(p.stdout+p.stderr)
    observed={c['id']:{} for c in cases};measurements={}
    for line in p.stdout.splitlines():
        words=line.split()
        if words and words[0]=='RESULT':
            _,case,idx,score=words;assert idx not in observed[int(case)],'duplicate result';observed[int(case)][idx]=score
        if words and words[0]=='MEASURE':
            _,case,cycles,keys,terms,error=words;measurements[int(case)]=dict(cycles=int(cycles),keys_scored=int(keys),mac_terms=int(terms),error=int(error))
    passed=p.returncode==0 and 'CORE_STREAM_PASS' in p.stdout
    for c in cases:
        got=observed[c['id']];assert got==c['selected'],(c['name'],got,c['selected'])
        m=measurements.get(c['id']);assert m and m['error']==c['expected_error'],(c,m)
        if 'mac_terms' in c:assert m['mac_terms']==c['mac_terms'],(c,m)
        c['measured']=m
    assert before_sha=={str(p.relative_to(ROOT)):sha(p) for p in locked_sources},'source changed during verification'
    assert fixture_locks=={str(f):sha(f) for f in a.fixture},'fixture changed during verification'
    for rel,digest in manifest_locks.items():assert sha(ROOT/rel)==digest,'manifest producer changed'
    result=dict(passed=passed,contract=o.CONTRACT,config=dict(MAX_HEADS=32,TOPK_MAX=512,LANES=16,D=128,G=32),cases=cases,case_count=len(cases),command_count=len(cmds),external_fixtures=fixture_locks,producer_locks=manifest_locks,
        source_sha256=before_sha,artifact_sha256={p.name:sha(p) for p in [stream,a.out/'expected.json',binary,a.out/'compile.log',a.out/'simulation.log']},tool_sha256={t:sha(shutil.which(t)) for t in toolnames},compile_command=compile_cmd)
    (a.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({k:v for k,v in result.items() if k not in ['cases']},indent=2));assert passed,p.stdout[-4000:]
if __name__=='__main__':main()
