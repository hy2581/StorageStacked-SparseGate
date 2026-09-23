#!/usr/bin/env python3
"""Cross-check SparseGate RTL pin waveforms against adapter events."""
from collections import deque
import re


def need(ok, message):
    if not ok:
        raise RuntimeError(message)


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
