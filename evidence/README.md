# 证据索引

以下 JSON 是实际执行后的公开摘要，保留配置、源码和原始产物哈希。`passed`、`status` 和限制字段共同定义结论；文件存在不表示通过。原始构建、权重、波形和专有工艺文件不在 Git 中，复现入口见项目 [README](../README.md)。

| 证据 | 验证对象 | 不能据此推出 |
|---|---|---|
| [核心回归](core/validation.json) | FP4 分组算术、FP32 舍入、带符号多头归约和稳定 Top-K；包含完整 H32/Top-512 与错误输入 | 完整模型质量、系统延迟 |
| [并行度对照](core/lane_sweep.json) | 同一输入及握手调度下 8/16/32 路核心的实际周期分解 | 三种电路达到相同物理频率或面积 |
| [ASIC 核心综合](core/synthesis.json) | 固定工艺角与约束下的映射、面积字段、setup/hold；保存设计独立读回 | wrapper/DMA 面积、门级等价、布局布线或物理签核 |
| [面积单位交叉核查](core/area_units.json) | Liberty、LEF 尺寸、发布包版本关系与实际 DC 数据库的单元面积对应 | 布局后的 core/die 面积或物理签核 |
| [wrapper 回归](sparse_gate/wrapper.json) | AXI 背压、通道保持、顺序、错误、版本检查与每字节 gather | 在线 UCIe/mem_sim 已通过 |
| [独立 wrapper 审阅](review/wrapper.json) | 另一组完整 Top-512、REUSE、最后写响应、候选读取和配置负例 | 替代原生系统回归 |
| [独立 DMA 审阅](review/dma.json) | RID/BID/RLAST 等错误排空及恢复 | 任意 AXI4 设备的通用互操作性 |
| [算法与输入](research/summary.json) | 固定官方源码/权重切片、独立 oracle、真实权重加随机激活、数值差异与 ties | 文本推理、困惑度或官方 CUDA 逐 bit 等价 |
| [大例 C 输入](research/top512_header.json) | 完整 H32/N640/K512 头文件与研究 fixture 的字节一致性 | 单独证明硬件执行正确 |
| [在线统一系统](system/summary.json) | 原系统回归、实际 RTL 门控、CPU 输出核对、协议/波形证据、慢内存反馈、输入/源码/二进制一致性 | 全芯片 RTL、硬件缓存一致性、未测量的 GPU/NPU 同时争用 |
| [真实完成波形](system/completion_window.json) | 从已核查原生 VCD 导出的最后 DMA B、DONE 和状态响应窗口 | 硅片示波结果 |
| [原仓库撤回](cleanup.json) | 旧交付、Release/tag 和本次创建分支的撤回范围与保留基线 | 删除用户原有分支或历史 |

综合文件将**映射完成**、**时序满足约束**与**电气设计规则**分开记录；`mapping_passed=true` 不能覆盖负 slack 或电气规则违例。系统汇总要求完整 Top-512 回执以及基线、错误/恢复、内存反馈等检查，局部 PASS 不会提升为总 PASS。

面积单位核查入口是 `python3 scripts/check_library_area_units.py --help`。它读取本地授权的 Liberty、LEF、发布说明和数据库读回 TSV，精确比较逻辑/物理面积，再按显式容差核对数据库数值；公开摘要只保留统计与输入哈希。仅有 Liberty/LEF 对应、尚未关联实际 DC 数据库时，总状态仍为未完成。

论文数值由 [prepare.py](../paper/prepare.py) 从上述摘要导入，正式构建拒绝缺少必需证据。[delivery.json](../paper/delivery.json) 记录最终 PDF 和论文源文件哈希。四张概念图与实际测量图分别保留来源，概念图不作为实验数据。
