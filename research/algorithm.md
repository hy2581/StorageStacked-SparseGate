# 新数字 IC 项目的算法选型与硬件合同

核查日期：2026-09-22。本文是重新选题的独立调研，不沿用上一轮系统调度方案、指标或结论；新实作位于独立仓库。已通过 HTTP Range 下载五个真实 layer20 indexer 张量（5707008 B），并完成独立有理数/IEEE 算术检查；硬件与系统验证以新仓 `results/` 的源绑定报告为准，不由本文的调研论证替代。没有下载或运行完整 552B 模型。

## 1. 推荐结论

**正式唯一主目标：DeepSeek-V4.1-Flash CSA2 索引/选择硬件（2026-09 发布），通过原生 AXI256→AXI2Flit→UCIe→在线 mem_sim 完成实际数据闭环。** 核心实现 FP4 分组点积、多索引头加权 ReLU 归约、Top-512、外部候选 ID 范围的真实读取和选中主 KV 的字节 gather。候选块产生、投影与最终 attention 仍由外部软件/处理器负责；不要求下载或运行完整 552B 模型。

SeerAttention-R 和 NSA 是选型对照，不作为主算法退路。SeerAttention-R 的小模型完整验证更容易，但本项目明确优先最新算法与电路工作；对 CSA2 的验收边界是公开格式和公式兼容、真实训练权重的小规模算子验证、原生系统闭环。真实权重与随机输入组合不等于真实整模型激活，也不据此声称模型质量。

| 候选 | 日期与公开性 | 门控计算及访问粒度 | 对现有 BF16 门控电路的距离 | 首个完整系统风险 |
|---|---|---|---|---|
| **DSA 系列：V3.2，更新至 CSA2** | V3.2 报告 2025-12-02；CSA2 报告 2026-09-17；官方权重、config、参考代码均可读 | 多索引头加权 ReLU 点积、token Top-K；CSA2 增加压缩/跨层源/分层候选 | 高：FP8/FP4 格式、缩放、多头归约、大 K、稀疏 gather 都须重做 | 官方完整模型很大；随意 INT8 替换改变排序；算术可能比存储更慢 |
| **SeerAttention-R** | 2025-06-10；官方 Qwen3-4B/8B gate 与原模型可组合 | 学习式 GQA 查询合并、max/min/avg K 压缩、每 KV head 块 Top-K | 中：BF16 可复用，但维度、池化/归一化/投影、Top-K 和存储接口需扩展 | 可做整模型；必须核对代码与论文位置编码差异，CPU/GPU 算子依赖需移植 |
| **NSA** | v1 2025-02-16，v2 2025-02-27；定义充分 | 压缩注意力概率→跨块/跨头聚合→Top-n，另有局部与压缩分支 | 高：不只是一个门控点积，需完整三分支语义 | 本轮未核验到论文作者发布的对应预训练权重；第三方实现不等于官方模型 |

