#!/usr/bin/env python3
"""Generate all numerical manuscript content from committed evidence.
Default refuses missing integrated-system/synthesis evidence; --preview marks it.
"""
import argparse, hashlib, json
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
OUT=ROOT/'paper/generated';OUT.mkdir(exist_ok=True)
FIG=ROOT/'paper/figures';FIG.mkdir(exist_ok=True)
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p): return json.loads((ROOT/p).read_text())
def check_sources(evidence):
 if isinstance(evidence,dict):
  for fn,digest in evidence.get('source_sha256',{}).items():
   p=ROOT/fn
   assert p.is_file(), 'Evidence source missing: '+fn
   assert sha(p)==digest, 'Evidence source changed: '+fn
  for value in evidence.values(): check_sources(value)
 elif isinstance(evidence,list):
  for value in evidence: check_sources(value)
def tex(s): return str(s).replace('_',r'\_').replace('%',r'\%').replace('&',r'\&')
def table(name,caption,columns,header,rows):
 s='\\begin{table}[t]\n\\centering\\caption{'+caption+'}\n\\label{tab:'+name+'}\n\\small\n\\begin{tabular}{'+columns+'}\\toprule\n'
 s+=' & '.join(header)+r'\\\midrule'+'\n'
 s+='\n'.join(' & '.join(map(str,r))+r'\\' for r in rows)
 return s+'\n\\bottomrule\\end{tabular}\n\\end{table}\n'
def draw_completion(completion,plt,np):
 points=completion['points'];origin=completion['origin_tick_fs'];cmd=completion['command']
 t=np.array([(p['tick_fs']-origin)/1e6 for p in points])
 signals=[('clk','AXI clock'),('m_axi_bvalid','DMA BVALID'),('m_axi_bready','DMA BREADY'),('busy','BUSY'),('done_flag','DONE'),('s_axi_arvalid','MMIO ARVALID'),('s_axi_rvalid','MMIO RVALID')]
 fig,ax=plt.subplots(figsize=(7.0,3.1),layout='constrained')
 for i,(name,label) in enumerate(signals):
  level=(len(signals)-1-i)*1.4;vals=[p['values'][name]*.78+level for p in points]
  ax.step(t,vals,where='post',linewidth=1.1,color='#294f70')
 for tick,label,color in [(origin,'Final DMA B handshake','#294f70'),(cmd['end_tick_fs'],'DONE / cache committed','#dc9955'),(cmd['first_terminal_status_r_tick_fs'],'RTL STATUS R = 0x2','#489393')]:
  ax.axvline((tick-origin)/1e6,color=color,linestyle='--',linewidth=.9,label=label)
 ax.set_yticks([(len(signals)-1-i)*1.4+.39 for i in range(len(signals))],[x[1] for x in signals]);ax.tick_params(axis='y',length=0,labelsize=7)
 ax.set_xlabel('Time relative to final DMA B handshake (ns)');ax.set_xticks(np.arange(t[0],t[-1]+.1,2));ax.set_xlim(t[0],t[-1]);ax.grid(axis='x',alpha=.12);ax.set_ylim(-.25,len(signals)*1.4+.15);ax.legend(loc='upper center',bbox_to_anchor=(.5,1.13),ncol=3,frameon=False,fontsize=6.5)
 ax.spines['left'].set_visible(False);fig.savefig(FIG/'completion_wave.pdf');fig.savefig(FIG/'completion_wave.png',dpi=220);plt.close(fig)

