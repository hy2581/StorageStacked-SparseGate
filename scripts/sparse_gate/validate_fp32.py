#!/usr/bin/env python3
"""Bit-for-bit finite arithmetic regression against independent integer oracle."""
import argparse, hashlib, importlib.util, json, random, shutil, subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('sg_oracle',ROOT/'research/csa2_oracle.py')
oracle=importlib.util.module_from_spec(spec);spec.loader.exec_module(oracle)

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--out',type=Path,default=ROOT/'results/sparse-gate/fp32');ap.add_argument('--random',type=int,default=40000)
    a=ap.parse_args();a.out.mkdir(parents=True,exist_ok=True);rng=random.Random(9321);rows=[];counts={0:0,1:0,2:0};overflow=0
    def add(op,x,y,z=0):
        nonlocal overflow
        try:
            r=oracle.add_fp32(x,y) if op==0 else oracle.multiply_fp32(x,y) if op==1 else oracle.round_fp32(x,y+z-256)
        except oracle.ArithmeticOverflow:r=1<<32;overflow+=1
        rows.append(f'{op} {x & 0xffffffff:08x} {y:08x} {z:08x} {r:09x}\n');counts[op]+=1
    special=[0,0x80000000,1,2,3,0x007fffff,0x00800000,0x00800001,0x3f800000,0x3f000000,0x7f7fffff,0xff7fffff,0x3f800001,0x33800000,0x33000000,0x00000080,0x80000001,0xbf800000,0x80800000]
    for x in special:
        for y in special:
            for op in (0,1):add(op,x,y)
    for _ in range(a.random):
        x=rng.getrandbits(32);y=rng.getrandbits(32)
        if (x>>23)&255==255:x^=1<<23
        if (y>>23)&255==255:y^=1<<23
        add(0,x,y);add(1,x,y)
        # Cancellation and close exponents exercise jam/subtraction normalization.
        y=((x^0x80000000)+rng.randrange(-8,9))&0xffffffff
        if (y>>23)&255!=255:add(0,x,y)
    for d in range(-4608,4609):
        qs,ks=rng.randrange(255),rng.randrange(255);add(2,d,qs,ks)
    for qs,ks in [(0,0),(0,127),(52,52),(53,53),(63,63),(64,64),(126,127),(127,127),(127,254),(254,254)]:
        for d in [-4608,-1,0,1,2,3,4608]:add(2,d,qs,ks)
    fixture=a.out/'vectors.txt';fixture.write_text(''.join(rows));binary=a.out/'tb_fp32.vvp'
    sources=[ROOT/'rtl/sparse_gate/sg_fp32_pkg.sv',ROOT/'tests/sparse_gate/tb_fp32.sv']
    locked_sources=[*sources,Path(__file__).resolve(),ROOT/'research/csa2_oracle.py']
    before_sha={str(p.relative_to(ROOT)):sha(p) for p in locked_sources}
    cmd=['iverilog','-g2012','-s','tb_fp32','-o',str(binary),*map(str,sources)]
    subprocess.run(cmd,check=True,cwd=ROOT)
    p=subprocess.run(['vvp',str(binary),f'+vectors={fixture.resolve()}'],capture_output=True,text=True,cwd=ROOT)
    (a.out/'simulation.log').write_text(p.stdout+p.stderr)
    passed=p.returncode==0 and f'FP32_CASES {len(rows)} ERRORS 0' in p.stdout
    assert before_sha=={str(p.relative_to(ROOT)):sha(p) for p in locked_sources},'source changed during verification'
    result=dict(passed=passed,total=len(rows),counts=counts,overflow_cases=overflow,random_seed=9321,contract=oracle.CONTRACT,
        source_sha256=before_sha,
        artifact_sha256={q.name:sha(q) for q in [fixture,binary,a.out/'simulation.log']},
        tool_sha256={t:sha(shutil.which(t)) for t in ['iverilog','vvp']},command=cmd)
    (a.out/'summary.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result,indent=2));assert passed,p.stdout[-4000:]
if __name__=='__main__':main()
