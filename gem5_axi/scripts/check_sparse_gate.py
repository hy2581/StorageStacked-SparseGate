#!/usr/bin/env python3
"""Fail-closed join: host AXI/UCIe -> dispatcher -> RTL DMA -> online DRAM.

No simulation is performed here. Check observed handshakes, native payloads,
physical RD/WR/DFI, final bytes and the actual guest's bit-exact result checks.
"""
import argparse
from collections import Counter, defaultdict, deque
import csv
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
def rows(path):
    with path.open() as stream:
        return list(csv.DictReader(stream))
def load(path): return json.loads(path.read_text())
def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def need(ok, message):
    if not ok: raise RuntimeError(message)

def audit_gate_wave(path, events, page, period):
    """Read pre-edge pins independently of the C++ log, including backpressure."""
    names={};changes={};tick=0;state={};held={};actual=[];commands=[];active=None;reads=deque();status_reads=[]
    internal=('busy','done_flag','error_flag','error_code','cache_valid','cycles','score_count','result_count','dma_reads','dma_writes','start_pulse',
        'cfg[3]','cfg[16]','cfg[17]','cfg[18]','cfg[19]','cfg[20]','cfg[21]')
    def consume(t,change):
        nonlocal active
        before=state.copy();state.update(change)
        if state.get('clk')!=1 or before.get('clk')==1 or not before.get('rst_n'):return
        if before['rtl_busy']==state['rtl_busy'] and not held and not any(before[s+'_axi_'+c+'valid'] for s in ('s','m') for c in ('aw','w','b','ar','r')):return
        if not before['rtl_busy'] and state['rtl_busy']:
            need(active is None and before['rtl_start_pulse']==1,'busy rose without accepted START')
            need(state['rtl_cycles']==0,'cycles not cleared at START')
            active={'start_tick_fs':t,'reads':0,'writes':0,'read_outstanding':0,'write_outstanding':0,'last_b_tick_fs':None}
            for name,index in [('mode',3),('nkeys',16),('ncand',17),('topk',18),('heads',19),('context',20),('epoch',21)]:active[name]=before['rtl_cfg['+str(index)+']']
        for side in ('s','m'):
            for channel,fields in [('aw',('awid','awaddr','awlen','awsize','awburst')),
                ('w',('wdata','wstrb','wlast')),('b',('bid','bresp')),
                ('ar',('arid','araddr','arlen','arsize','arburst')),('r',('rid','rdata','rresp','rlast'))]:
                prefix=side+'_axi_';key=side+'_'+channel;v=before[prefix+channel+'valid'];ready=before[prefix+channel+'ready']
                payload=tuple(before[prefix+f] for f in fields)
                if key in held:need(v and payload==held[key],'RTL pin payload changed under backpressure: '+key)
                if v and not ready:held[key]=payload
                else:held.pop(key,None)
                if v and ready:
                    actual.append((t,side.upper()+'_'+channel.upper(),payload))
                    if side=='m':
                        need(active is not None,'DMA handshake outside a busy command')
                        if channel=='ar':active['read_outstanding']+=1
                        elif channel=='aw':active['write_outstanding']+=1
                        elif channel=='r':
                            active['read_outstanding']-=1;active['reads']+=1
                            need(active['read_outstanding']>=0,'orphan per-command DMA R')
                        elif channel=='b':
                            active['write_outstanding']-=1;active['writes']+=1;active['last_b_tick_fs']=t
                            need(active['write_outstanding']>=0,'orphan per-command DMA B')
                    elif channel=='ar':
                        # The wrapper snapshots register data on AR, not on R.
                        status=(before['rtl_error_code']<<8)|(before['rtl_error_flag']<<2)|(before['rtl_done_flag']<<1)|before['rtl_busy']
                        reads.append((t,before[prefix+'araddr'],status))
                    elif channel=='r':
                        need(reads,'slave R without AR in waveform');ar_tick,address,status=reads.popleft()
                        if address==page+4:
                            value=(before[prefix+'rdata']>>32)&0xffffffff
                            need(value==status,'STATUS read differs from state sampled at AR')
                            status_reads.append({'ar_tick_fs':ar_tick,'r_tick_fs':t,'status':value})
        if before['rtl_busy'] and not state['rtl_busy']:
            need(active is not None,'busy fell without a command')
            delta=t-active['start_tick_fs'];need(delta%period==0 and delta//period==state['rtl_cycles'],'busy interval differs from RTL cycles')
            need(active['read_outstanding']==active['write_outstanding']==0,'DONE/error while DMA remains outstanding')
            need(active['reads']==state['rtl_dma_reads'] and active['writes']==state['rtl_dma_writes'],'per-command RTL DMA count mismatch')
            if state['rtl_done_flag']:
                need(not state['rtl_error_flag'] and state['rtl_cache_valid'],'successful completion state inconsistent')
                need(active['last_b_tick_fs'] is not None and active['last_b_tick_fs']<t,'DONE precedes final DMA B response')
            active.update(end_tick_fs=t,cycles=state['rtl_cycles'],status=(state['rtl_error_code']<<8)|(state['rtl_error_flag']<<2)|(state['rtl_done_flag']<<1),
                score_count=state['rtl_score_count'],result_count=state['rtl_result_count'],cache_valid=state['rtl_cache_valid'])
            commands.append(active);active=None
    with path.open() as f:
        head='';depth=0
        for line in f:
            head+=line
            words=line.split()
            if words and words[0]=='$scope':depth+=1
            elif words and words[0]=='$upscope':depth-=1
            if words and words[0]=='$var' and depth==1:
                name=words[4]
                if name in ('clk','rst_n') or name.startswith(('s_axi_','m_axi_')):names[words[3]]=name
            elif words and words[0]=='$var' and depth==2 and words[4] in internal:names[words[3]]='rtl_'+words[4]
            if '$enddefinitions' in line:break
        need(re.search(r'\$timescale\s+1fs\s+\$end',head),'RTL waveform is not on 1 fs scale')
        need(all('rtl_'+n in names.values() for n in internal),'missing wrapper state in waveform')
        for line in f:
            words=line.split()
            if not words:continue
            if line.startswith('#'):consume(tick,changes);tick=int(line[1:]);changes={}
            elif words[0][0] in 'bB' and len(words)==2 and words[1] in names:
                bits=words[0][1:];need(set(bits)<={'0','1'},'unknown RTL wave bits');changes[names[words[1]]]=int(bits,2)
            elif words[0][0] in '01xXzZ' and words[0][1:] in names:
                need(words[0][0] in '01','unknown RTL wave bit');changes[names[words[0][1:]]]=int(words[0][0])
        consume(tick,changes)
    expected=[]
    for e in events:
        kind=e['event']
        if kind not in ('S_AW','S_W','S_B','S_AR','S_R','M_AW','M_W','M_B','M_AR','M_R'):continue
        ch=kind[2:]
        if ch in ('AW','AR'):
            # Size is independently recorded in the pin wave; DMA must be32B,
            # guest register traffic in this acceptance is exactly32-bit.
            payload=(int(e['id']),int(e['address']),int(e['beats'])-1,5 if kind[0]=='M' else 2,1)
        elif ch=='W':payload=(int(e['data_hex'],16),int(e['strb_hex'],16),1)
        elif ch=='B':payload=(int(e['id']),int(e['resp']))
        else:payload=(int(e['id']),int(e['data_hex'],16),int(e['resp']),1)
        expected.append((int(e['tick_fs']),kind,payload))
    need(sorted(actual)==sorted(expected),'RTL waveform and adapter handshake log differ')
    need(active is None and not reads,'unfinished command or slave read in waveform')
    starts=[e for e in events if e['event']=='S_W' and int(e['address'])==page+8 and
        (int(e['strb_hex'],16)>>8)&15==15 and (int(e['data_hex'],16)>>64)&0xffffffff==1]
    need(len(starts)==len(commands),'START writes and busy intervals differ')
    for i,(start,cmd) in enumerate(zip(starts,commands)):
        need(int(start['tick_fs'])<cmd['start_tick_fs'],'busy precedes command write')
        if i:need(commands[i-1]['end_tick_fs']<int(start['tick_fs']),'overlapping command lifetime')
        end=commands[i+1]['start_tick_fs'] if i+1<len(commands) else float('inf')
        final_reads=[r for r in status_reads if cmd['end_tick_fs']<=r['ar_tick_fs']<end and r['status']==cmd['status']]
        need(final_reads,'completed command has no matching host STATUS observation')
        cmd['first_terminal_status_ar_tick_fs']=final_reads[0]['ar_tick_fs']
        cmd['first_terminal_status_r_tick_fs']=final_reads[0]['r_tick_fs']
    return len(actual),commands

def check(d, fixture, model_manifest):
    # A failed rerun must never leave an older positive receipt behind.
    (d/'sparse_gate_check.json').unlink(missing_ok=True)
    cfg=load(d/'config.json')['systemc_kernel']['system']['axi']
    need(cfg['gate_enable'] and cfg['backend']=='aou' and cfg['memory_backend']=='memsim','wrong system configuration')
    model=load(model_manifest)
    need(model['status']=='BUILT_NOT_VALIDATED','model build incomplete')
    need(sha(Path(cfg['gate_library']))==model['library_sha256'],'loaded DLL hash differs')
    for name,value in model['source_sha256'].items(): need(sha(ROOT/name)==value,'stale model source: '+name)
    s=load(d/'sparse_gate_summary.json');aou=load(d/'aou_summary.json')
    protocol=load(d/'protocol_summary.json');mem=load(d/'memsim_bridge_summary.json');core=load(d/'memsim_core.json')
    need(s['drained'] and s['time_unit_fs']==1 and s['build_id']==model['build_id'],'RTL adapter not drained or stale build ID')
    need(core['passed'] and mem['passed'] and core['command_errors']==core['dfi_errors']==0,'native memory failure')
    need(protocol['drained'] and protocol['accepted']==protocol['completed'],'undrained host protocol')
    need(load(d/'link_check_summary.json')['passed'],'raw UCIe verification missing')
    base=int(cfg['base']);page=int(cfg['gate_base']);period=mem['period_fs']
    bus=rows(d/'aou_events.csv');by={ch:[r for r in bus if r['channel']==ch] for ch in ('AW','W','B','AR','R')}
    live_ids=set()
    for e in bus:
        ch=e['channel'];key=(ch in ('AW','B'),int(e['id']))
        if ch in ('AW','AR'):
            need(key not in live_ids,'host reused an AXI parent ID before completion');live_ids.add(key)
        elif ch=='B' or (ch=='R' and int(e['last'])):
            need(key in live_ids,'host response without a live parent ID');live_ids.remove(key)
    need(not live_ids,'host AXI parent ID still outstanding')
    paths={(r['channel'],r['axi_id'],r['axi_tick_fs']):r for r in rows(d/'axi_flit_path.csv')}
    replies={ch:defaultdict(deque) for ch in ('B','R')}
    for ch in replies:
        for r in by[ch]:replies[ch][r['id']].append(r)
    requests=defaultdict(deque);write_data=iter(by['W'])
    for ch in ('AW','AR'):
        for a in by[ch]:
            n=1<<int(a['size']);beats=int(a['len'])+1;address=int(a['address'])
            data=bytearray();mask=[];returned=bytearray();fwd=[paths[ch,a['id'],a['tick']]];rev=[]
            for b in range(beats):
                lane=(address+b*n)%32
                if ch=='AW':
                    w=next(write_data);raw=int(w['data_hex'],16).to_bytes(32,'little')
                    data.extend(raw[lane:lane+n]);mask.extend(str((int(w['strb_hex'],16)>>(lane+j))&1) for j in range(n))
                    fwd.append(paths['W',a['id'],w['tick']])
                else:
                    r=replies['R'][a['id']].popleft();need(int(r['resp'])==0,'unexpected host R error')
                    returned.extend(int(r['data_hex'],16).to_bytes(32,'little')[lane:lane+n]);rev.append(paths['R',a['id'],r['tick']])
            if ch=='AW':
                r=replies['B'][a['id']].popleft();need(int(r['resp'])==0,'unexpected host B error');rev.append(paths['B',a['id'],r['tick']])
            requests[ch=='AW',int(a['id']),address,beats].append(dict(data=data.hex(),mask=''.join(mask),returned=returned.hex(),bytes=n*beats,
                forward=max(int(p['rx_last_tick_fs']) for p in fwd),reverse=min(int(p['tx_first_tick_fs']) for p in rev),address=address,width=n))
    need(next(write_data,None) is None and all(not q for table in replies.values() for q in table.values()),'unmatched host data/response')
    events=rows(d/'sparse_gate_events.csv')
    wave_handshakes,wave_commands=audit_gate_wave(d/'sparse_gate.vcd',events,page,protocol['period_ticks'])
    need(all(int(x['tick_fs'])<=int(y['tick_fs']) for x,y in zip(events,events[1:])),'nonmonotonic adapter events')
    mmio=deque();issues=[];dma_addr=deque();dma_w=deque();dma_read_return=deque();dma_write_return=deque();host_completed=0
    pending_tags={};mmio_current=None
    for e in events:
        kind=e['event'];tick=int(e['tick_fs']);write=bool(int(e['write']));addr=int(e['address']);ident=int(e['id']);tag=int(e['tag']);beats=int(e['beats'])
        if kind=='mmio_begin':
            need(mmio_current is None,'overlapping MMIO objects');q=requests[write,ident,addr,beats];need(bool(q),'orphan MMIO');req=q.popleft()
            need(page<=addr<page+4096 and tick>=req['forward'],'MMIO bypassed UCIe');mmio_current=(req,write,ident,bytearray(),0)
        elif kind in ('S_AW','S_AR'):
            need(mmio_current is not None and ident==mmio_current[2],'MMIO address identity');need(tick>=mmio_current[0]['forward'],'RTL address before link delivery')
        elif kind=='S_W':
            need(mmio_current is not None and mmio_current[1],'orphan RTL slave write')
            req,wr,id0,raw,done=mmio_current;lane=(req['address']+done*req['width'])%32
            data=int(e['data_hex'],16).to_bytes(32,'little')[lane:lane+req['width']];raw.extend(data)
            need(e['strb_hex'] and int(e['strb_hex'],16)>>lane & ((1<<req['width'])-1)==int(req['mask'][done*req['width']:(done+1)*req['width']][::-1],2),'MMIO WSTRB changed')
            mmio_current=(req,wr,id0,raw,done+1)
        elif kind in ('S_B','S_R'):
            need(mmio_current is not None,'orphan RTL slave response');req,wr,id0,raw,done=mmio_current
            need(ident==id0 and int(e['resp'])==0 and tick<=req['reverse'],'MMIO return before RTL/identity failure')
            if kind=='S_B':need(wr and raw.hex()==req['data'],'MMIO write payload changed');mmio_current=None;host_completed+=1
            else:
                need(not wr,'read response to write');lane=(req['address']+done*req['width'])%32
                raw.extend(int(e['data_hex'],16).to_bytes(32,'little')[lane:lane+req['width']]);done+=1
                if done==beats:need(raw.hex()==req['returned'],'MMIO read payload changed');mmio_current=None;host_completed+=1
                else:mmio_current=(req,wr,id0,raw,done)
        elif kind in ('M_AW','M_AR'):
            need(ident==1 and addr%32==0 and not page<=addr<page+4096,'invalid DMA address');dma_addr.append((kind=='M_AW',addr,tick))
        elif kind=='M_W':dma_w.append(e)
        elif kind=='memory_issue':
            need(tag not in pending_tags,'reused live memory tag')
            item=dict(event=e,write=write,address=addr,beats=beats,tag=tag)
            if e['source']=='HOST':
                q=requests[write,ident,addr,beats];need(bool(q),'orphan host bypass');item['host']=q.popleft()
                need(not page<=addr<page+4096 and tick>=item['host']['forward'],'host bypass address/link causality')
            else:
                need(dma_addr,'DMA issue without RTL address');dw,da,dt=dma_addr.popleft()
                need((write,addr)==(dw,da) and beats==1 and dt<=tick,'DMA metadata changed')
                if write:
                    need(dma_w,'DMA issue without RTL W');w=dma_w.popleft();need(int(w['tick_fs'])<=tick,'DMA data from future')
                    item['dma_data']=int(w['data_hex'],16).to_bytes(32,'little').hex();item['dma_mask']=''.join(str((int(w['strb_hex'],16)>>j)&1) for j in range(32))
            issues.append(item);pending_tags[tag]=item
        elif kind=='memory_return':
            need(tag in pending_tags,'orphan memory return');item=pending_tags.pop(tag);item['return']=e
            need(write==item['write'] and addr==item['address'],'memory return metadata changed')
            if 'host' in item:need(tick<=item['host']['reverse'],'host response Flit precedes shared memory return');host_completed+=1
            elif write:dma_write_return.append(item)
            else:dma_read_return.append(item)
        elif kind in ('M_B','M_R'):
            queue=dma_write_return if kind=='M_B' else dma_read_return;need(queue,'RTL DMA response without native return');item=queue.popleft();item['rtl_return']=e
            need(int(item['return']['tick_fs'])<=tick and ident==1 and int(e['resp'])==0,'DMA completion causality/status')
    need(not pending_tags and not dma_addr and not dma_w and not dma_read_return and not dma_write_return and mmio_current is None,'undrained adapter trace')
    need(all(not q for q in requests.values()),'host request never reached dispatcher')
    native=rows(d/'memsim_bridge.csv');groups={};children={};completions={}
    for e in native:
        need(int(e['tick'])%period==0,'native event off memory clock');groups.setdefault(e['burst'],[]).append(e)
        if e['event'] in ('submit','complete'):
            table=children if e['event']=='submit' else completions;need(e['mem_id'] not in table,'duplicate memory child');table[e['mem_id']]=e
    need(len(groups)==len(issues)==mem['bursts']==s['memory_issued']==s['memory_completed']==aou['memory_completed'],'memory accounting mismatch')
    need(children.keys()==completions.keys() and len(children)==core['submitted']==core['returned']==mem['children'],'native child accounting mismatch')
    physical=defaultdict(list);signals=defaultdict(list)
    for c in rows(d/'memsim_commands.csv'):
        if c['command'] in ('RD','WR'):physical[c['request_id']].append(c)
    for e in rows(d/'memsim_dfi_signals.csv'):
        if e['kind'] in ('WRITE_DATA','READ_DATA'):signals[e['request_id']].append(e)
    need(physical.keys()==signals.keys()==children.keys(),'missing physical command/DFI child')
    for mid,req in children.items():
        ret=completions[mid];cmds=physical[mid];need(len(cmds)==1,'unexpected memory forwarding in suite');cmd=cmds[0]
        need(all(req[k]==ret[k] for k in ('burst','address','bytes','offset','command')),'native child return identity')
        need(cmd['command']==('WR' if req['command']=='W' else 'RD') and int(cmd['address'],0)==int(req['address'])-base,'physical command mismatch')
        need(int(req['tick'])<=int(ret['issued_cycle'])*period<=int(ret['completion_cycle'])*period<=int(ret['tick']),'native clock causality')
        need(int(cmd['cycle'])==int(ret['issued_cycle']) and int(ret['status']) in (0,1),'physical timing/error')
        data=bytearray();mask=bytearray()
        for e in sorted(signals[mid],key=lambda e:(int(e['cycle']),int(e['phase']))):
            need(int(e['address'],0)==int(req['address'])-base+len(data),'DFI address')
            data.extend(bytes.fromhex(e['dfi_wrdata'] if req['command']=='W' else e['dfi_rddata']))
            if req['command']=='W':mask.extend(bytes.fromhex(e['dfi_wrdata_mask']))
        need(data.hex()==(req['data'] if req['command']=='W' else ret['data']),'DFI payload changed')
        if req['command']=='W':need(list(mask)==[0 if b=='1' else 255 for b in req['mask']],'DFI mask changed')
    image=defaultdict(int)
    for item,group in zip(issues,groups.values()):
        accepts=[e for e in group if e['event']=='accept'];returns=[e for e in group if e['event']=='return']
        need(len(accepts)==len(returns)==1,'native burst does not return exactly once');a,r=accepts[0],returns[0]
        need(int(a['axi_id'])==item['tag'] and int(a['address'])==item['address'] and (a['command']=='W')==item['write'],'dispatcher/native request changed')
        need(int(item['event']['tick_fs'])<=int(a['tick'])<=int(r['tick'])<=int(item['return']['tick_fs']),'dispatcher/native time reversal')
        need(int(a['status'])==int(r['status'])==0,'unexpected memory error')
        host=item.get('host');length=int(a['bytes']);address=int(a['address'])-base
        if item['write']:
            want_data=host['data'] if host else item['dma_data'];want_mask=host['mask'] if host else item['dma_mask']
            need(a['data']==want_data and a['mask']==want_mask,'signal/native write differs')
            for j,b in enumerate(bytes.fromhex(a['data'])):
                if a['mask'][j]=='1':image[address+j]=b
        else:
            want=host['returned'] if host else int(item['rtl_return']['data_hex'],16).to_bytes(32,'little').hex()
            need(r['data']==want,'native/signal read differs')
            need(bytes(image[address+j] for j in range(length)).hex()==r['data'],'read differs from shared logical image')
        chunks=[e for e in group if e['event']=='submit'];offset=0;data=bytearray()
        for e in chunks:
            need(int(e['offset'])==offset and int(e['address'])==int(a['address'])+offset,'native child coverage')
            n=int(e['bytes']);need(n>0 and int(a['tick'])<=int(e['tick'])<=int(completions[e['mem_id']]['tick'])<=int(r['tick']),'native child lifetime')
            if item['write']:need(e['data']==a['data'][2*offset:2*(offset+n)] and e['mask']==a['mask'][offset:offset+n],'native write child differs')
            else:data.extend(bytes.fromhex(completions[e['mem_id']]['data']))
            offset+=n
        need(offset==length,'incomplete native burst');
        if not item['write']:need(data.hex()==r['data'],'native read assembly changed')
    actual={}
    for e in rows(d/'memsim_image.csv'):
        a=int(e['address'],0);raw=bytes.fromhex(e['data']);need(bytes.fromhex(e['init'])==b'\xff'*len(raw),'uninitialized native image')
        for j,b in enumerate(raw):need(a+j not in actual,'overlapping image rows');actual[a+j]=b
    need(all(actual.get(a,0)==b for a,b in image.items()) and all(image.get(a,0)==b for a,b in actual.items()),'final memory image differs')
    need(host_completed==s['host_completed']==len(by['AW'])+len(by['AR'])==aou['target_reads']+aou['target_writes'],'host count mismatch')
    log=(d/'run.log').read_text();marker='SPARSE GATE TOP512' if fixture=='top512' else 'SPARSE GATE'
    need(marker+' PASS' in log and marker+' FAIL' not in log,'guest acceptance missing')
    commands=[tuple(map(int,m)) for m in re.findall(r'GATE_COMMAND mode=(\d+) status=(\d+) count=(\d+) scores=(\d+) read_beats=(\d+) write_beats=(\d+) cycles=(\d+)',log)]
    h,n,k,c=(32,640,512,0) if fixture=='top512' else (32,64,8,16) if fixture=='real-weights' else (4,16,4,4)
    expected=[(0,2,k,n,3*h+3*n+9*k,10*k),(2,2,k,0,9*k,10*k),(1,2,k,c,3*h+3*c+(c+7)//8+9*k,10*k),(2,516,k,0,0,0),(0,2,k,n,3*h+3*n+9*k,10*k)]
    if fixture=='top512':expected=[(0,2,512,640,6624,5120),(2,2,512,0,4608,5120)]
    need(len(commands)==len(expected) and all(tuple(x[:6])==want and x[6]>0 for x,want in zip(commands,expected)),'guest command results or physical counts differ')
    need(len(wave_commands)==len(commands),'guest commands differ from busy intervals')
    for guest,wave in zip(commands,wave_commands):
        need(guest[0]==wave['mode'],'guest mode differs from accepted RTL configuration')
        need((wave['heads'],wave['nkeys'],wave['topk'],wave['ncand'])==(h,n,k,c),'accepted RTL fixture geometry differs')
        need(tuple(guest[1:])==tuple(wave[k] for k in ('status','result_count','score_count','reads','writes','cycles')),'guest report differs from independent per-command waveform')
    need(s['dma_reads']==sum(x[4] for x in commands)==s['dma_read_completed'] and s['dma_writes']==sum(x[5] for x in commands)==s['dma_write_completed'],'RTL reported/DMA observed counters differ')
    lock=load(d/'integration_sources.json');need(lock['verified_after_run'],'source/guest executable lock is incomplete')
    for name,value in lock['source_sha256'].items():need(sha(ROOT/name)==value,'integration source changed: '+name)
    need(sha(Path(lock['workload_path']))==lock['workload_sha256'],'guest executable changed')
    evidence=['integration_sources.json','config.json','run.log','protocol_summary.json','aou_summary.json','sparse_gate_summary.json','sparse_gate_events.csv','sparse_gate.vcd','axi_wave.vcd','aou_events.csv','transactions.csv','ucie_flits.csv','ucie_soc.csv','ucie_mem.csv','axi_flit_path.csv','link_check_summary.json','memsim_bridge.csv','memsim_bridge_summary.json','memsim_core.json','memsim_commands.csv','memsim_dfi_signals.csv','memsim_image.csv']
    result=dict(passed=True,scope='CPU commands through UCIe; real RTL DMA; same online mem_sim authority',fixture=fixture,
        host_transactions=host_completed,mmio_transactions=s['mmio_reads']+s['mmio_writes'],native_bursts=len(groups),native_children=len(children),
        dma_read_beats=s['dma_reads'],dma_write_beats=s['dma_writes'],rtl_wave_handshakes=wave_handshakes,guest_commands=commands,rtl_command_intervals=wave_commands,model_build_id=s['build_id'],
        model_manifest_sha256=sha(model_manifest),checker_sha256=sha(Path(__file__)),artifacts_sha256={p:sha(d/p) for p in evidence})
    (d/'sparse_gate_check.json').write_text(json.dumps(result,indent=2)+'\n');return result

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('directory',type=Path);p.add_argument('--fixture',choices=['smoke','real-weights','top512'],required=True)
    p.add_argument('--model-manifest',type=Path,default=ROOT/'build/sparse_gate_model/build.json')
    a=p.parse_args();print(json.dumps(check(a.directory,a.fixture,a.model_manifest),indent=2))
