#!/usr/bin/env python3
"""Render Chinese measurement labels from the unchanged, accepted evidence."""
import hashlib
import json
import os
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib import font_manager
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'paper/zh/figures'
OUT.mkdir(parents=True, exist_ok=True)

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def main():
    source = ROOT / 'paper/generated/manifest.json'
    lock = json.loads(source.read_text())
    assert not lock['preview'] and not lock['missing_evidence']
    for name, digest in lock['input_sha256'].items():
        assert sha(ROOT/name) == digest, name
    font = Path(os.environ.get('SPARSE_GATE_ZH_FONT', '/usr/share/fonts/truetype/droid/DroidSansFallbackFull.ttf'))
    assert font.is_file(), 'A CJK font is required: ' + str(font)
    font_manager.fontManager.addfont(str(font))
    family = font_manager.FontProperties(fname=str(font)).get_name()
    # Use genuine TrueType glyphs for PDF Type 42 embedding. CFF-based Noto
    # collections render in PNG but are misdeclared by this Matplotlib version.
    plt.rcParams.update({'font.family':['DejaVu Sans',family], 'font.size':9, 'axes.unicode_minus':False,
                         'axes.spines.top':False, 'axes.spines.right':False,
                         'pdf.fonttype':42, 'ps.fonttype':42})
    used = ['evidence/core/lane_sweep.json', 'evidence/system/completion_window.json', 'evidence/system/summary.json']
    lane, wave, system = [json.loads((ROOT/p).read_text()) for p in used]
    assert lane['passed'] and wave['passed'] and system['passed'] and not system['failures']

    fig, ax = plt.subplots(figsize=(4.7,2.8),layout='constrained')
    x = np.arange(3); bottom = np.zeros(3)
    phases = [('arithmetic_cycles','算术与 Q 检查','#294f70'),('ready_cycles','加载与等待','#489393'),
              ('heap_cycles','堆维护','#dc9955'),('score_output_cycles','分数交接','#869baa'),
              ('result_output_cycles','结果输出','#c3cbd1')]
    for key,label,color in phases:
        values = np.array([v['phases'][key] for v in lane['results']])/1000
        ax.bar(x,values,bottom=bottom,label=label,color=color,width=.54); bottom += values
    for i,v in enumerate(lane['results']):
        assert sum(v['phases'][key] for key,_,_ in phases) == v['measured']['cycles']
        ax.text(i,bottom[i]+9,format(v['measured']['cycles'],','),ha='center',fontsize=9)
    ax.set_xticks(x,[str(r['lanes'])+' 路' for r in lane['results']]); ax.set_ylabel('核心实测周期（千周期）')
    ax.set_ylim(0,max(bottom)*1.2); ax.grid(axis='y',alpha=.18); ax.set_axisbelow(True)
    ax.legend(loc='upper right',fontsize=8.5,frameon=False)
    save(fig,'lane_sweep')

    points = wave['points']; origin = wave['origin_tick_fs']; command = wave['command']
    assert command == system['cases']['cpu_synthetic']['commands'][0]['rtl_interval']
    t = np.array([(p['tick_fs']-origin)/1e6 for p in points])
    signals = [('clk','AXI 时钟'),('m_axi_bvalid','DMA BVALID'),('m_axi_bready','DMA BREADY'),
               ('busy','BUSY'),('done_flag','DONE'),('s_axi_arvalid','MMIO ARVALID'),('s_axi_rvalid','MMIO RVALID')]
    fig,ax = plt.subplots(figsize=(7,3.1),layout='constrained')
    for i,(name,label) in enumerate(signals):
        level=(len(signals)-1-i)*1.4
        ax.step(t,[p['values'][name]*.78+level for p in points],where='post',linewidth=1.1,color='#294f70')
    for tick,label,color in [(origin,'最后一次 DMA B 握手','#294f70'),(command['end_tick_fs'],'DONE／缓存提交','#dc9955'),
                             (command['first_terminal_status_r_tick_fs'],'RTL 状态响应 R = 0x2','#489393')]:
        ax.axvline((tick-origin)/1e6,color=color,linestyle='--',linewidth=.9,label=label)
    ax.set_yticks([(len(signals)-1-i)*1.4+.39 for i in range(len(signals))],[v[1] for v in signals])
    ax.tick_params(axis='y',length=0,labelsize=8)
    ax.set_xlabel('相对最后一次 DMA B 握手的时间（ns）'); ax.set_xticks(np.arange(t[0],t[-1]+.1,2))
    ax.set_xlim(t[0],t[-1]); ax.grid(axis='x',alpha=.12); ax.set_ylim(-.25,len(signals)*1.4+.15)
    ax.legend(loc='upper center',bbox_to_anchor=(.5,1.13),ncol=3,frameon=False,fontsize=7.5)
    ax.spines['left'].set_visible(False); save(fig,'completion_wave')

    case=system['cases']['cpu_real_weights']; slow=system['gate_memory_feedback']['slow_case']
    commands=case['commands'][:3]; slowed=slow['commands'][:3]
    assert case['passed'] and slow['passed'] and case['axi_period_fs']==slow['axi_period_fs']
    assert slow['memsim_period_fs']==4*case['memsim_period_fs']
    assert [c['mode'] for c in commands]==[c['mode'] for c in slowed]==['FULL','REUSE','REINDEX']
    assert [(c['dma_read_bytes'],c['dma_write_bytes']) for c in commands]==[(c['dma_read_bytes'],c['dma_write_bytes']) for c in slowed]
    fig,axes=plt.subplots(1,2,figsize=(6.6,2.5),layout='constrained')
    labels=[c['mode'] for c in commands]; x=np.arange(3)
    max_time=max(c['cycles'] for c in slowed)*case['axi_period_fs']/1e9
    for offset,items,label,color in [(-.18,commands,'存储周期 1 倍','#294f70'),(.18,slowed,'存储周期 4 倍','#489393')]:
        values=[c['cycles']*case['axi_period_fs']/1e9 for c in items]
        axes[0].bar(x+offset,values,width=.34,label=label,color=color)
        for i,value in enumerate(values): axes[0].text(i+offset,value+max_time*.018,f'{value:.1f}',ha='center',fontsize=7.5)
    axes[0].set_xticks(x,labels); axes[0].set_ylabel('RTL 忙区间（μs）')
    axes[0].set_ylim(0,max_time*1.25); axes[0].legend(fontsize=7.5,frameon=False)
    payload=[(c['dma_read_bytes']+c['dma_write_bytes'])/1024 for c in commands]
    axes[1].bar(labels,payload,color=['#294f70','#489393','#dc9955'],width=.6)
    axes[1].set_ylabel('DMA 有效载荷（KiB）'); axes[1].set_ylim(0,max(payload)*1.2)
    for i,value in enumerate(payload): axes[1].text(i,value+max(payload)*.02,f'{value:.2f}',ha='center',fontsize=8)
    for ax in axes: ax.grid(axis='y',alpha=.18); ax.set_axisbelow(True); ax.tick_params(axis='x',labelsize=8)
    save(fig,'native_modes')
    record={'schema':'sparse_gate_chinese_measurement_figures_v1',
            'source_manifest_sha256':sha(source),'generator_sha256':sha(__file__),
            'input_sha256':{p:sha(ROOT/p) for p in used},
            'font':{'file':font.name,'family':family,'sha256':sha(font),'latin_family':'DejaVu Sans'},
            'output_sha256':{str(p.relative_to(ROOT)):sha(p) for p in sorted(OUT.iterdir()) if p.suffix in ['.pdf','.png']}}
    (OUT/'manifest.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(record,ensure_ascii=False,indent=2))

def save(fig,name):
    fig.savefig(OUT/(name+'.pdf')); fig.savefig(OUT/(name+'.png'),dpi=220); plt.close(fig)

if __name__ == '__main__': main()
