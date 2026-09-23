# Vortex 到在线 SparseGate 的协议适配

`configs/run_vortex.py` 建立 gem5 SE 宿主、Vortex SimX 设备、AXI256/AXI2Flit/UCIe
链路、SparseGate RTL 模型与在线 mem_sim。宿主进程配置 Vortex 命令处理器；
门控请求由其 DMA 主设备通过 Vortex BAR 发出。

`aou_backend.cc` 在存储侧把保留的门控寄存器窗口送到 RTL，从 RTL DMA 发出的
索引读取、KV 聚集和结果写回访问同一个在线存储。`scripts/inspect_link.py`、
`scripts/check_aou.py`、`scripts/check_vortex_gate.py` 分别核对链路、AXI 映射和
Vortex 门控回执。运行入口为 `env/run_vortex_gate.sh`。
