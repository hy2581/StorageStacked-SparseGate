#!/usr/bin/env python3
"""Export the already validated H32/N640/K512 fixture for a native-system client."""
import hashlib,json,struct,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
src=ROOT/'results/research/inputs/pretrained-layer20-random-activation-top512.json'
out=ROOT/'research/fixtures/csa2_top512_fixture.h'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
d=json.loads(src.read_text());summary=json.loads((ROOT/'evidence/research/summary.json').read_text())
locked=next(c for c in summary['fixture_cases'] if c['name']==d['name'])
assert sha(src)==locked['fixture_sha256'] and d['expected']['status']=='OK'
assert (d['heads'],d['positions'],d['topk'],d['dimension'])==(32,640,512,128)
q=bytes.fromhex(d['query_codes_hex']);qs=bytes.fromhex(d['query_scales_hex']);w=bytes.fromhex(d['weights_bf16_le_hex'])
k=bytes.fromhex(d['key_codes_hex']);ks=bytes.fromhex(d['key_scales_hex'])
qr=[q[i*64:(i+1)*64]+qs[i*4:(i+1)*4]+w[i*2:(i+1)*2]+bytes(26) for i in range(32)]
kr=[k[i*64:(i+1)*64]+ks[i*4:(i+1)*4]+bytes(28) for i in range(640)]
idx=d['expected']['indices_position_order'];sc=[int(d['expected']['scores_hex'][i],16) for i in idx]
assert len(idx)==512 and idx==sorted(set(idx))
text='''/* Generated from the source-locked CSA2 layer20 H32/N640/K512 fixture.
 * Trained weights with seeded random intermediate activations; not text inference.
 * Only FULL and REUSE expected outputs are included. Payloads are physical AXI96.
 * Regenerate: python3 research/export_top512_header.py */
#ifndef CSA2_TOP512_FIXTURE_H
#define CSA2_TOP512_FIXTURE_H
#include <stdint.h>
#define SG_LARGE_HEADS 32
#define SG_LARGE_KEYS 640
#define SG_LARGE_TOPK 512
'''
for name,rows in [('sg_large_q',qr),('sg_large_k',kr)]:
 text+=f'static const uint8_t {name}[{len(rows)}][96] = {{\n'
 text+='\n'.join(' {'+','.join(f'0x{b:02x}' for b in row)+'},' for row in rows)+'\n};\n'
for name,values in [('sg_large_expected_index',idx),('sg_large_expected_score',sc)]:
 text+=f'static const uint32_t {name}[512] = {{\n'
 text+='\n'.join(' '+','.join(f'0x{v:08x}u' for v in values[i:i+8])+',' for i in range(0,512,8))+'\n};\n'
text+='#endif\n';out.write_text(text)
run=ROOT/'results/research/top512-header';run.mkdir(exist_ok=True)
source=run/'readback.c';source.write_text('#include <stdio.h>\n#include "'+str(out)+'"\nint main(void){fwrite(sg_large_q,1,sizeof(sg_large_q),stdout);fwrite(sg_large_k,1,sizeof(sg_large_k),stdout);fwrite(sg_large_expected_index,1,sizeof(sg_large_expected_index),stdout);fwrite(sg_large_expected_score,1,sizeof(sg_large_expected_score),stdout);return ferror(stdout);}\n')
expected=b''.join(qr+kr)+struct.pack('<512I',*idx)+struct.pack('<512I',*sc)
readback={}
for cc,standard in [('gcc','c99'),('g++','c++17')]:
 exe=run/standard;subprocess.run([cc,'-std='+standard,'-Werror','-Wall',str(source),'-o',str(exe)],check=True)
 got=subprocess.check_output([str(exe)]);assert got==expected
 readback[standard]={'passed':True,'bytes':len(got),'sha256':hashlib.sha256(got).hexdigest()}
e={'schema':'sparse_gate_top512_header_v1','passed':True,'scope':'Input/header readback only; native-system execution recorded separately','input_scope':d['input_scope'],'fixture_path':str(src.relative_to(ROOT)),'fixture_sha256':sha(src),'source_sha256':{str(out.relative_to(ROOT)):sha(out),'research/export_top512_header.py':sha(__file__)},'readback':readback,'heads':32,'positions':640,'topk':512}
(ROOT/'evidence/research/top512_header.json').write_text(json.dumps(e,indent=2)+'\n');print(json.dumps(e,indent=2))
