#!/usr/bin/env python3
"""Verify that Vortex CP DMA, not the host CPU, submitted the gate command."""
import argparse
import csv
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'gem5_new/tools'))
from hettrace.reader import CHAN_AW, CHAN_AR, read_records
from check_gate_wave import audit_gate_wave

PAGE = 0x1900f0000

def load(path): return json.loads(path.read_text())
def need(value, message):
    if not value: raise RuntimeError(message)

PROFILES = {
    'small': {'heads': 4, 'keys': 16, 'topk': 4, 'kv_bytes': 288,
              'workload': 'gem5_axi/workloads/sparse_gate_vortex_cp.cpp',
              'fixture': 'research/fixtures/system_smoke.h'},
    'long': {'heads': 32, 'keys': 640, 'topk': 512, 'kv_bytes': 288,
             'workload': 'gem5_axi/workloads/sparse_gate_vortex_long.cpp',
             'fixture': 'research/fixtures/csa2_top512_fixture.h'},
}

def check(case, binary, manifest, profile='small'):
    spec=PROFILES[profile]
    expected_reads=3*spec['heads']+3*spec['keys']+spec['topk']*(spec['kv_bytes']//32)
    expected_writes=spec['topk']*(1+spec['kv_bytes']//32)
    config=load(case/'config.json')['systemc_kernel']['system']['axi']
    need(config['gate_enable'] and int(config['gate_base'])==PAGE,'wrong gate aperture')
    model=load(manifest)
    need(model['status']=='BUILT_NOT_VALIDATED' and
         model['parameters']=={'mem_base':0x190000000,'mem_bytes':0x100000,'reg_base':PAGE},
         'wrong RTL model parameters')
    for name,record in model['source_files'].items():
        source=ROOT/name
        need(source.stat().st_size==record['bytes'] and source.stat().st_mtime_ns==record['mtime_ns'],
             'RTL model source changed: '+name)
    need(Path(model['library']).stat().st_size==model['library_bytes'],'RTL library size changed')
    gate=load(case/'sparse_gate_summary.json')
    protocol=load(case/'protocol_summary.json')
    bridge=load(case/'memsim_bridge_summary.json')
    core=load(case/'memsim_core.json')
    link=load(case/'link_check_summary.json')
    need(gate['drained'] and gate['build_id']==model['build_id'],'gate not drained or wrong model')
    need(protocol['drained'] and protocol['accepted']==protocol['completed'],'AXI not drained')
    need(link['passed'] and bridge['passed'] and core['passed'],'link or memory check failed')
    need(gate['dma_reads']==gate['dma_read_completed'] and
         gate['dma_writes']==gate['dma_write_completed'],'DMA did not complete')
    need(gate['memory_issued']==gate['memory_completed']==bridge['bursts'],
         'online memory accounting differs')

    vortex=case/'hettrace/vortex.hettrace'
    host=case/'hettrace/host.hettrace'
    need(vortex.is_file() and host.is_file(),'missing source-separated trace')
    vreq=[r for r in read_records(str(vortex)) if r.chan in (CHAN_AW,CHAN_AR) and PAGE<=r.addr<PAGE+4096]
    hreq=[r for r in read_records(str(host)) if r.chan in (CHAN_AW,CHAN_AR) and PAGE<=r.addr<PAGE+4096]
    need(vreq and not hreq,'gate register requests are not exclusively from Vortex')
    need(any(r.chan==CHAN_AW and r.addr==PAGE+8 for r in vreq),'Vortex START write absent')
    need(any(r.chan==CHAN_AR and r.addr==PAGE+4 for r in vreq),'Vortex STATUS poll absent')
    need(all(r.src_id==1 for r in vreq),'Vortex trace source ID changed')
    events=list(csv.DictReader((case/'sparse_gate_events.csv').open()))
    need(any(e['event']=='S_W' and int(e['address'])==PAGE+8 for e in events),
         'START did not reach RTL slave')
    need(any(e['event']=='M_AR' for e in events) and any(e['event']=='M_AW' for e in events),
         'RTL did not issue read and write DMA')
    _,commands=audit_gate_wave(case/'sparse_gate.vcd',events,PAGE,protocol['period_ticks'])
    need(len(commands)==1 and commands[0]['mode']==0 and commands[0]['status']==2 and
         commands[0]['heads']==spec['heads'] and commands[0]['nkeys']==spec['keys'] and
         commands[0]['topk']==spec['topk'],
         'RTL did not finish one successful FULL command')
    log=(case/'run.log').read_text(errors='replace')
    m=re.search(r'VORTEX_GATE_COMMAND mode=0 status=(\d+) count=(\d+) scores=(\d+) read_beats=(\d+) write_beats=(\d+) cycles=(\d+)',log)
    need(m and 'VORTEX SPARSE GATE PASS source=Vortex-CP-DMA' in log,
         'guest did not verify all scores, indices and gathered bytes')
    values=list(map(int,m.groups()))
    need(values==[2,spec['topk'],spec['keys'],expected_reads,expected_writes,commands[0]['cycles']],
         'guest counters differ from expected RTL command')
    need(gate['dma_reads']==expected_reads and gate['dma_writes']==expected_writes,
         'adapter DMA count differs')
    timing=re.search(r'VortexGPGPU timing summary: core_read=(\d+) core_write=(\d+) cp_read=(\d+) cp_write=(\d+) completed=(\d+).*vortex_cycles=(\d+)',log)
    need(timing is not None,'Vortex source timing summary absent')
    core_read,core_write,cp_read,cp_write,completed,core_cycles=map(int,timing.groups())
    need(cp_read>0 and cp_write>0 and completed>=cp_read+cp_write and
         core_read==core_write==core_cycles==0,'source is not isolated Vortex CP DMA')
    result={'schema':'vortex_gate_system_v1','passed':True,'source':'Vortex command-processor DMA',
            'scope':('One synthetic H4/N16/K4 FULL command' if profile=='small' else
                     'One H32/N640/K512 FULL command with trained weights and seeded synthetic activations')+
                    '; guest verifies all result and gather bytes',
            'vortex_mmio_requests':len(vreq),'host_mmio_requests':len(hreq),
            'vortex_timing':{'cp_reads':cp_read,'cp_writes':cp_write,'core_reads':core_read,
                             'core_writes':core_write,'core_cycles':core_cycles},
            'rtl_command':commands[0],'model_build_id':model['build_id'],
            'binary_bytes':binary.stat().st_size,
            'model_library_bytes':model['library_bytes'],
            'source_files':{name:(ROOT/name).stat().st_size for name in
                ('gem5_axi/aou_backend.cc','gem5_axi/configs/run_vortex.py',
                 spec['workload'],spec['fixture'],'env/run_vortex_gate.sh')},
            'simulator_bytes':(ROOT/'gem5/build/AXI/gem5.opt').stat().st_size,
            'vortex_library_bytes':(ROOT/'vortex-gpu/vxbuild/sim/simx/libvortex-gem5.so').stat().st_size,
            'evidence_files':{name:(case/name).stat().st_size for name in
                ('config.json','run.log','protocol_summary.json','aou_summary.json',
                 'link_check_summary.json','sparse_gate_summary.json',
                 'hettrace/vortex.hettrace','hettrace/host.hettrace',
                 'sparse_gate_events.csv','sparse_gate.vcd','axi_wave.vcd',
                 'ucie_flits.csv','memsim_bridge.csv','memsim_commands.csv','memsim_dfi_signals.csv')}}
    (case/'vortex_gate_check.json').write_text(json.dumps(result,indent=2)+'\n')
    return result

if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('case',type=Path)
    p.add_argument('--binary',type=Path,required=True)
    p.add_argument('--model-manifest',type=Path,required=True)
    p.add_argument('--profile',choices=tuple(PROFILES),default='small')
    a=p.parse_args()
    print(json.dumps(check(a.case,a.binary,a.model_manifest,a.profile),indent=2))