def draw_native_modes(case,slow_case,plt,np):
 cmds=case['commands'][:3];slow_cmds=slow_case['commands'][:3]
 assert case['passed'] and slow_case['passed'] and case['axi_period_fs']==slow_case['axi_period_fs']
 assert slow_case['memsim_period_fs']==4*case['memsim_period_fs']
 assert [c['mode'] for c in cmds]==[c['mode'] for c in slow_cmds]==['FULL','REUSE','REINDEX']
 assert [(c['dma_read_bytes'],c['dma_write_bytes']) for c in cmds]==[(c['dma_read_bytes'],c['dma_write_bytes']) for c in slow_cmds]
 fig,axes=plt.subplots(1,2,figsize=(6.6,2.5),layout='constrained');names=[c['mode'] for c in cmds];colors=['#294f70','#489393','#dc9955'];x=np.arange(3)
 max_time=max(c['cycles'] for c in slow_cmds)*case['axi_period_fs']/1e9
 for offset,commands,label,color in [(-.18,cmds,'Memory period 1x','#294f70'),(.18,slow_cmds,'Memory period 4x','#489393')]:
  vals=[c['cycles']*case['axi_period_fs']/1e9 for c in commands];axes[0].bar(x+offset,vals,width=.34,label=label,color=color)
  for i,value in enumerate(vals):axes[0].text(i+offset,value+max_time*.018,f'{value:.1f}',ha='center',fontsize=6.5)
 axes[0].set_xticks(x,names);axes[0].set_ylabel(r'RTL busy time ($\mu$s)');axes[0].set_ylim(0,max_time*1.25);axes[0].legend(fontsize=6.5,frameon=False)
 vals=[(c['dma_read_bytes']+c['dma_write_bytes'])/1024 for c in cmds]
 axes[1].bar(names,vals,color=colors,width=.6);axes[1].set_ylabel('DMA payload (KiB)');axes[1].set_ylim(0,max(vals)*1.2)
 for i,value in enumerate(vals):axes[1].text(i,value+max(vals)*.02,f'{value:.2f}',ha='center',fontsize=7)
 for ax in axes:ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True);ax.tick_params(axis='x',labelsize=7)
 fig.savefig(FIG/'native_modes.pdf');fig.savefig(FIG/'native_modes.png',dpi=220);plt.close(fig)