来源：[V3.2 原始报告](https://arxiv.org/abs/2512.02556)、[CSA2 原始报告](https://arxiv.org/abs/2609.19969)、[SeerAttention-R 原始报告](https://arxiv.org/abs/2506.08889)、[NSA v2](https://arxiv.org/abs/2502.11089v2)。选型标准是可验证的硬件工作量与系统闭合，不是重新包装已有稀疏注意力为新算法。

## 2. 候选一：DSA 的精确实现目标及最新变化

### 2.1 V3.2 Lightning Indexer

原始定义（报告 §2.1，式 1–2）：

\[
I_{t,s}=\sum_{j=1}^{H_I}w^I_{t,j}\operatorname{ReLU}
  \left((q^I_{t,j})^T k^I_s\right),\qquad
\mathcal S_t=\operatorname{TopK}_{s\le t} I_{t,s}.
\]

主 attention 只取 \(\mathcal S_t\) 对应的 MLA KV latent；不是精确 dense attention。权重 \(w\) 是学习出来的实数，源码没有非负约束。**不能将其改成先跨 head 求和再 ReLU，也不能把 K 换为普通 KV 的均值。** Prefill 对每个 query 加因果掩码，indexer 仍有二次复杂度；decode 扫历史 index K，每步线性。主 attention 的稀疏化不等于 indexer 不扫描全历史。[原始定义](https://arxiv.org/html/2512.02556v1#S2.SS1)

已核实官方配置：61 层，index \(H_I=64,d_I=128,K=2048\)；主 MLA latent rank=512、独立 RoPE 维=64。索引缓存是共享单 K 的 `[batch, history, 128]`，查询 `[batch, query_length, 64,128]`，head 权重 `[batch,query_length,64]`；不是 64 份历史 K。官方 checkpoint 是 671B 级模型，本轮未核实本地有完整推理资源。[官方 config](https://github.com/deepseek-ai/DeepSeek-V3.2-Exp/blob/87e509a2e5a100d221c97df52c6e8be7835f0057/inference/config_671B_v3.2.json)

参考实现合同：索引 Q/K 先各自投影，K 做 LayerNorm，前 64 维用 **non-interleaved RoPE**，再做归一化 Hadamard 旋转，之后量化成 E4M3FN。每 128 维一组 scale；`scale_fmt="ue8m0"` 使 scale 为 2 的幂，但演示缓存以 FP32 承载 scale。Q scale 与 head 权重、\(1/\sqrt{128}\)、\(1/\sqrt{64}\) 合并；FP8 点积使用 FP32 中间结果，逐 head ReLU 和加权归约，最后乘 K scale。`k_cache` 是真正 FP8 tensor。[Indexer 源码](https://github.com/deepseek-ai/DeepSeek-V3.2-Exp/blob/87e509a2e5a100d221c97df52c6e8be7835f0057/inference/model.py#L401)、[量化及 fp8_index 核](https://github.com/deepseek-ai/DeepSeek-V3.2-Exp/blob/87e509a2e5a100d221c97df52c6e8be7835f0057/inference/kernel.py)

必须使用修复后的参考：官方 README 记录 2025-11-17 修复 indexer 与 MLA 的 RoPE 布局混用。当前核查 commit 为 `87e509a2e5a100d221c97df52c6e8be7835f0057`，提交时间 2025-11-18。优化 GPU 对照另有作者的 [DeepGEMM](https://github.com/deepseek-ai/DeepGEMM) index-logit/paged kernel 与 [FlashMLA](https://github.com/deepseek-ai/FlashMLA) sparse attention kernel，不能拿 Python 演示实现的低效率代表已有最优实现。[官方更新与实现入口](https://github.com/deepseek-ai/DeepSeek-V3.2-Exp)

**数字硬件含义（设计推导，不是测量）**：单 query 在 N=32768 时仅 index 点积就有 \(64\times128\times32768=268435456\) 次乘加。按 128 MAC/cycle 的理想阵列也要 2097152 cycles，尚未计缩放、归约、Top-K 和链路。因此“小索引网络”不等于小 RTL；用少量 MAC 加一个门控控制器，很可能没有系统收益。历史 index K 的最低 payload 是 \(N(128+4)\) B（按演示 FP32 scale），另有 query/weight、主 KV 和更新流量。

### 2.2 2026 更新：V4 与 V4.1 CSA2 不能忽略

V4 官方发布日是 2026-04-24，采用 CSA/HCA 与滑窗；CSA 对压缩表示继续做索引。V4.1-Flash 官方发布日 2026-09-10，原始报告于 2026-09-17 提交。CSA2 分别规定 Full、Reindex、Reuse 模式：缓存源、索引源和最终选择可以跨层复用；后续 Reindex 只在源层给出的候选池中重评分。[V4 官方公告](https://deepseek.com/en/news/v4-preview/)、[V4 报告](https://arxiv.org/html/2606.19348v1)、[V4.1 官方公告](https://deepseek.com/en/news/deepseek-v4-1-flash/)、[CSA2 §2.3](https://arxiv.org/html/2609.19969v1)

V4.1 已公开 config 的关键数值：index \(H_I=32,d_I=128,K=512\)，候选块宽 8、最多 2048 个块，即最多 16384 候选位置；滑窗 128；main head_dim=512；KV source 层 `[2,8,14,20]`，index source 层 `[2,8,14,20,24,28,32,36]`，candidate source 层 20。不要把这些层角色替换为所有层都运行一个全扫描引擎。[官方 config，固定 revision](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/dba1be0a40aa45a94ad051997016db3960a90277/config.json)

索引 score 仍是多头 weighted-ReLU dot；Q/K 使用 E2M1 FP4，每 32 维一个 E8M0 scale。主 compressed KV 另用每 16 维一个 E4M3 scale，不能共用格式假设。硬件若自行紧密打包，128 维 index entry 是 64 B 数值+4 B scale；512 维 main KV 是 256 B 数值+32 B scale，均为**逻辑载荷推导**，实际 AXI 事务需加对齐、元数据和尾拍。[官方量化核](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/dba1be0a40aa45a94ad051997016db3960a90277/inference/kernel.py)

重要实现边界：参考 `model.py` 的 `fp4_act_quant(..., inplace=True)` 将量化后反量化的数值写回 BF16 存储；其 `Indexer.forward` 先计算完整 `einsum` 再按 candidate mask 屏蔽。它明确算法和数值目标，但不能把该演示 tensor 大小或 mask 行为当成生产内核实际压缩存储/物理跳读。Top-K 后还按位置排序；候选层对每 8 个位置取最大分数选块，最新部分块强制保留。实现时要对齐这些边界。[官方模型 Indexer/Compressor/Attention](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/dba1be0a40aa45a94ad051997016db3960a90277/inference/model.py)

FP4 不是 INT4。E2M1 可用小查表/移位乘积实现，但不同组 scale 必须在归约前对齐；跨组、跨 head 的舍入次序会影响第 K 名附近排序。首版应以官方量化后值的算子输出和 Top-K 集合为合同，记录并列处理，不能未经验证承诺 bit-exact CUDA。

### 2.3 已有工作的重合风险

LongCat LSA（2026-08-03）已提出 streaming-aware 连续访存、跨层 index reuse、粗到细 hierarchical indexing；CSA2 更已把分层候选与跨层 KV/index reuse 放进真实模型。因而“把索引分两级”“跨层共用候选”“把选中的 KV 排成连续访问”都不能独立作为新算法贡献。官方 GPU kernel 同样已有 paged、低精度与稀疏 gather 优化。[LongCat 原始报告](https://arxiv.org/abs/2608.01662)、[LongCat 算法正文](https://arxiv.org/html/2608.01662v1)

可以研究的是**具体数字实现**：物理 FP4/FP8 缓存格式、有限 SRAM 下的多头共享读与缩放流水、全范围/候选范围共用扫描器、较大 Top-K 的吞吐/面积、跨源层缓存所有权、以及在在线 AXI/UCIe/backpressure 下的实际收益。当前检索不足以证明这些组合全球首创，必须先实现、再作硬件文献比较。

## 3. 候选二：SeerAttention-R 的可落地合同

### 3.1 算法、真实模型与缓存

将同一 GQA 组的 pre-RoPE query 拼接，学习式投影到单个 gate query；对每个 KV head 的非重叠块做 max/min/avg pooling，拼接后投影为 gate key，再使用位置编码：

\[
q^g_{t,h}=R_t\,N_q\!\left(W^q_h\operatorname{concat}_{j\in G_h}q^{nope}_{t,j}\right),
\]
\[
k^g_{b,h}=R_{p_b}\,N_k\!\left(W^k_h[
\max_{s\in b}k^{nope}_{s,h};\min_{s\in b}k^{nope}_{s,h};
\operatorname{mean}_{s\in b}k^{nope}_{s,h}]\right).
\]

\(N_q,N_k\) 是本次 checkpoint 配置开启的 RMSNorm；论文抽象式没有展开这两个算子。Gate 分数为 \((q^g)^Tk^g/\sqrt{d_g}\)。固定 token budget 模式按块 Top-K 选择，严格单调的 softmax 在实数排序上可省；threshold 模式则不能直接省 softmax。最新块强制保留，是补偿未封闭压缩块的算法语义。[论文式 1 与 §3](https://arxiv.org/html/2506.08889v1)、[官方 gate 实现](https://github.com/microsoft/SeerAttention/blob/aba03e3f2caefd0ccd21e576670aa830b748c84e/seer_attn/decode_sparse/attn_gate_inf.py)

本次直接 GET 核实 Qwen3-4B gate config：36 层、Q heads=32、KV heads=8、head_dim=128、gate_dim=128、block=64，`Qproj`、`Kmaxminavg`、`use_qk_norm=true`、`use_rope=true`、BF16。官方适配权重约 66.1 MB，仅含 gate，必须同时加载 Qwen/Qwen3-4B；不是一个独立 66 MB LLM。[官方模型文件](https://huggingface.co/SeerAttention/SeerAttention-Decode-Qwen3-4B-AttnGates/tree/d29752cb96b675b0072d6c13baa2a0dad8365783)、[固定配置](https://huggingface.co/SeerAttention/SeerAttention-Decode-Qwen3-4B-AttnGates/blob/d29752cb96b675b0072d6c13baa2a0dad8365783/config.json)

参考 tensor：query `[B,1,32,128]`→gate query `[B,1,8,128]`；压缩 K `[B,ceil(N/64),8,128]`，主 K/V 为各自 `[B,N,8,128]`；mask/indices 按 KV head 输出，组内四个 query head 共用选择。完整块摘要只在块封闭时更新；不完整块保留 remainder，不能将 padding 的 0 纳入 max/min/mean。Prefill 运行 dense attention 并建立 gate cache；该 decode 模型不等于同时实现稀疏 prefill。[cache 源码](https://github.com/microsoft/SeerAttention/blob/aba03e3f2caefd0ccd21e576670aa830b748c84e/seer_attn/decode_sparse/cache_utils.py)、[Qwen3 接入](https://github.com/microsoft/SeerAttention/blob/aba03e3f2caefd0ccd21e576670aa830b748c84e/seer_attn/decode_sparse/qwen3/modeling_qwen3_seerattn_inference.py)

参考源码位置：`seer_attn/decode_sparse/attn_gate_inf.py`、`cache_utils.py`、`qwen3/modeling_qwen3_seerattn_inference.py`；选择后 attention kernel 位于 `seer_attn/kernels/varlen/tilelang_sparse_gqa_decode_varlen_indice.py`，另有 Triton 版本。官方仓库当前核查 commit `aba03e3f2caefd0ccd21e576670aa830b748c84e`（2025-07-03）。[官方仓库](https://github.com/microsoft/SeerAttention/tree/aba03e3f2caefd0ccd21e576670aa830b748c84e)

### 3.2 开始 RTL 前必须澄清的参考细节

1. **位置编码不一致候选**：论文称压缩块用首 token 位置；prefill 源码用 `position_ids[:,0::block]`，但 decode 块封闭时 gate 源码使用传入的当前 query 位置编码。应写 B−1/B/B+1 边界对比，确认实际模型输出，再明确使用哪一合同；不能悄悄修一边后宣称复现官方所有行为。
2. 官方 Python gate 即使 token-budget 模式也调用 softmax；论文允许排序前省掉它。有限 BF16 softmax 可制造原 logits 没有的并列，省略后应验证 mask，而不是只用单调性口头证明完全一致。
3. `mask[..., -1]=True` 在 Top-K 后执行，最终块数可能超过 budget 对应的 K；末尾块若已选中则不增加。不得把强制块从预算中偷偷扣掉以获得更高稀疏率。
4. 前若干层 dense 的开关、padding mask、batch 长度和 remainder 长度均属于模型配置，不能只取最有利的层。论文有前两层 dense 的消融，具体运行需要绑定参数。

这些是直接读 [gate 源码](https://github.com/microsoft/SeerAttention/blob/aba03e3f2caefd0ccd21e576670aa830b748c84e/seer_attn/decode_sparse/attn_gate_inf.py) 与 [接入代码](https://github.com/microsoft/SeerAttention/blob/aba03e3f2caefd0ccd21e576670aa830b748c84e/seer_attn/decode_sparse/qwen3/modeling_qwen3_seerattn_inference.py) 得到的审计任务，尚未运行验证。

### 3.3 对原门控的真正修改空间

建议首版保持 BF16 输入、明确 FP32 累积合同，不立即另造 INT8 量化算法。把旧固定短向量/小 Top-K 电路改为：128 维分片点积、每 KV head 独立可配置 Top-K、完整/未封闭块版本管理、按所选块真实发起 KV 读、输出完整 bytes 到计算端。BF16 运算、存储宏、排序器和命令链都应实际综合验证。

池化和“每满 B token 更新一次摘要”、GQA 共用掩码已是原算法，不能算新意。硬件贡献应落在例如：**KV 写入旁路驱动的完整摘要形成与提交电路，门控算术和选中块 gather 共享有限 SRAM/事务窗口，在 AXI/UCIe 反压下保持正确性与可测吞吐。** Gate projection/Norm/RoPE 若暂在 CPU/NPU 上，必须作为明确前处理列账；最终不能只交付接受预生成分数的比较器。

数字推导示例：N=32768、B=64、8 KV heads、D=128 时，每层 BF16 gate cache 为 1 MiB，完整 BF16 KV 为 128 MiB，单步 gate 点积为 524288 MAC；这些都不是性能测量。预算 4096 token 意味着每 head 至少按 64 块做选择，再按实际末尾必选规则计流量。对照必须包含**已有软件 SeerAttention-R 且小 gate cache 常驻计算侧**的方案，不能假设基线每步都跨 UCIe 搬回全部摘要来制造收益。

## 4. 候选三：NSA 不能缩写成“均值门控”

NSA 同时计算 compressed、selected、sliding-window 三个注意力输出，并由学习 gate 混合：
\[
o_t=\sum_{c\in\{cmp,slc,win\}}g_t^c\operatorname{Attn}(q_t,K^c_t,V^c_t).
\]
压缩 token 来自带块内位置编码的可学习 MLP。先得到压缩 attention 的 softmax 概率；按压缩块与选择块的重叠关系求和，再将同一 GQA 组的 head 概率相加，选 Top-n 块。**跨 head 的归一化不同，不能一般性地直接用未归一化 logits 的和代替概率和。** [NSA §3，式 5–12](https://arxiv.org/html/2502.11089v2)

论文配置 l=32、stride=16、selection block=64、n=16（含一个初始块和两个局部块）、window=512。因此缓存包含三条分支需要的表示；不仅有 selection 所用原始 K/V。Prefill 和 decode 都支持稀疏，但 decode 压缩分支还要随历史长度扫描压缩 token。原文没有给出可直接沿用的 INT8/FP4 排序合同。[NSA v2](https://arxiv.org/abs/2502.11089v2)

本轮未查到能确认与论文训练实验同源的 DeepSeek 官方 NSA 小模型 checkpoint。可读参考有 FLA 的 `native_sparse_attention/modeling_nsa.py`，核查 commit `bd67af59b90afa34b25f61d2922e612d10dba3bd`（2025-03-19）；这必须标为第三方实现，不能冠为官方已训练模型。[FLA 实现](https://github.com/fla-org/native-sparse-attention/tree/bd67af59b90afa34b25f61d2922e612d10dba3bd)

NSA 的优势是块规整，缺点是以当前目标衡量，真正实现三分支、学习压缩与概率聚合的工程量大，模型级验证来源更弱。只抽走其 block Top-K 算子会失去完整算法语义，因此不作为首选。

## 5. 正式 CSA2 算子边界与实施合同

### 5.1 首版必须做什么

输入为已投影、RMSNorm、RoPE、FP4 量化的 Q/K 与有符号 BF16 head weights；前处理由外部软件/处理器负责，性能比较须另列成本。RTL 接受 packed E2M1、每 32 维 E8M0 scale，执行提交范围内的 score、选择和真实存储读取。支持官方 32 heads×128 dimensions、Top-512；缩小 H 或 K 的定向算术测试标为参数化测试，不能代替完整规格覆盖。

三个硬件命令不是完整 CSA2 跨层角色的替代：FULL 扫 caller 已准备的有效/因果历史范围；REINDEX 接受升序、唯一、范围内的展开位置 ID，用自己的 Q/weights 只读这些位置；REUSE 在严格 context/epoch/地址等合同匹配时复用已完成的选择。官方 candidate-source 每 8 位置取最大 score、Top-2048 块并强制最新块的操作在 `research/csa2_oracle.py:select_candidate_blocks` 提供 Python 参考，**当前 RTL 不产生该候选池**。投影、RMSNorm、RoPE、压缩、量化、候选生产与最终 sparse attention 均不在硬件核内；main-KV gather 只核字节复制，不代表已执行 attention。具体布局和错误合同见 `docs/sparse_gate/interface.md`。

官方 Torch 对并列项的 `topk` 不承诺固定 index 次序。本 oracle 的 source candidate 与最终 token Top-K 明确采用 score 相同优先较小位置；源池最新可见块具有最高优先级。该确定性扩展仅在并列处选取官方允许的集合，不能称与某个 CUDA kernel 逐 bit/逐 index 完全相同。

Prefill 还需区分原始 block mask 与物理可读 ID：官方 mask 会保留最新 partial block 内尚不可见的槽位，但它们已在 score 中被因果掩码设为负无穷。Python 外部 producer 显式再取 `position < visible` 的交集，防止真实 DMA 去读未来记录。decode 的 `N=visible` 情况无需额外裁剪。独立读回与官方完整候选函数比较的是该可见性交集，不宣称 prefill 原始 block bitmap 完全相同。

Vortex CP DMA 通过真实命令与 query payload 发起；RTL 从在线 mem_sim 的物理地址读 index K，经 MAC/排序后发起 selected main-KV gather，返回真正 bytes。完成时刻沿原链路返回，不以离线 trace 或 Python mask 替代电路结果。新的 index K 与主 KV 写入要受同一版本/可见长度约束。

### 5.2 确切数字格式与舍入（新硬件合同，不冒称 CUDA bit-exact）

E2M1 的低三位 0…7 对应绝对值 `{0,0.5,1,1.5,2,3,4,6}`，最高位是 sign，码 8 是负零；每字节先低 nibble 再高 nibble。E8M0 字节 `e=0…254` 表示 `2^(e-127)`，255 是 NaN，应报格式错误而非零 scale。依据 [OCP MX 1.0 标准](https://www.opencompute.org/documents/ocp-microscaling-formats-mx-v1-0-spec-final-pdf)。该标准并不是本文创新。

令整数 `m=2*E2M1_value`，每 32 维组精确累加 `d=sum(mq*mk)`，范围为 ±4608。四组按 `g=0,1,2,3` 顺序计算：

`group_fp32 = RNE_FP32(d * 2^(eq+ek-256))`

随后按组顺序用 FP32 RNE 累加完整 128 维 dot；**ReLU 在四组全部归约后执行**；乘该 head 的 BF16 weight（精确扩展为 FP32）并 RNE；最后按 head0→31 的显式 FP32 RNE 顺序归约。结果按 score 降序、index 升序稳定 Top-K，输出另有 position 顺序供 gather。

保留 IEEE subnormal，不做 FTZ；±0 排序相等。BF16 weight 的 NaN/Inf、E8M0 255 报 FORMAT_ERROR；任何有限输入中间运算溢出为 Inf 报 ARITHMETIC_ERROR，错误任务不得出成功 Top-K。head weights 保持 BF16 符号与完整有限编码，不能无声明地压为定点。官方 torch 演示的 einsum/乘法/归约有其 dtype 和 kernel 次序，这里只承诺上述可复现电路数值合同，另报相对官方算子的误差与 Top-K 差异。

### 5.3 真实权重的有限抽取已核可行

已读固定 revision 的 `model.safetensors.index.json`（约 7.5 MB），layer20 indexer 的五个张量同在 `model-00023-of-00048.safetensors`。HTTP Range 已实际返回 206，文件总长 7400713088 B、header 261280 B；仅需读取如下五个数据区，而非 7.4 GB 分片：

| tensor 后缀 | shape / dtype | 数据字节 |
|---|---|---:|
| k_norm.weight | [128] BF16 | 256 |
| weights_proj.weight | [32,5120] BF16 | 327680 |
| wk.weight | [128,512] BF16 | 131072 |
| wq_b.scale | [128,40] F8_E8M0 | 5120 |
| wq_b.weight | [4096,1280] F8_E4M3 | 5242880 |

合计 5707008 B。加载这些真实训练张量，可由明确标注的随机 `x[5120]、qr[1280]、latent[N,512]` 生成实际学习投影驱动的 Q/K/weights，再量化并进入 RTL。这证明权重、格式、数值、访存链路工作；随机中间激活不来自全模型 forward，不能报告为 DeepSeek 的真实语言模型 trace 或质量验证。[官方权重索引](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash/blob/dba1be0a40aa45a94ad051997016db3960a90277/model.safetensors.index.json)

### 5.4 验收与公平比较

先做完整全零并列、负权重、跨组抵消、subnormal/下溢零、极端 scale/溢出错误、causal tail、稀疏候选；独立 Python oracle 不借用 RTL helpers。再使用真实权重投影输入，报告逐 score 和 Top-K；Torch 比较允许记录差异，但不能把不一致写为 bit-exact。

系统至少包括 index scan、query、scale、weights、Top-K、selected-KV、更新、协议元数据的全部周期与字节。最强对照是相同 CSA2 算法的软件/处理器索引后经同一链路 gather，不把 dense→sparse 的已有算法收益当成硬件贡献。必须包含计算侧常驻索引缓存的基线，避免制造每步跨链路搬全量 index K 的稻草人。

硬件贡献只讨论实做后的 FP4 缩放/归约流水、有限 SRAM 的多头共享读、可配置大 K 排序器、候选地址读与实际事务反馈；跨层/分层算法本身已有。是否称存算一体取决于真实宏接口与验证，数字标准单元 MAC 放在 Logic Die 只称近存计算。综合面积与时序覆盖真实算术核和系统接口，不用小型协议核替代整套数据通路。

## 6. 可复查版本与尚未完成项

本轮通过官方 GitHub/Hugging Face API 实时核验的 revision：

| 对象 | revision |
|---|---|
| DeepSeek-V3.2-Exp inference | `87e509a2e5a100d221c97df52c6e8be7835f0057` |
| DeepSeek-V4.1-Flash | `dba1be0a40aa45a94ad051997016db3960a90277` |
| Microsoft SeerAttention | `aba03e3f2caefd0ccd21e576670aa830b748c84e` |
| SeerAttention Qwen3-4B gate | `d29752cb96b675b0072d6c13baa2a0dad8365783` |
| Qwen/Qwen3-4B base | `1cfa9a7208912126459214e8b04321603b3df60c` |
| FLA NSA 第三方参考 | `bd67af59b90afa34b25f61d2922e612d10dba3bd` |
| DeepGEMM 当日 main | `78b69000794d0937b47ae3387eff7663410264d1` |
| FlashMLA 当日 main | `ba89a3466e9470ad08ab39738d4e7bb66989e1e7` |

本文锁定算法归因与算子合同；当前已有真实权重切片、独立算术 oracle 和 fixture producer。RTL/系统/PPA 完成程度以各自源绑定实测报告为准，本文不外推其状态；没有证明新硬件比已有最优 GPU kernel 更快，也没有完成完整模型运行或新颖性穷尽检索。尤其不能把已有 Top-K、共享 K、压缩缓存、分层索引和低精度自身写成我们的新贡献。
