# 论文与发布材料独立审查（历史记录）

以下保留第一、第二轮审查当时的观察、问题与待验状态，不作为当前验收结论。问题修复及最新证据状态见 [独立发布审查](publication_review.md)；系统结果以 [最终汇总](../../evidence/system/summary.json) 为准，论文以 [交付清单](../../paper/delivery.json) 为准。

审查日期：2026-09-22。第一轮针对当前源码、证据摘要、`paper/main.tex`、`paper/prepare.py`、README、接口和重构文档。已看四张独立图及旧五页 preview；最终排版和 native/PPA 证据尚需增量复核。本次只读实现与证据，没有重新运行重型仿真、综合或修改发布状态。

## 第一轮时点结论

数值合同、RTL结构、原论文归属和新颖性边界总体相符。现有证据支持 post-projection 算子正确性、AXI/DMA 定向行为和 lane 数量的核心周期比较。它们不能替代 native 系统完成验收或物理实现证据。审查时 `evidence/system/summary.json` 为 `INCOMPLETE`，所有五组 native 结果尚未核验；`evidence/core/synthesis.json` 尚不存在。因此本轮不作最终论文/系统发布通过结论。

## 应修正的具体问题

1. **REUSE 流量公式的结果条数定义错误。** `paper/main.tex` 交通量段把 R 定义为 `min(K,N)`，仅对 REINDEX 改成 `min(K,C)`。若先 REINDEX 且 C<K，再 REUSE，实际复用结果数仍是 C。RTL `sparse_gate_axi.sv` 使用缓存 `result_count`，实现正确。建议定义 `R_full=min(K,N)`、`R_reindex=min(K,C)`、`R_reuse=R_committed`，或统一说明每个公式中的 R 是该命令实际输出条数。例：N=64/K=8/C=4/V=288 时，REUSE 是36个读beat、40个写beat，而非72/80。

2. **继承的维护文档仍指向原仓库。** `docs/development.md` 把主仓库写成 `git@github.com:fmq03/StorageStacked.git`，与新仓库 `AGENTS.md` 不允许向原仓库推送的边界冲突。改成独立仓库地址，旧迁移过程明确标成历史追溯。

3. **论文生成脚本仍未接入最终证据。** 当前 `prepare.py` 在 system 文件存在时无条件抛出异常，在 synthesis 文件存在时也无条件抛出异常。这是有意的 fail-closed 占位，但此时旧 preview 不能当最终可复现产物。接入 schema 后至少逐项验证 `passed/status`、源码锁、native 五组验收和综合的实际边界；未完成项不能从文件存在推导为 PASS。

4. **论文证据闭合范围不足。** 当前 generator 仅把 core、lane、原 wrapper 三份证据写入输入 manifest，正文的预训练tensor字节数、oracle验证规模、Torch误差仍为硬编码，review wrapper/DMA结果也不在生成依赖中。建议将 `evidence/research/summary.json`、`evidence/review/wrapper.json`、`evidence/review/dma.json` 纳入 manifest，并从 research 摘要生成有关数字。`if p.exists(): assert sha(...)` 会让缺失源码静默通过，应对已声明源码路径要求存在且哈希一致。对明确不分发的大权重或构建产物，应单独保留来源记录，不能套用源码忽略逻辑。

5. **当前完成时态需由最终 native 证据支撑。** 摘要“connect it … online memory simulator”、正文“live memory feedback”和 `thesis_redesign.md` 的“在线反馈”可描述已实现架构，但当前不能解释为已验收成果。最终 native 全通过后可保留；否则应在摘要或结果段直说集成未验证。三处理源共存用例在原 GPU/NPU 工作结束后运行 gate，不能描述成三者与 gate 并发争用实验。当前 evidence 已清楚写出此限制，论文应继承它。

6. **轻微图注歧义。** layout 图本身正确区分 index 的 E2M1/E8M0/group32 和 main KV 的 E2M1/E4M3/group16。正文图注中的“official E4M3/group16 format”建议改为“E2M1 payload with E4M3 scales per 16 values”，避免读者以为数据本身是E4M3。flow 图的 `ERROR; cache invalid` 应在 caption 限定为“accepted START command”；非法 doorbell/拒绝的 AXI 写会保留上一份 committed cache，接口文档已正确说明。

## 已现场核对的正向证据

