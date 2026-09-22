#!/usr/bin/env python3
"""Export actual native RTL waveform samples around a verified completion."""
import argparse,hashlib,json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 ap=argparse.ArgumentParser();ap.add_argument('--case',type=Path,default=ROOT/'results/sparse-gate-system-final-cpu/cpu_smoke');args=ap.parse_args()
 case=args.case.resolve();check=case/'sparse_gate_check.json';vcd=case/'sparse_gate.vcd'
 accepted=json.loads(check.read_text());assert accepted['passed'] and accepted['fixture']=='smoke'
 assert sha(vcd)==accepted['artifacts_sha256']['sparse_gate.vcd']
 command=accepted['rtl_command_intervals'][0];assert command['status']==2 and (command['mode'],command['heads'],command['nkeys'],command['topk'])==(0,4,16,4)
 period=json.loads((case/'protocol_summary.json').read_text())['period_ticks'];origin=command['last_b_tick_fs'];begin=origin-3*period;end=origin+8*period
 wanted={'clk','m_axi_bvalid','m_axi_bready','s_axi_arvalid','s_axi_arready','s_axi_rvalid','s_axi_rready','s_axi_rdata'}
 internal={'busy','done_flag','cache_valid'};names={};state={};points=[];tick=0;changes={};depth=0;last=None
 def consume(t,delta):
  nonlocal last
  state.update(delta)
  if begin<=t<=end:
   if not points:
    assert set(wanted)|internal<=state.keys()
    if t>begin:points.append({'tick_fs':begin,'values':last.copy()})
   points.append({'tick_fs':t,'values':state.copy()})
  if t<begin:last=state.copy()
 with vcd.open() as f:
  for line in f:
   w=line.split()
   if w and w[0]=='$scope':depth+=1
   elif w and w[0]=='$upscope':depth-=1
   elif w and w[0]=='$var' and ((depth==1 and w[4] in wanted) or (depth==2 and w[4] in internal)):names[w[3]]=w[4]
   if '$enddefinitions' in line:break
  assert set(names.values())==wanted|internal
  for line in f:
   w=line.split()
   if not w:continue
   if line.startswith('#'):
    consume(tick,changes);tick=int(line[1:]);changes={}
    if tick>end:break
   elif w[0][0] in 'bB' and len(w)==2 and w[1] in names:
    assert set(w[0][1:])<={'0','1'};changes[names[w[1]]]=int(w[0][1:],2)
   elif w[0][0] in '01' and w[0][1:] in names:changes[names[w[0][1:]]]=int(w[0][0])
  if tick<=end:consume(tick,changes)
 assert points and points[0]['tick_fs']==begin
 if points[-1]['tick_fs']<end:points.append({'tick_fs':end,'values':points[-1]['values'].copy()})
 assert sha(vcd)==accepted['artifacts_sha256']['sparse_gate.vcd']
 e={'schema':'native_completion_wave_window_v1','passed':True,'scope':'Actual post-evaluation VCD levels; channel handshakes use stable values before rising edges','axi_period_fs':period,'origin_tick_fs':origin,'command':command,'source_sha256':{'paper/export_completion.py':sha(Path(__file__))},'native_check':{'path':str(check.relative_to(ROOT)),'sha256':sha(check)},'vcd':{'path':str(vcd.relative_to(ROOT)),'sha256':sha(vcd)},'points':points}
 target=ROOT/'evidence/system/completion_window.json';target.write_text(json.dumps(e,indent=2)+'\n');print(f'{target.relative_to(ROOT)}: {len(points)} actual samples; {begin}..{end} fs')
if __name__=='__main__':main()
