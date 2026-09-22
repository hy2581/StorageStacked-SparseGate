# 在线系统中的 SparseGate 适配层

`gem5_axi/sparse_gate_backend.cc` 位于 AouTarget 的整笔请求/响应 FIFO 与
MemSimBackend 之间。它把保留页的访问转成 `sparse_gate_axi` 的真实 AXI256
从端握手，把该 RTL 主端的 DMA 转回同一个 MemSimBackend 的请求。普通访问仍
由原 mem_sim 执行。适配层没有评分函数、私有数据镜像或替代 RTL 的软件结果。

## 时间与有界状态

适配层只使用已有 `aclk`。下降沿准备从端请求和 DMA 返回值，再调用 Verilator
`eval(clk=0)`；上升沿记录此前稳定的握手信号并调用 `eval(clk=1)`，之后更新
FIFO/队列状态。每次调用都断言 SystemC 时间等于 gem5 `curTick()`。动态库只
包含 Verilator C++ 模型，不链接 SystemC，也不推进独立仿真时间。输出波形
使用 `1fs` 时间单位，验证器以**上升沿之前**的信号恢复全部十组通道握手。

主机输入、RAM 等待、MMIO 等待和返回队列各至多 8 笔；MMIO 同时转换一笔
整突发。DMA 地址和写数据独立锁存，遵守单个 32 B INCR 传输、ID 1、一个未完成
请求的 RTL 合同。RAM 和 DMA 在共享内存入口轮转仲裁。内部最多 32 个返回标签，
标签与原 host ID 分离；返回时恢复原 plane、ID 和方向。每个 host
`(方向, plane, ID)` 只准入一笔，避免后来的寄存器响应超过同组较早 RAM 请求。
这不是跨 ID 的内存栅栏；数据依赖仍由上游等待完成和软件 epoch 协议保证。
不支持独占访问：MMIO `AxLOCK != 0` 与原 MemSimBackend 一样返回 SLVERR，
读突发返回规定数量的错误 beat，整笔写已由 AouTarget 收集；不向 RTL 发起
请求，因而锁定的 START/MODE 写不能产生副作用。普通 RAM 的 lock 仍交给原
MemSimBackend 检查。独立适配层测试直接编译实际后端并加载实际 RTL DLL，
使用明确标注的测试时钟 shim；它与生产 gem5 验收分开记录。

地址/写入数据进入内存后必须等待真实 mem_sim 完成。DMA R/B 在 RTL 接收前保持
有效和数据稳定。DONE 的算子语义由 RTL 和 guest 检查；适配层的 `drained` 只表示
它自身、请求标签和 FIFO 已清空，不单独代表算子正确性。

## 构建、工作负载与验收

`env/build_sparse_gate.sh` 构建动态库，检查 RTL、ABI、shim 的构建前后 SHA256，
记录工具版本和 DLL build ID。构建完成字段 `BUILT_NOT_VALIDATED` 只表示库构建
完成。`sparse_gate_abi_smoke.cpp` 单独检查 ABI 边界的 lane/WSTRB、AW/W 顺序、
响应背压、多拍错误读取及恢复；它不替代统一系统验收。

`env/run_sparse_gate.sh NEW_RESULT_DIRECTORY cpu` 运行两套实际 CPU 程序：
闭式小输入和真实训练权重加随机激活输入。两者执行 FULL、输出地址改变的 REUSE、
REINDEX、过期 REUSE 拒绝、FULL 恢复；检查选中 ID、FP32 分数位、288 B KV
逐字节值和各模式的 DMA/score 计数。`three` 模式先完成已有 GPU/NPU 计算，再执行
同一个门控 client，证明同一系统配置中共存；**该用例不声称门控与 GPU/NPU
流量在时间上重叠**。

`cpu-slow` 模式用同一 learned-weight 程序把在线 mem_sim 周期放大四倍，单独记录
每条命令的周期及 host 完成时间。对照要求输入/可执行文件/RTL 相同，分数与 DMA
数量不变；成功命令的延迟须实际增加。轮询次数可能改变，因此不把 host 指令数
视作固定，也不要求 host 延迟等于所有 DMA 延迟之和。

`top512` 是独立的 H32/N640/K512 规模验证，仅执行 FULL 和 REUSE。它使用
独立 buffer 布局、逐项检查 512 个 index/FP32 分数/padding 和两份各
147456 B 的 gather 输出，不扩大为完整模型或 REINDEX 的同规模验证。

`check_sparse_gate.py` 连接 host AXI 与独立解码的 UCIe 路径、MMIO 引脚、DMA
引脚、重映射内存标签、native RD/WR、DFI、内存读返回和最终镜像。它还核对真实
guest 的结果检查记录、源输入锁及模型哈希。失败时删除旧的正向回执。
验证器还从 wrapper 层 VCD 独立提取每次 busy 上升/下降，检查其间隔等于
实际 cycles 寄存器，并逐任务计数 DMA 地址和响应。成功 DONE 必须晚于该
任务最后一个 DMA BRESP 且无未完成 DMA。STATUS 数据在 S_AR 握手时采样，
验证器按该时刻的 busy/done/error 状态检查，而非误用后续 S_R 握手时刻。
`env/collect_sparse_gate_system.py` 默认要求 native 19 项、原 CPU/tester 7 组、
原 XPU 4 组以及新增三组全部通过，才导出公开 `evidence/system/summary.json` 的
PASS；另在独立字段中要求门控内存时序对照通过。`--draft` 只能导出明确缺项的
INCOMPLETE 状态。
最终论文的验收默认必须包含大规模结果；`--gate-top512 RESULT_DIRECTORY`
仅用于指定它的运行目录，不能省略该验证项。四个门控 suite
使用各自目录中的 guest ELF，避免并行编译污染正在执行的输入。

这些入口必须在新仓库独立运行；旧目录或依赖缓存中的既往 PASS 不计入本次验收。
工具缓存可用 `env/run_sparsegate_stage.py --deps PREFIX STAGE -- COMMAND...`
显式指定，构建目录与 Bazel 输出仍留在当前独立仓库。