- `core/validation`、`core/lane_sweep`、`sparse_gate/wrapper`、`review/wrapper`、`review/dma`、`research/summary` 声明的所有 `source_sha256` 路径在审查时存在且与当前源码一致，没有发现摘要与现存源码漂移。
- Core 摘要是42个case、4520个成功key score、13,557,824个实际执行乘积项、130,009个浮点helper案例。错误用例和成功用例的边界在正文中区分正确。不可把这些总数改述成完整模型token或系统请求数。
- E2M1乘2得到 `0,±1,±2,±3,±4,±6,±8,±12`；32项整数点积范围±4608；尺度指数 `eq+ek-256` 与RTL和oracle一致。ReLU在完整head dot之后、有符号head加权之前，未错误假设权重非负。
- Q有效载荷32×70=2240 B，完整物理Q读取32×96=3072 B；K有效68 B、物理96 B；512个64bit heap pair是4096 B；wrapper另有4096 B结果cache。主KV示例288 B对应9个AXI256 beat；gather测试只是opaque pattern逐字节copy，不证明attention计算或真实模型KV质量。
- `H[4(32/L+2)+3]` 对H32、L8/16/32得到864/608/480周期每key。每个lane-sweep phase之和精确为608365/444525/362605。三者各执行2,621,440个乘积项；正文只报告周期比，不声称相同频率、PPA或线性扩展，边界正确。
- Core表的N640基线444514周期和lane-sweep的L16结果444525来自不同回归调用。保留不同数字可以，但不要把它们写成同一次测量；lane图caption已指出它属于同一sweep的相同handshake安排。
- 论文明确公开投影/压缩/候选块生成/最终attention不在RTL核内，真实预训练权重配独立高斯激活不是全文本隐藏状态；没有模型质量、完整LLM吞吐、能耗、硅片时钟或算法新颖性主张。
- 已现场核对原论文PDF SHA-256为 `f7a130aa333d57d1ba99cdb72782b1cd324c3d3e5317b63538dce95be16b5490`；原论文正文确有128 Block×32 Cell、每Cell32个BF16值、GQA四倍映射、每周期选一个winner、SRAM Cell综合黑盒、数字外围SMIC28综合和7nm归一化。256KiB物理payload及64KiB distinct summary是合理的结构推算，正文已明确不是新电路实测。
- 官方 [CSA2论文](https://arxiv.org/abs/2609.19969) 的标题和2026-09-17提交日期已独立在线确认。算子表达式、32head/128dim/Top512配置和候选block8读取自固定revision的本地官方源码，而非从模型名称推断。

## 图形与最终版排版

已查看独立 `system/core/layout/flow` PNG。数值标签清楚，FP4与scale区分正确，core箭头顺序与RTL一致。最新system图的主AXI/UCIe链已用双向箭头表达回程，修复了旧preview绕过UCIe的返回连线；但旧五页PDF仍嵌入旧图，必须重编译。

旧preview中layout图只占单栏，字段小到不适合纸面阅读；源稿已计划改为fullwidth，应以最终PDF重新渲染检查。flow图内文字也比正文小，应检查最终打印尺寸是否达到可读水平。system图最左侧仍有一条多余的悬空竖线，与三设备左侧箭头相连；不影响已标明的真实协议主路径，但视觉上可被误认成另一条返回bus。若再次编辑图，可删除该悬空支路，保留三设备右侧经原协议链往返的连接。

最终应逐页确认：表不越栏、数学公式不截断、四张概念图使用当前文件、字体可读、无preview/待完成占位、引用可点击、作者信息与工程草稿身份一致。PDF可编译本身不等于图形正确或研究结论成立。

## native / PPA 到达后的增量复核范围

- native summary必须包含CPU baseline、XPU baseline、CPU synthetic、CPU learned-weight、三源coexistence的真实完成与readback；检查源码哈希、单时间轴、同一mem_sim镜像、回程链、DMA beats与公式、结果/Gather bytes及错误状态。将主机total时间、gate active cycles和存储完成时间分别命名。
- integrated cases如只有N64/K8，需明确这是系统验收规模；N640/K512是core验收，不能合并成“full-shape native系统已通过”。
- PPA读实际tool成功退出、映射状态、库/corner、时钟/IO/负载约束、寄存器/组合单元面积及未约束路径。若仅core综合，必须标core；AXI wrapper/DMA/C++适配器不应被计入其面积。没有时序收敛就不能用目标周期作已实现频率；无活动率来源就不能报告实测功耗/能量。
- 8/16/32lane只完成cycle sweep，不能用16lane综合面积与另外两种核心周期混合推导跨设计PPA优势。
- 最终paper生成manifest应冻结新证据与输出，并在独立仓库真实上传后才保留“are available”这一发布时态。

## 第二轮：在线适配器和数据守恒审查

范围为 `gem5_axi/sparse_gate_backend.hh/.cc`、`sparse_gate_model.cpp`、`sparse_gate_abi.h`、`scripts/check_sparse_gate.py`，并追到 `aou_backend.cc`、`memsim_backend.cc`、guest client和runner。只读静态审查；此结论不替代本次仍在运行的gate系统仿真。后续checker增强由另一审查者实施，本审查未并行改动checker。

第一轮的REUSE结果数定义、main-KV图注、accepted START错误分支、独立仓库维护地址已经在当前文件中确认修正。`prepare.py`现已把research及两个review摘要纳入输入，最终构建仍需等待新native/PPA证据。

### 计算和内存边界

没有发现C++替代RTL算分、Top-K或保存独立KV镜像。`sparse_gate_model.cpp`只把ABI引脚复制到 `Vsparse_gate_axi`，调用 `eval()`，复制输出并导出VCD。适配器保存的是待处理请求、AXI拍、response和tag，未实现注意力算术。`aou_backend.cc`在gate启用时只建立一个 `MemSimBackend`，普通旁路与DMA进入同一对FIFO；DMA读数取自其返回对象，B/R通道在native response到达后才有效。

`edge()`校验SystemC时间值等于gem5 `curTick()`；下降沿准备输入和组合输出，上升沿用上一稳定快照记录握手并推进RTL。ABI的VerilatedContext只被赋予同一个fs时间，未链接第二套SystemC或启动自己的时间推进循环。相同时间的多次eval不重复dump，后退时间会抛错。

内部tag与processor ID分离；response按ticket恢复原ID/user/plane。每个(direction, plane, ID) host组序列化，避免MMIO越过同组较早的旁路请求；内存响应检查方向、plane和读拍数。输入请求、写拍、背压响应都有有界队列，未知tag、重复DMA、提前MMIO响应或非单拍DMA会停止仿真。错误RRESP/BRESP沿通道送回RTL，没有在适配层改成成功。

### 已有数据校验链

guest把Q/K和确定性KV图案通过volatile远端访问写入，再发MMIO命令。`sg_verify()`逐个比较index和FP32 score、结果记录其余24B零填充，以及每个288B gather记录的所有字节。预期分数来自固定fixture，guest只作比较，不计算在线替代分数。

REUSE更换output/gather地址，防止把第一次命令已有输出当成新的输出。stale epoch必须返回ERROR2、cache invalid、0 score和0读写beat；随后FULL命令验证错误恢复。当前native fixture没有覆盖C<K后REUSE、非法doorbell保留cache、DMA错误注入等边界，这些分别由wrapper/review证据支持，不能混写为native覆盖。

离线checker将host AXI事件与UCIe往返路径、dispatcher事件和RTL VCD握手关联；逐native child核对提交/完成ID、地址、字节数、DRAM RD/WR、DFI数据/mask和完成时刻。它由观察到的写入重建逻辑镜像，并与所有返回数据及native最终image比较。因此checker中的Python字节字典是仿真之后的校验oracle，不是运行时供数路径。

### 发现的覆盖缺口与边界

1. **逐命令计时/完成需要额外交叉检查。** 审查开始时checker只要求guest打印的cycles>0，DMA计数主要按五条命令求总和；没有把每条START的busy区间、最后DMA BRESP和DONE独立配对。已向主代理和checker维护者报告。拟定的最小增强是从已有VCD读取wrapper内部busy/cycles/done/error/计数器：busy上升边沿置cycles=0，busy下降那一沿仍累加，因此 `(end_tick-start_tick)/AXI_period` 应精确等于命令cycles；成功任务最后M_B必须早于DONE，错误reuse段必须无DMA。host R响应中的寄存器值在AR握手时采样，不能错误地把R握手时刻当状态采样时刻。增强未通过实际native波形前不计为已验证。

2. **MMIO sideband支持有限。** ABI没有AxLOCK/cache/prot/qos，当前adapter也没有在MMIO入口拒绝AxLOCK；底层普通MemSimBackend会拒绝lock，而MMIO会按普通访问驱动。现有guest全部是普通非exclusive访问，审查未发现这影响当前用例。接口应明确只支持普通non-exclusive访问；若希望对输入严格fail-closed，应在适配入口拒绝lock，并用定向测试核验。不能把当前结果扩大为所有AXI4 sideband语义完整实现。

3. **完成队列排空不单独证明整个计算已完成。** adapter的`drained`核对host/DMA队列和计数，但未直接检查RTL内部busy。当前runner还要求guest成功完成全部五条命令、清洁模拟退出，checker核对全部返回，因此最终suite不只依赖drained；不要将单独的 `sparse_gate_summary.json` 当完整gate验收凭证。

4. **源代码锁与二进制归属要保持配对。** DLL由build_id、构建源码哈希和库哈希绑定，native runner也记录guest可执行文件及前后源码锁。gem5可执行文件另记于environment manifest；发布时保留该manifest及本次增量构建记录，避免仅用运行时源码hash宣称任意旧gem5 binary来自这些源码。

静态审查没有发现数据丢失被静默补齐、fake memsim完成、C++瞬时计算整任务或复用错误直接被成功接受的确定性实现缺陷。这里的结论仅针对读取到的实现及当前受限协议/fixture；最终native PASS仍须以新回执和波形增强检查为准。
