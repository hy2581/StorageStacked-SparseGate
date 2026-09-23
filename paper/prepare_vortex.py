#!/usr/bin/env python3
"""Generate the Vortex-source result from its sealed, source-checked receipt."""
import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def need(ok,message):
    if not ok:raise RuntimeError(message)

receipt_path=ROOT/'evidence/system/vortex_gate_cp.json'
model_path=ROOT/'evidence/system/vortex_gate_model.json'
receipt=json.loads(receipt_path.read_text())
model=json.loads(model_path.read_text())
need(receipt['schema']=='vortex_gate_system_v1' and receipt['passed'],'Vortex system result absent')
need(receipt['checker_sha256']==sha(ROOT/'gem5_axi/scripts/check_vortex_gate.py'),'Vortex checker changed')
for name,digest in receipt['source_sha256'].items():
    need(sha(ROOT/name)==digest,'Vortex result source changed: '+name)
for name,digest in model['source_sha256'].items():
    need(sha(ROOT/name)==digest,'Vortex RTL source changed: '+name)
need(sha(model_path)==receipt['model_manifest_sha256'],'Vortex model receipt changed')
need(model['build_id']==receipt['model_build_id'] and
     model['library_sha256']==receipt['model_library_sha256'],'Vortex model identity differs')
need(model['parameters']=={'mem_base':0x190000000,'mem_bytes':0x100000,'reg_base':0x1900f0000},
     'Vortex address mapping differs')
cmd=receipt['rtl_command'];timing=receipt['vortex_timing']
need(receipt['vortex_mmio_requests']>0 and receipt['host_mmio_requests']==0 and
     cmd['mode']==0 and cmd['status']==2 and cmd['result_count']==4 and
     cmd['score_count']==16 and cmd['reads']==96 and cmd['writes']==40 and
     timing['core_cycles']==0 and timing['cp_reads']>0 and timing['cp_writes']>0,
     'Vortex source/result contract differs')
en=(
    f"In a separate Vortex command-processor run, {receipt['vortex_mmio_requests']} gate-register "
    f"requests appear in the Vortex source trace and none in the host source trace. "
    f"The H4/N16/K4 FULL command completes in {cmd['cycles']:,} RTL cycles with "
    f"{cmd['reads']} DMA read beats and {cmd['writes']} DMA write beats. The guest "
    "checks all four score/index records and all 1,152 gathered KV bytes. "
    "Host software configures the Vortex command processor, while Vortex CP DMA submits "
    "the AXI requests. No GPU core cycles execute in this case; GPU-kernel-initiated "
    "gate commands and concurrent contention remain untested. "
    "Earlier CPU-run measurements in this manuscript refer to their sealed prior source snapshot.\n"
)
zh=(
    f"在独立的 Vortex 命令处理器用例中，Vortex 源轨迹包含 {receipt['vortex_mmio_requests']} 笔门控寄存器请求，"
    f"主机源轨迹为 0 笔。H4/N16/K4 的 FULL 命令在 {cmd['cycles']} 个 RTL 周期后完成，"
    f"包含 {cmd['reads']} 个 DMA 读取数据拍和 {cmd['writes']} 个 DMA 写入数据拍。"
    "被测程序逐项核对 4 条分数／索引记录及全部 1152 B 聚集 KV 数据。"
    "主机软件配置 Vortex 命令处理器，AXI 请求由 Vortex 命令处理器 DMA 发出。"
    "本用例中 GPU 核函数执行周期为 0；核函数直接发起门控命令及并发争用仍未验证。"
    "本文此前的 CPU 用例测量对应各自封存的旧源码快照。\n"
)
for path,text in [(ROOT/'paper/generated/vortex_results.tex',en),
                  (ROOT/'paper/zh/generated/vortex_results.tex',zh)]:
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(text)
print(json.dumps({'receipt_sha256':sha(receipt_path),'model_manifest_sha256':sha(model_path),
                  'english_sha256':sha(ROOT/'paper/generated/vortex_results.tex'),
                  'chinese_sha256':sha(ROOT/'paper/zh/generated/vortex_results.tex')},indent=2))
