# 证据索引

| 文件 | 已验证内容 | 范围 |
| --- | --- | --- |
| [`system/vortex_gate_cp.json`](system/vortex_gate_cp.json) | Vortex CP DMA 的请求来源、H4/N16/K4 FULL、RTL 完成和逐字节聚集输出 | 一条合成输入在线命令；GPU 核函数没有执行 |
| [`core/validation.json`](core/validation.json) | FP4、FP32、带符号多头归约和稳定 Top-K | 独立 RTL 核心，不是在线系统时延 |
| [`core/lane_sweep.json`](core/lane_sweep.json) | 8/16/32 路核心的实际周期 | 不表示相同面积或可达频率 |
| [`core/synthesis.json`](core/synthesis.json) | 固定工艺角下的核心综合与时序 | 未含 AXI/DMA，也未完成物理签核 |
| [`sparse_gate/wrapper.json`](sparse_gate/wrapper.json) | AXI 背压、错误和结果提交 | 独立封装测试 |
| [`research/summary.json`](research/summary.json) | 研究输入与独立数值参考 | 不代表完整模型推理质量 |

文件中的通过状态仅说明各自范围内的检查成功。论文在线系统结论只引用
Vortex CP DMA 用例；大规模 H32/N640/K512 是核心独立验证。
