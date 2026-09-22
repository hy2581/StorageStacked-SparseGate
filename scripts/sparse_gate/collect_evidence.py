#!/usr/bin/env python3
"""Read back core evidence hashes and export small public summaries, never PDK/logs."""
import argparse,hashlib,json,re,shutil
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(path):return json.loads(path.read_text())
def require_digest(path,expected):assert sha(path)==expected,(str(path),'hash mismatch')
def checked_validation(path):
    data=read(path);assert data['passed'] is True,path
    for group in ['source_sha256','external_fixtures','producer_locks']:
        for rel,digest in data.get(group,{}).items():require_digest(ROOT/rel,digest)
    for name,digest in data['artifact_sha256'].items():
        p=path.parent/name
        if not p.exists():p=path.parent/'obj'/name
        require_digest(p,digest)
    for tool,digest in data['tool_sha256'].items():require_digest(shutil.which(tool),digest)
    return data
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--core',type=Path,default=ROOT/'results/sparse-gate/core-accepted/summary.json');ap.add_argument('--float',type=Path,default=ROOT/'results/sparse-gate/fp32-final/summary.json');ap.add_argument('--out',type=Path,default=ROOT/'evidence/core/validation.json');a=ap.parse_args()
    core=checked_validation(a.core);fp=checked_validation(a.float)
    observed={};scores={};metrics={}
    for line in (a.core.parent/'simulation.log').read_text().splitlines():
        w=line.split()
        if w and w[0]=='RESULT':
            _,cid,idx,value=w;bucket=observed.setdefault(int(cid),{});assert idx not in bucket;bucket[idx]=value
        elif w and w[0]=='SCORE':
            _,cid,idx,value,error=w;scores.setdefault(int(cid),[]).append((int(idx),value,int(error)))
        elif w and w[0]=='MEASURE':
            _,cid,cycles,keys,terms,error=w;metrics[int(cid)]=dict(cycles=int(cycles),keys_scored=int(keys),mac_terms=int(terms),error=int(error))
    cases=[]
    for c in core['cases']:
        assert c['selected']==observed.get(c['id'],{})
        assert c['measured']==metrics[c['id']]
        assert c['expected_error']==metrics[c['id']]['error']
        if c['expected_error']==0:
            assert len(scores.get(c['id'],[]))==metrics[c['id']]['keys_scored']
            if 'heads' in c:assert metrics[c['id']]['mac_terms']==metrics[c['id']]['keys_scored']*c['heads']*128
        compact={k:v for k,v in c.items() if k!='selected'};compact['selected_count']=len(c['selected']);compact['selected_sha256']=hashlib.sha256(json.dumps(c['selected'],sort_keys=True).encode()).hexdigest();cases.append(compact)
    out=dict(schema_version=1,passed=True,scope='Actual FP4 score arithmetic and stable Top-K core only; no projection, source block-pool, epoch reuse, DMA, final attention, or physical signoff implied.',contract=core['contract'],config=core['config'],case_count=len(cases),cases=cases,
        score_handshakes=sum(len(v) for v in scores.values()),successful_keys=sum(m['keys_scored'] for m in metrics.values()),mac_terms=sum(m['mac_terms'] for m in metrics.values()),
        float=dict(total=fp['total'],counts=fp['counts'],overflow_cases=fp['overflow_cases'],passed=True),
        source_sha256={**fp['source_sha256'],**core['source_sha256']},
        source_summaries={str(p.resolve().relative_to(ROOT)):sha(p) for p in [a.core,a.float]},
        input_fixture_sha256={str(Path(p).resolve().relative_to(ROOT)):h for p,h in core['external_fixtures'].items()},producer_locks=core.get('producer_locks',{}),
        artifact_sha256=dict(core=core['artifact_sha256'],float=fp['artifact_sha256']),tool_sha256={**core['tool_sha256'],**fp['tool_sha256']},
        collector_path=str(Path(__file__).resolve().relative_to(ROOT)),collector_sha256=sha(Path(__file__).resolve()))
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps(dict(passed=True,cases=len(cases),output=str(a.out),sha256=sha(a.out)),indent=2))
if __name__=='__main__':main()
