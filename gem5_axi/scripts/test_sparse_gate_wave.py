#!/usr/bin/env python3
"""Non-mutating corruption controls for independent RTL command timing checks."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import time
import check_sparse_gate as checker

class Overlay:
    def __init__(self,path,target,replacements):self.path,self.target,self.replacements=path,target,replacements
    @contextmanager
    def open(self):
        def lines():
            tick=None;injected=False
            with self.path.open() as stream:
                for line in stream:
                    if line.startswith('#'):
                        if tick==self.target:
                            yield from self.replacements;injected=True
                        tick=int(line[1:])
                    yield line
            if tick==self.target:yield from self.replacements;injected=True
            if not injected:raise RuntimeError('corruption target missing')
        yield lines()

def main():
    p=argparse.ArgumentParser();p.add_argument('case',type=Path);p.add_argument('out',type=Path);a=p.parse_args()
    a.out.unlink(missing_ok=True);vcd=a.case/'sparse_gate.vcd';events=a.case/'sparse_gate_events.csv'
    sha=lambda f:hashlib.sha256(f.read_bytes()).hexdigest()
    locked={str(f):sha(f) for f in (vcd,events,Path(checker.__file__),Path(__file__))}
    period=json.loads((a.case/'protocol_summary.json').read_text())['period_ticks']
    cfg=json.loads((a.case/'config.json').read_text())['systemc_kernel']['system']['axi'];base=int(cfg['gate_base'])
    start=time.monotonic();ev=checker.rows(events);n,commands=checker.audit_gate_wave(vcd,ev,base,period)
    codes={};depth=0
    with vcd.open() as f:
        for line in f:
            w=line.split()
            if w and w[0]=='$scope':depth+=1
            elif w and w[0]=='$upscope':depth-=1
            elif w and w[0]=='$var' and depth==2:codes[w[4]]=w[3]
            if '$enddefinitions' in line:break
    c=commands[0];changes=[
        ('cycles_plus_one',c['end_tick_fs'],[f"b{c['cycles']+1:b} {codes['cycles']}\n"],'busy interval differs'),
        ('read_count_plus_one',c['end_tick_fs'],[f"b{c['reads']+1:b} {codes['dma_reads']}\n"],'per-command RTL DMA count mismatch'),
        ('done_same_edge_as_final_b',c['last_b_tick_fs'],[f"0{codes['busy']}\n",f"1{codes['done_flag']}\n",f"1{codes['cache_valid']}\n"],'DONE precedes final DMA B response')]
    cases=[]
    for name,tick,replacements,message in changes:
        try:checker.audit_gate_wave(Overlay(vcd,tick,replacements),ev,base,period)
        except RuntimeError as e:
            if message not in str(e):raise RuntimeError(name+' rejected for unexpected reason: '+str(e)) from e
            cases.append({'name':name,'detected':True,'reason':str(e)})
        else:raise RuntimeError('Undetected corruption: '+name)
    if locked!={f:sha(Path(f)) for f in locked}:raise RuntimeError('Audit source/input changed')
    result={'passed':True,'positive_handshakes':n,'positive_commands':len(commands),'negative_controls':cases,
        'scope':'In-memory overlays of actual VCD records; original simulation artifacts unchanged',
        'locked_sha256':locked,'elapsed_seconds':time.monotonic()-start}
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2))
if __name__=='__main__':main()