def main():
 ap=argparse.ArgumentParser();ap.add_argument('--preview',action='store_true');args=ap.parse_args()
 inputs=['evidence/core/validation.json','evidence/core/lane_sweep.json','evidence/sparse_gate/wrapper.json','evidence/research/summary.json','evidence/review/wrapper.json','evidence/review/dma.json','evidence/research/top512_header.json','evidence/system/completion_window.json']
 core,lane,wrap,research,review,dma,large_input,completion=map(read,inputs)
 assert core['passed'] and lane['passed'] and wrap['status']=='PASS' and research['passed'] and review['passed'] and dma['passed']
 assert large_input['passed'] and completion['passed']
 for evidence in (core,lane,wrap,research,review,dma,large_input,completion): check_sources(evidence)
 counts={'CoreCaseCount':core['case_count'],'CoreKeyCount':core['successful_keys'],'CoreMacCount':core['mac_terms'],'FpCaseCount':core['float']['total']}
 counts.update(TensorBytes=research['tensor_payload_bytes'],OraclePairCount=research['arithmetic_audit']['add_checked'],RationalCaseCount=research['arithmetic_audit']['rational_round_checked'])
 learned=next(c for c in research['fixture_cases'] if c['name']=='pretrained-layer20-random-activation-top512')['torch_comparison']
 tied=next(c for c in research['fixture_cases'] if c['name']=='zero-ties-top512')['torch_comparison']
 counts['TieDifference']=tied['fp32']['topk_symmetric_difference']
 values={k:format(v,',') for k,v in counts.items()}
 values.update(BfRelative=format(learned['bf16_demo']['relative_l2_error'],'.6g'),BfAbsolute=format(learned['bf16_demo']['max_abs_error'],'.6g'))
 assert learned['fp32']['max_abs_error']==0 and learned['bf16_demo']['topk_symmetric_difference']==0
 (OUT/'results.tex').write_text('\n'.join('\\newcommand{\\'+k+'}{'+v+'}' for k,v in values.items())+'\n')
 wanted={'random_h32_n521_k512':'Random full shape','all_equal_shuffled_ids':'Shuffled tied IDs','negative_head_weights':'Signed head weights','subnormal_scores':'Subnormal scores','candidate_subset':'Subset'}
 rows=[]
 for c in core['cases']:
  if c['name'] in wanted:
   label=wanted[c['name']]+(f" (C={c['submitted']})" if c['submitted']<c['positions'] else '')
   rows.append([label,c['heads'],c['positions'],c['topk'],format(c['measured']['cycles'],','),'PASS'])
  elif 'pretrained-layer20' in c['name']:
   label='Weights: '+(f"C={c['submitted']}" if 'reindex' in c['name'] else 'small full' if 'small' in c['name'] else 'Top-512')
   rows.append([label,c['heads'],c['positions'],c['topk'],format(c['measured']['cycles'],','),'PASS'])
 (OUT/'core_table.tex').write_text(table('core','Selected core cases. C denotes the submitted candidate count when only a subset of N positions is scanned. Cycles include the documented byte-load interface and test backpressure; these are not system latency measurements.','lrrrrl',['Case','H','N','K','Cycles','Check'],rows))
 import matplotlib
 matplotlib.use('Agg')
 import matplotlib.pyplot as plt
 import numpy as np
 plt.rcParams.update({'font.family':'DejaVu Sans','font.size':8,'axes.spines.top':False,'axes.spines.right':False,'pdf.fonttype':42,'ps.fonttype':42})
 fig,ax=plt.subplots(figsize=(5.6,2.65),layout='constrained');x=np.arange(3);bottom=np.zeros(3)
 phases=[('arithmetic_cycles','Arithmetic + Q checks','#294f70'),('ready_cycles','Load / wait','#489393'),('heap_cycles','Heap','#dc9955'),('score_output_cycles','Score handoff','#869baa'),('result_output_cycles','Result drain','#c3cbd1')]
 for key,label,color in phases:
  y=np.array([v['phases'][key] for v in lane['results']])/1000;ax.bar(x,y,bottom=bottom,label=label,color=color,width=.54);bottom+=y
 for i,v in enumerate(lane['results']):ax.text(i,bottom[i]+7,format(v['measured']['cycles'],','),ha='center',va='bottom',fontsize=8)
 ax.set_xticks(x,[str(r['lanes'])+' lanes' for r in lane['results']]);ax.set_ylabel('Measured core cycles (thousands)');ax.set_ylim(0,max(bottom)*1.18);ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True);ax.legend(loc='upper right',fontsize=7,frameon=False)
 fig.savefig(FIG/'lane_sweep.pdf');fig.savefig(FIG/'lane_sweep.png',dpi=220);plt.close(fig)
 impl=r'''\begin{figure}[t]
\centering\includegraphics[width=\columnwidth]{lane_sweep.pdf}
\caption{Measured lane-count sensitivity for the same H32/N640/K512 learned-weight-derived input. All scores and selections match. This core-only test excludes wrapper positional sorting and native DMA/RAM waits; result-drain cycles reflect its testbench ready sequence. No clock or PPA equivalence across builds is assumed.}
\label{fig:lanes}
\end{figure}
'''
 rs=lane['results'];a,b,c=[v['measured']['cycles'] for v in rs]
 impl+=f'The 8/16/32-lane implementations require {a:,}, {b:,}, and {c:,} cycles for the same input and identical handshake schedule. Each computes 2,621,440 product terms and selects the same 512 indices. Relative cycle improvements are {a/b:.3f}$\\times$ from 8 to 16 lanes and {b/c:.3f}$\\times$ from 16 to 32 lanes. More lanes shorten integer-product batches, while scale conversion and FP32 reduction remain serialized. Loading, selection and output costs remain visible; the result does not imply linear scaling or equal attainable frequency.\n\n'
 full_core=next(v for v in core['cases'] if v['name']=='external:pretrained-layer20-random-activation-top512.json')
 impl+=f"The {full_core['measured']['cycles']:,}-cycle Top-512 case in Table~\\ref{{tab:core}} uses a different randomized backpressure sequence from this controlled lane sweep; the {b:,}-cycle 16-lane result is therefore not an identical timing experiment.\n\n"
 synth=ROOT/'evidence/core/synthesis.json';system=ROOT/'evidence/system/summary.json'
 missing=[];abstract_results=[]
 if synth.exists():
  inputs.append('evidence/core/synthesis.json');d=read(inputs[-1]);check_sources(d)
  assert d['completed'] and d['mapping_passed'] and d['mapped'] and d['unmapped_leaf_references']==0, 'Incomplete synthesis mapping'
  coverage=d['timing_coverage'];assert coverage['status'] in ['PASS','FAIL','NOT_CHECKED']
  assert bool(coverage['passed'])==(coverage['status']=='PASS')
  inputs.append('evidence/core/area_units.json');area=read(inputs[-1]);check_sources(area)
  assert area['passed'] and area['liberty_area_unit_verified'] and area['area_unit']=='um2'
  assert area['dc_database_sha256']==d['library']['sha256']
  assert area['inputs']['dc_cell_areas']['sha256']==d['library_cell_areas']['sha256']
  assert area['dc_cell_area_match']['passed'] and area['dc_cell_area_match']['compared']==d['library_cell_areas']['rows']
  impl+=table('synthesis','Native Design Compiler mapping of the 16-lane score/heap core in a TSMC 28-nm HPC+ standard-cell library. Arrays are flop-mapped. No layout, extracted interconnect, gate-level equivalence or physical signoff is claimed.','lr',['Metric','Measured / configured'],[
   ['Library corner',tex(d['library_corner'])],['Target period (ns)',f"{d['target_period_ns']:.3f}"],[r'Mapped cell area ($\mu$m$^2$)',f"{d['cell_area_library_units']:,.2f}"],['Leaf cells',f"{d['leaf_cells']:,}"],['Sequential cells',f"{d['registers']:,}"],['Setup slack (ns)',f"{d['setup_slack_ns']:+.6f}"],['Hold slack (ns)',f"{d['hold_slack_ns']:+.6f}"],['Design-rule violation entries',f"{d['design_rule_violation_count']:,}"],['Constraint coverage',tex(coverage['status'])]])
  closed=d['setup_slack_ns']>=0 and d['hold_slack_ns']>=0
  assert bool(d['timing_passed'])==closed
  impl+=('The reported setup and hold checks meet the stated constraints in this mapped-core model. ' if closed else 'The mapped core does not close all stated timing constraints; negative slack is retained in the table. ')
  if 0<=d['setup_slack_ns']<.001:impl+=f"The reported setup margin is only {d['setup_slack_ns']*1e6:g} fs; this near-zero nominal margin is not evidence of a robust physical frequency. "
  assert d['design_rule_violation_count']==sum(d['design_rule_violation_counts'].values())
  assert bool(d['design_rules_passed'])==(d['design_rule_violation_count']==0)
  assert bool(d['passed'])==(closed and d['design_rules_passed'] and coverage['passed'])
  impl+='Design-rule entries count reported transition, capacitance, fanout, or other electrical-limit violations; an object appearing in multiple categories is counted in each. These checks are distinct from setup/hold and from layout DRC. '
  if not d['design_rules_passed']:impl+='Electrical design-rule limits remain violated in this mapped result. '
  if coverage['passed']:
   assert coverage['io_delay_check']['passed'] and coverage['reset_false_path_verified'] and coverage['unwaived_warning_count']==0
   impl+='The independent clock and I/O coverage checks pass, with the documented reset false-path exception. '
  else:impl+='Constraint coverage is '+tex(coverage['status'])+'; timing extrema alone do not establish complete timing coverage. '
  if 'noncombinational_cell_area_library_units' in d and 'combinational_cell_area_library_units' in d:
   noncomb=d['noncombinational_cell_area_library_units'];comb=d['combinational_cell_area_library_units'];total=d['cell_area_library_units']
   assert total>0 and 0<=noncomb<=total and 0<=comb<=total
   impl+=f"The report attributes {comb:,.2f} $\\mu$m$^2$ to combinational cells and {noncomb:,.2f} $\\mu$m$^2$ ({100*noncomb/total:.1f}\\%) to noncombinational cells. The latter includes control state as well as flop-mapped storage; it is not a measurement of Q/heap storage alone. "
  dc_area_relation=('match exactly' if area['dc_cell_area_match']['exact_matches']==area['dc_cell_area_match']['compared'] else 'agree within the recorded readback tolerance')
  impl+=f"For all {area['liberty_lef_match']['compared']:,} Liberty cells, the area exactly matches the same-name LEF width times height. The kit release compatibility is checked, and actual DC database areas {dc_area_relation}. "
  impl+='LEF SIZE dimensions use micrometers~\\cite{lefdef}; this establishes cell-footprint area, not placed core or die area. The synthesis target excludes the AXI wrapper, DMA, processor models, and UCIe system. '
  clock=d['clock_model'];assert clock['ideal_clock'] and clock['cts_status']=='NOT_RUN'
  impl+='The clock is ideal; CTS and physical clock-network loading are not modeled. '
  clock_nets=[n for n in clock['high_fanout_nets'] if n['name']==clock['source']]
  if clock_nets:impl+=f"The tool uses a fanout estimate of {clock['assumed_fanout_for_delay']:,} for the clock net reported with {clock_nets[0]['loads']:,} loads. "
  impl+='An independent saved-design readback checks mapping and timing reports; it is not an equivalence proof. The simulation clock is a test setting, not an established chip frequency.\n'
  abstract_results.append(f"The mapped core has {d['cell_area_library_units']/1e6:.3f} mm$^2$ of cell area in a 28-nm HPC+ library at {tex(d['library_corner'])}. ")
  if d['passed']:
   abstract_results[-1]+=f"It meets the nominal {d['target_period_ns']:g}-ns timing target with ideal clocking"
   abstract_results[-1]+=(f" and only {d['setup_slack_ns']*1e6:g} fs reported setup slack. " if 0<=d['setup_slack_ns']<.001 else '. ')
 else:
  missing.append('native synthesis result')
  impl+='\\textbf{Preview: synthesis is still running. No area, frequency or timing-closure result is asserted.}\n'
 (OUT/'implementation_results.tex').write_text(impl)
 sys_text=''
 if system.exists() and read('evidence/system/summary.json').get('passed'):
  inputs.append('evidence/system/summary.json');d=read(inputs[-1]);check_sources(d)
  assert d['status']=='PASS' and not d['failures']
  assert sha(ROOT/d['source_lock']['path'])==d['source_lock']['sha256']
  assert sha(ROOT/'env/collect_sparse_gate_system.py')==d['collector_sha256']
  cases=d['cases'];cpu=cases['baseline_cpu'];xpu=cases['baseline_xpu']
  assert all(cases[n]['passed'] for n in ['baseline_cpu','baseline_xpu','cpu_synthetic','cpu_real_weights','three_source_coexistence','cpu_top512'])
  feedback=d['gate_memory_feedback'];assert feedback['passed'] and d['adapter_contract']['passed']
  assert completion['command']==cases['cpu_synthetic']['commands'][0]['rtl_interval']
  sys_text+=f"The original path passes {cpu['native_tests_passed']} native tests, {len(cpu['cases'])} CPU/tester cases, and {len(xpu['cases'])} XPU cases. SparseGate then passes separate synthetic-input CPU, learned-weight-derived CPU, and three-source coexistence programs. The latter executes the original GPU/NPU work before gate commands; it demonstrates coexistence on the retained path, not concurrent gate contention.\n\n"
  sys_text+='Every gate run checks all returned score/index records and every gathered byte against the independent fixture. The small-case sequence exercises FULL, valid REUSE, REINDEX, stale-epoch rejection, and FULL recovery. The stale command has no accepted DMA traffic. Native AXI waves, UCIe Flits, backend events, and memory commands are cross-checked, with binary and source digests retained. Each command counter is independently checked against its RTL busy interval, and successful DONE is checked against the final DMA write response. A separate adapter/RTL test rejects unsupported exclusive accesses and verifies ordinary-access recovery.\n\n'
  assert d['wave_controls']['passed'] and len(d['wave_controls']['negative_controls'])==3
  sys_text+='The waveform checker also rejects three controlled corruptions of a recorded trace: an incremented cycle count, an incremented DMA-read count, and premature DONE at the final B handshake. These overlays leave the original simulation files unchanged.\n\n'
  draw_completion(completion,plt,np)
  sys_text+=r'''\begin{figure*}[t]
\centering\includegraphics[width=.94\textwidth]{completion_wave.pdf}
\caption{Actual native RTL VCD samples around the first successful FULL completion in the H4/N16/K4 CPU program. Levels are recorded after model evaluation; handshakes sample values stable before the rising edge. DONE commits three AXI cycles after the final B handshake. The RTL STATUS response is independently correlated with its later delivery through the return protocol path. This is a simulator waveform, not a silicon capture.}
\label{fig:completion}
\end{figure*}
'''
  v=cases['cpu_real_weights'];cmds=v['commands'][:3];slow_cmds=feedback['slow_case']['commands'][:3]
  assert [c['mode'] for c in cmds]==['FULL','REUSE','REINDEX']
  rows=[[c['mode'],c['score_count'],c['dma_read_beats'],c['dma_write_beats'],format(c['cycles'],','),format(slow['cycles'],',')] for c,slow in zip(cmds,slow_cmds)]
  sys_text+=table('modes','Measured RTL command counters in the learned-weight-derived H32/N64/K8 program; REINDEX has 16 candidates. R/W are DMA beat counts, unchanged across the two memory periods. Each result gathers 288 B.','lrrrrr',['Mode','Scores','R','W',r'$1\times$ cyc.',r'$4\times$ cyc.'],rows)
  sys_text+=f"The AXI simulation period is {v['axi_period_fs']/1e6:g} ns. Command cycles count the RTL busy interval through the final write response; host-run time also includes the protocol and software interactions. All three successful commands return eight records on this input.\n\n"
  sys_text+=f"Increasing the online memory period from {v['memsim_period_fs']/1e6:g} to {feedback['slow_case']['memsim_period_fs']/1e6:g} ns preserves the guest binary, RTL, scores, and DMA counts. All successful command counters increase; complete host finish time increases by {feedback['host_finish_delta_fs']/1e9:.3f} $\\mu$s. Polling traffic can change, so this is a memory-feedback experiment rather than a fixed-instruction speedup comparison.\n\n"
  full=cases['cpu_top512'];fc,rc=full['commands'];assert [fc['mode'],rc['mode']]==['FULL','REUSE'] and fc['result_count']==rc['result_count']==512
  abstract_results.insert(0,f"Native H32/N640/K512 FULL and REUSE require {fc['cycles']:,} and {rc['cycles']:,} busy cycles, respectively; every selected record and 147,456 gathered bytes are verified per command. ")
  sys_text+=f"A separate full-shape H32/N640/K512 guest executes FULL and then REUSE to distinct destinations. It verifies all 512 score/index records, their padding, and 147,456 gathered bytes per command. FULL takes {fc['cycles']:,} busy cycles with {fc['dma_read_beats']:,} read beats and {fc['dma_write_beats']:,} write beats; REUSE takes {rc['cycles']:,} cycles with {rc['dma_read_beats']:,}/{rc['dma_write_beats']:,} read/write beats. This extends full-shape selection evidence through the actual online path; the small-case REINDEX/error sequence is a separate test.\n\n"
  draw_native_modes(v,feedback['slow_case'],plt,np)
  sys_text+=r'''\begin{figure*}[t]
\centering\includegraphics[width=.86\textwidth]{native_modes.pdf}
\caption{Measured H32/N64/K8 command latency with two online memory periods, and DMA payload (identical across periods). REUSE preserves an earlier selection; REINDEX evaluates a supplied subset. These different workloads are not interchangeable accuracy baselines. Payload includes result and gathered-KV writes, excluding host uploads, MMIO, readback, and link framing.}
\label{fig:native}
\end{figure*}
'''
 else:
  missing.append('passing integrated-system result')
  sys_text='\\textbf{Preview: the native online system is still being built and validated. No integrated PASS or system performance result is asserted in this preview.}\n'
 (OUT/'system_results.tex').write_text(sys_text)
 (OUT/'abstract_results.tex').write_text(''.join(abstract_results).rstrip()+'\n')
 if missing and not args.preview:raise RuntimeError('Cannot publish paper: missing '+', '.join(missing))
 hashes={fn:sha(ROOT/fn) for fn in inputs}
 record={'schema':'paper_generation_v1','preview':args.preview,'missing_evidence':missing,'input_sha256':hashes,'generator_sha256':sha(__file__),'outputs':{str(p.relative_to(ROOT)):sha(p) for p in OUT.glob('*.tex')}}
 (OUT/'manifest.json').write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record,indent=2))
if __name__=='__main__':main()
