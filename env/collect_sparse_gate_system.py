#!/usr/bin/env python3
"""Publish compact system evidence only from complete locally verified runs."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):h.update(block)
    return h.hexdigest()
def read(path):return json.loads(path.read_text())
def need(ok,why):
    if not ok:raise RuntimeError(why)
def relative(path):
    try:return str(path.resolve().relative_to(ROOT))
    except ValueError:return str(path.resolve())
def ref(path):return {'path':relative(path),'sha256':sha(path)}
def finish(path):
    matches=re.findall(r'EXIT: .* code 0 tick (\d+)',path.read_text())
    need(len(matches)==1,'missing clean simulated exit: '+str(path));return int(matches[0])

def baseline(directory,kind):
    summary=read(directory/'summary.json');need(summary['passed'],'baseline failed')
    seal=read(directory/'closure.json');need(seal['passed'] and seal['summary_sha256']==sha(directory/'summary.json'),'baseline closure missing/mismatched')
    need(seal['sealer_sha256']==sha(ROOT/'env/seal_system_run.py'),'baseline sealer source changed')
    for name,value in seal['artifacts_sha256'].items():need(sha(directory/name)==value,'baseline artifact changed: '+name)
    names=['directed','replay','shallow','held','period_3ns','cpu','cpu_slow'] if kind=='cpu' else ['npu','gpu','three','three_slow']
    need(set(summary['cases'])==set(names),'wrong baseline case set')
    need(summary['native_tests_passed']==19,'native test count differs from locked 19-case plan')
    manifest=read(directory/'environment/manifest.json')
    result={'status':'PASS','passed':True,'summary':ref(directory/'summary.json'),
        'closure':ref(directory/'closure.json'),
        'environment_manifest':ref(directory/'environment/manifest.json'),
        'environment':{'compiler':manifest['compiler'].splitlines()[0],'python':manifest['python'].splitlines()[0],
            'systemc':manifest['systemc'],'ticks_per_second':manifest['ticks_per_second'],
            'gem5_binary_sha256':manifest['binary_sha256'],'memsim_library_sha256':manifest['memsim_library_sha256']},
        'native_tests_passed':19,'native_plan':ref(directory/'native-test-plan.json'),'native_test_log':ref(directory/'native-tests.log'),'cases':{}}
    for name in names:
        d=directory/name;c=summary['cases'][name];cfg=read(d/'config.json')['systemc_kernel']['system']['axi']
        need(not cfg.get('gate_enable',False),'baseline accidentally enables gate')
        need(all(c[k]['passed'] for k in ('check_summary','aou_check_summary','memsim_check','memsim_core')),'baseline subcheck failed')
        for k in ('check_summary','aou_check_summary','memsim_check','memsim_core'):
            need(c[k]==read(d/(k+'.json')),'baseline summary does not match case receipt: '+name+'/'+k)
        paths=['run.log','config.json','stats.txt','axi_events.csv','axi_wave.vcd','aou_events.csv','ucie_flits.csv',
            'memsim_bridge.csv','memsim_commands.csv','memsim_dfi_signals.csv','memsim_image.csv','check_summary.json',
            'aou_check_summary.json','memsim_check.json','memsim_core.json','link_check_summary.json']
        result['cases'][name]={'status':'PASS','gate_enable':False,'host_finish_tick_fs':finish(d/'run.log'),
            'host_transactions':c.get('transactions',c['check_summary'].get('transactions')),
            'memsim_scale':cfg['memsim_scale'],'memsim_period_fs':read(d/'memsim_config.json')['period_fs'],
            'axi_period_fs':read(d/'protocol_summary.json')['period_ticks'],'artifacts':{p:ref(d/p) for p in paths}}
        if 'sources' in c:result['cases'][name].update(sources=c['sources'],devices=c['devices'])
    result['memory_feedback']=summary['cpu_feedback' if kind=='cpu' else 'memory_feedback']
    if kind=='xpu':result['xpu_environment_manifest']=ref(directory/'environment/xpu_manifest.json')
    return result

def gate_case(directory,fixture):
    suite_path=directory.parent/'summary.json';suite=read(suite_path)
    need(suite['passed'],'gate suite has not completed acceptance')
    entry=suite['cases'][directory.name]
    need(entry['passed'] and entry['summary_sha256']==sha(directory/'sparse_gate_check.json'),'gate case receipt differs from completed suite')
    need(Path(entry['summary']).resolve()==(directory/'sparse_gate_check.json').resolve(),'gate suite receipt path differs')
    c=read(directory/'sparse_gate_check.json');need(c['passed'] and c['fixture']==fixture,'gate case not verified')
    need(c['checker_sha256']==sha(ROOT/'gem5_axi/scripts/check_sparse_gate.py'),'gate checker changed since validation')
    for name,value in c['artifacts_sha256'].items():need(sha(directory/name)==value,'gate artifact changed: '+name)
    sources=read(directory/'integration_sources.json');need(sources['verified_after_run'],'source lock not verified after case')
    for name,value in sources['source_sha256'].items():need(sha(ROOT/name)==value,'integration source changed: '+name)
    need(sha(Path(sources['workload_path']))==sources['workload_sha256'],'guest executable changed')
    cfg=read(directory/'config.json')['systemc_kernel']['system']['axi'];need(cfg['gate_enable'],'gate disabled')
    model_path=directory.parent/'environment/gate_model_build.json';model=read(model_path)
    need(sha(model_path)==c['model_manifest_sha256'] and model['build_id']==c['model_build_id'],'gate model manifest/build ID changed')
    need(model['status']=='BUILT_NOT_VALIDATED' and model['source_sha256']==model['source_sha256_after'],'gate model build was not source locked')
    need(sha(Path(cfg['gate_library']))==model['library_sha256'],'executed gate library changed')
    for name,value in model['source_sha256'].items():need(sha(ROOT/name)==value,'executed RTL/model source changed: '+name)
    envpath=directory.parent/'environment/manifest.json';environment=read(envpath)
    need(sha(Path(environment['binary']))==environment['binary_sha256'],'gate gem5 executable changed')
    need(sha(ROOT/'mem_sim/build-unified/libstoragestacked_memsim.so')==environment['memsim_library_sha256'],'gate online mem_sim library changed')
    commands=[]
    for mode,status,count,scores,reads,writes,cycles in c['guest_commands']:
        commands.append({'mode':['FULL','REINDEX','REUSE'][mode],'status':status,'expected_error':status==516,
            'result_count':count,'score_count':scores,'cycles':cycles,'dma_read_beats':reads,'dma_write_beats':writes,
            'dma_read_bytes':32*reads,'dma_write_bytes':32*writes})
    need(len(c['rtl_command_intervals'])==len(commands),'per-command RTL waveform verification missing')
    for command,interval in zip(commands,c['rtl_command_intervals']):command['rtl_interval']=interval
    return {'status':'PASS','passed':True,'fixture':fixture,'summary':ref(directory/'sparse_gate_check.json'),
        'suite_summary':ref(suite_path),
        'environment_manifest':ref(envpath),'gem5_binary_sha256':environment['binary_sha256'],
        'memsim_library_sha256':environment['memsim_library_sha256'],
        'integration_source_lock':ref(directory/'integration_sources.json'),'source_sha256':sources['source_sha256'],
        'guest_binary_sha256':sources['workload_sha256'],'host_finish_tick_fs':finish(directory/'run.log'),
        'host_transactions':c['host_transactions'],'mmio_transactions':c['mmio_transactions'],
        'native_bursts':c['native_bursts'],'native_children':c['native_children'],'rtl_wave_handshakes':c['rtl_wave_handshakes'],
        'model_build_id':c['model_build_id'],'model_manifest':ref(model_path),'rtl_model_source_sha256':model['source_sha256'],
        'model_library_sha256':model['library_sha256'],'memsim_scale':cfg['memsim_scale'],
        'memsim_period_fs':read(directory/'memsim_config.json')['period_fs'],
        'axi_period_fs':read(directory/'protocol_summary.json')['period_ticks'],'commands':commands,
        'artifacts':{name:{'path':relative(directory/name),'sha256':value} for name,value in c['artifacts_sha256'].items()}}

def three_gate_case(directory,baseline_directory):
    result=gate_case(directory,'smoke')
    sys.path.insert(0,str(ROOT/'gem5_new/tools'))
    from hettrace.reader import CHAN_R,CHAN_W,read_records
    from hettrace.validate import validate_dir
    issues,summaries=validate_dir(str(directory/'hettrace'),ticks_per_second=10**15)
    need(not [e for e in issues if e.level=='ERROR'],'three-source raw trace validation failed')
    need({s.name for s in summaries}=={'host','vortex','coralnpu'} and all(s.transactions>0 for s in summaries),'gate coexistence does not contain all three real sources')
    need(sum(s.transactions for s in summaries)==result['host_transactions'],'three-source trace/physical AXI transaction count mismatch')
    sources={};intervals=[c['rtl_interval'] for c in result['commands']]
    for s in summaries:
        p=directory/'hettrace'/(s.name+'.hettrace');records=list(read_records(str(p)))
        sources[s.name]={'transactions':s.transactions,'bytes':sum(r.size for r in records if r.chan in (CHAN_R,CHAN_W)),
            'first_tick_fs':min(r.tick for r in records),'last_tick_fs':max(r.tick for r in records),
            'events_during_gate_busy':sum(any(c['start_tick_fs']<=r.tick<=c['end_tick_fs'] for c in intervals) for r in records),
            'raw_trace':ref(p)}
    import csv
    with (directory/'transactions.csv').open() as f:axi_bytes=sum(int(r['bytes']) for r in csv.DictReader(f))
    need(sum(s['bytes'] for s in sources.values())==axi_bytes,'three-source trace/AXI byte count mismatch')
    # The extra native case reuses the independently sealed accelerator binaries.
    # Recheck those exact files and bind the configured library/kernel paths.
    xp=baseline_directory/'environment/xpu_manifest.json';x=read(xp);need(x['passed'],'accelerator binary audit missing')
    config=(directory/'config.json').read_text();binaries={}
    for name in ('vortex','coralnpu','runtime','runtime_backend','gpu_kernel','npu_kernel'):
        item=x['files'][name];p=Path(item['path']);need(sha(p)==item['sha256'],'accelerator binary changed: '+name)
        if name in ('vortex','coralnpu','gpu_kernel','npu_kernel'):need(str(p) in config,'configured accelerator artifact differs: '+name)
        binaries[name]=ref(p)
    parent='gem5_new/workloads/three_source/host_main.cpp'
    original=subprocess.check_output(['git','show','3be39b697bdc315ae0be08ed2162c322bcf59462:'+parent],cwd=ROOT)
    need(hashlib.sha256(original).hexdigest()==sha(ROOT/parent),'original three-source workload changed from fixed upstream')
    result.update(sources=sources,accelerator_binaries=binaries,accelerator_baseline_manifest=ref(xp),
        original_three_source=ref(ROOT/parent),
        trace_validation_sources={p:sha(ROOT/p) for p in ('gem5_new/tools/hettrace/reader.py','gem5_new/tools/hettrace/validate.py')},
        trace_metadata={p.name:ref(p) for p in (directory/'hettrace').glob('*.json')},
        coexistence_scope='Same configuration; raw event counts during busy report actual overlap, not assumed concurrent contention')
    return result

def main():
    initial_collector_sha256=sha(Path(__file__))
    p=argparse.ArgumentParser();p.add_argument('--cpu-baseline',type=Path,default=ROOT/'results/baseline-memsim')
    p.add_argument('--xpu-baseline',type=Path,default=ROOT/'results/baseline-xpu')
    p.add_argument('--gate-cpu',type=Path,default=ROOT/'results/sparse-gate-system-final-cpu')
    p.add_argument('--gate-three',type=Path,default=ROOT/'results/sparse-gate-system-final-three')
    p.add_argument('--gate-slow',type=Path,default=ROOT/'results/sparse-gate-system-final-slow')
    p.add_argument('--gate-top512',type=Path,default=ROOT/'results/sparse-gate-system-final-top512')
    p.add_argument('--out',type=Path,default=ROOT/'evidence/system/summary.json');p.add_argument('--draft',action='store_true')
    a=p.parse_args();a.out.unlink(missing_ok=True);failures=[];entries={}
    jobs=[('baseline_cpu',lambda:baseline(a.cpu_baseline,'cpu')),('baseline_xpu',lambda:baseline(a.xpu_baseline,'xpu')),
        ('cpu_synthetic',lambda:gate_case(a.gate_cpu/'cpu_smoke','smoke')),
        ('cpu_real_weights',lambda:gate_case(a.gate_cpu/'cpu_real-weights','real-weights')),
        ('three_source_coexistence',lambda:three_gate_case(a.gate_three/'three_smoke',a.xpu_baseline))]
    jobs.append(('cpu_top512',lambda:gate_case(a.gate_top512/'cpu_top512','top512')))
    for name,fn in jobs:
        try:entries[name]=fn()
        except Exception as e:
            failures.append(name+': '+str(e));entries[name]={'status':'NOT_RUN' if isinstance(e,FileNotFoundError) else 'NOT_VERIFIED','passed':False,'reason':str(e)}
    feedback={}
    try:
        slow=gate_case(a.gate_slow/'cpu_real-weights_slow','real-weights');fast=entries['cpu_real_weights']
        need(fast['passed'] and slow['passed'],'gate timing comparison incomplete')
        need(slow['memsim_scale']==4 and slow['memsim_period_fs']==4*fast['memsim_period_fs'],'wrong gate timing scale')
        need(slow['guest_binary_sha256']==fast['guest_binary_sha256'] and slow['model_build_id']==fast['model_build_id'],'gate timing input/model differs')
        deltas=[]
        for x,y in zip(fast['commands'],slow['commands']):
            need(all(x[k]==y[k] for k in ('mode','status','result_count','score_count','dma_read_beats','dma_write_beats')),'gate timing comparison changed operation')
            delta=y['cycles']-x['cycles'];deltas.append(delta)
            if not x['expected_error']:need(delta>0,'slower memory did not delay completed gate command')
        host_delta=slow['host_finish_tick_fs']-fast['host_finish_tick_fs'];need(host_delta>0,'slower memory did not delay gate host')
        feedback={'status':'PASS','passed':True,'scale':4,'host_finish_delta_fs':host_delta,'host_finish_delta_ns':host_delta/1e6,
            'command_cycle_deltas':deltas,'slow_case':slow,
            'scope':'Same executable, RTL and data; polling traffic may change; compare observed completed command latency and host exit'}
    except Exception as e:
        failures.append('gate_memory_feedback: '+str(e));feedback={'status':'NOT_RUN' if isinstance(e,FileNotFoundError) else 'NOT_VERIFIED','passed':False,'reason':str(e)}
    contract_path=ROOT/'results/sparse-gate-backend-contract-portable/summary.json';contract={}
    try:
        contract=read(contract_path);need(contract['passed'] and contract['exclusive_rejections']==4,'adapter contract test incomplete')
        need(contract['library_sha256']==sha(ROOT/'build/sparse_gate_model/libsparse_gate_model.so'),'adapter test RTL library changed')
        for name,value in contract['source_sha256'].items():need(sha(ROOT/name)==value,'adapter test source changed')
        for name,value in contract['artifacts_sha256'].items():need(sha(contract_path.parent/name)==value,'adapter test artifact changed')
        contract={'status':'PASS','passed':True,'summary':ref(contract_path),**contract}
    except Exception as e:failures.append('adapter_contract: '+str(e));contract={'passed':False,'reason':str(e)}
    wave_controls={};wave_path=ROOT/'results/sparse-gate-wave-controls/summary.json'
    try:
        wave_controls=read(wave_path)
        need(wave_controls['passed'] and len(wave_controls['negative_controls'])==3 and all(c['detected'] for c in wave_controls['negative_controls']),'wave corruption controls incomplete')
        for name,value in wave_controls['locked_sha256'].items():need(sha(ROOT/name)==value,'wave control source/input changed')
        wave_controls={'summary':ref(wave_path),**wave_controls}
    except Exception as e:failures.append('wave_controls: '+str(e));wave_controls={'passed':False,'reason':str(e)}
    result={'schema':'sparse_gate_public_system_evidence_v1','passed':not failures,
        'status':'PASS' if not failures else 'INCOMPLETE','base_upstream_revision':'3be39b697bdc315ae0be08ed2162c322bcf59462',
        'current_revision':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
        'source_lock':ref(ROOT/'env/sources.lock.json'),'collector_sha256':initial_collector_sha256,
        'path':'CPU / Vortex SimX / CoralNPU RTL -> native AXI256 -> AXI2Flit -> UCIe -> AouTarget -> RTL dispatcher / same online mem_sim',
        'time_axis':'single gem5 native SystemC event axis, 1 fs; Verilator evaluated at existing AXI clock edges',
        'cases':entries,'gate_memory_feedback':feedback,'adapter_contract':contract,'wave_controls':wave_controls,'failures':failures,
        'limitations':['Post-projection index selection and packed KV gather only; no full LLM or projection acceleration',
            'Real-weight fixture uses seeded random activations, not text-derived full-model traces',
            'Three-source gate case runs after the original GPU/NPU computations: configuration coexistence, not concurrent gate contention',
            'HBM4 provisional behavioral timing; no PHY or silicon performance claim',
            'Software-managed epoch/invalidate; no cache coherence or in-flight reset recovery']}
    need(sha(Path(__file__))==initial_collector_sha256,'collector source changed during execution')
    if failures and not a.draft:raise SystemExit('\n'.join(failures))
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(result,indent=2,ensure_ascii=False)+'\n')
    need(read(a.out)==result,'public evidence readback differs');print(json.dumps({'path':str(a.out),'status':result['status'],'sha256':sha(a.out),'failures':failures},indent=2))
if __name__=='__main__':main()
