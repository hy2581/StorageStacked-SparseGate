# AXI 外围独立复核

审查/实测日期：2026-09-22。范围为 `rtl/sparse_gate_axi/sparse_gate_axi.sv`、`sparse_gate_dma.sv`、原 `tests/test_axi.cpp` 和 `interface.md`。本次不改 RTL。结论限定于所写单拍 DMA / MMIO 子集；没有发现当前合法输入合同下会产生错误 Top-K、越界 DMA 或提前 DONE 的阻断缺陷。两处合同歧义已由文档收窄；错误 ID 和多拍错误 R 排空的原覆盖缺口也已由独立测试补齐。

## 冻结源与实测

| 文件 | SHA256 |
|---|---|
| `rtl/sparse_gate_axi/sparse_gate_axi.sv` | `978cd71cd0f8794410fcb326124a36262bf980a8bfb603a92760121bad994073` |
| `rtl/sparse_gate_axi/sparse_gate_dma.sv` | `0c7eb97e4fb64dbb70fb83f9401a45a4fa5aa3ae113799c97faceb7a30050332` |
| `rtl/sparse_gate/sg_index_core.sv` | `094b297eaabca45981dc31dd46661ca6fd39b77859ba9bf1c82681eb5444a3ab` |
| `rtl/sparse_gate/sg_fp32_pkg.sv` | `54e4f21009646b1214236e73def967aefa9e1ebd6099fa483294a57699c65b9c` |

新增 `research/review/test_wrapper_edges.cpp`，复用原时钟/字节存储 BFM，另写边界激励和断言；`run_wrapper_review.py` 从上述 RTL 重新生成并编译 Verilator 模型，不只复用旧二进制。实际 194178 周期完成，所有新增断言通过。可提交的紧凑记录在 `evidence/review/wrapper.json`，含完整源码、工具、二进制与日志哈希。

```sh
python research/review/run_wrapper_review.py
python research/review/run_dma_review.py
```

本次补足的原测试缺口：

- BYTE 写入非零 byte lane、保留未选字节、拒绝 AWSIZE 外的 WSTRB；完整 32 B/八寄存器读回。
- 合法两拍 AXI 写但不受 MMIO 支持：第一拍无 WLAST 时不提前 B，排空末拍后 SLVERR，随后正常写恢复。
- 不支持的三拍读返回三个稳定错误响应，只最后一拍 RLAST，随后正常读恢复。
- FULL H=1、D=128、N=520、K=512，核对全部 512 个零分并列输出与 DMA 计数，再 REUSE 全部 512 项。该测试验证外围数组容量，不替代另有 H=32 核测试。
- busy 期间配置写被拒绝且 EPOCH 不变。
- 暂扣最后一次输出 BRESP，确认仍 busy、非 DONE、未提交 cache；释放成功 BRESP 后才完成。
- 分别改变 context、epoch、N_KEYS、TOP_K、HEADS、Q_BASE、K_BASE，七者都拒绝 REUSE。
- REINDEX 只列 key0，同时 key6 的 scale 故意为 255；任务成功且只产生 7 个读 beat（Q3 + candidate1 + K3），证实未列 K 不可观察。

## 两处已消除的合同歧义

**R1，P2 文档问题，已 fixed-by-document。** `sparse_gate_axi.sv:250` 对非法 doorbell 只置 error6，不清先前的 `cache_valid`；`S_ERROR` 的清缓存发生在 `:347`。原描述“failed new command invalidates cache”过宽。实测 COMMAND=3 返回 SLVERR/error6，但 cache_valid=1，随后 REUSE 成功。`interface.md:42` 现已明确：只有有效 START 后执行失败才使其投机选择失效；非法 doorbell/被拒 AXI 写不启动 job，保留之前已提交选择。这与实测一致，未修改 RTL。

**R2，P2 比较前提，已 fixed-by-document。** `sparse_gate_axi.sv:278-290` 只按候选 ID 发读，核在读到 key 后验证格式，无法检查没有读到的 K。冻结 Python oracle 为便于输入检查会验证整个传入 K 数组的 scale。因此二者 bit-exact 对比前提是整个提供的 cache 格式合法。未选位置故意损坏时，RTL 的不可观察行为符合物理跳读合同；不能要求它复制 oracle 的全数组输入校验。该前提已记录在研究 evidence，`interface.md:42` 也已写明 fetched-only 格式检测。

## 静态审查结论及依据

**地址与别名。** `:190-216` 用 65 bit 计算 region 末端，拒绝 wrap、越过存储窗及 MMIO 页；长度由 32 bit 配置提升到 64 bit 后计算。当前 N≤65536、K≤512、KV_BYTES≤4096 条件下不会因乘法溢出绕过区域检查。输出区域与会读取的 Q/K/candidate/main-KV 分离，gather 与这些输入及输出分离；只读输入彼此重叠本身不破坏作业。`separate()` 自身用 64 bit 加法，但只有 `region_ok()` 全部通过后组合 `ranges_ok` 才可能为真，因此无发现通过 wrap 绕过校验的路径。DMA `:53-54` 还逐拍复查当前窗口和寄存器页；32 B 对齐的单拍自然不跨 4 KiB。

**AW/W 独立与背压。** 外围 `:74-124` 各有一个 AW/W 暂存，原测试已实际覆盖 W 先于 AW；B/R payload 只在响应产生/握手推进时更新。新增 narrow 与 full-line 写直接核对了字节通道。DMA `:37-41,60-66` 分别跟踪 AW/W 握手，只有两者都送达后才等待 B。原 BFM 对两者独立随机背压并逐拍检查稳定性。

**坏 burst。** MMIO `:95-123` 不承诺执行 burst 写，丢弃数据至 WLAST 后错误返回；读端 `:125-133` 对非法 ARLEN 返回声明数量的错误 beat。新增的是合法 AXI burst / 本端不支持的几何，不是任意违背 AXI 的恶意提前 WLAST。无 WLAST 永不出现的对端属于协议失效，不在当前恢复承诺内。

**完成与恢复。** 所有输出与 gather 路径都在 `S_OUTWAIT`/`S_GWRITEWAIT` 等 DMA completion；DMA 完成在 B 握手后产生。`S_FINISH :342-345` 是唯一成功提交路径。新增 held-BRESP 直接验证“数据已经交给写 BFM”不足以完成 job。原 `test_axi.cpp:132-139` 实测坏候选、RRESP、数值格式、BRESP 后重新运行成功；`S_ERROR` 同时复位算术核状态并清投机 cache。已有合同只支持启动复位，不声称在途外部写热复位恢复。

**K=512。** `insert_pos`/`output_no` 为 10 bit；实际数组访问取低 9 bit。正常第 512 次插入时 `result_count=511`，最大合法写索引为 511；完成前不会再从 count=512 启动新插入。`S_ADVANCE` 在输出 511 后结束。新增完整 512 项测试确认未发生零号项覆盖或最后项丢失。这个证明依赖算术核只输出配置数量且最后项置 last 的已有核心合同；外围没有另加一个“第 513 个异常结果”防线，不能称支持失效核心容错。

## 后续定向补测与合同限定

**R3，原 P2 验证缺口，已 fixed-by-test。** 原 BFM `test_axi.cpp:31,33` 固定 RID/BID=1，RLAST=1；DMA `sparse_gate_dma.sv:66,72-73` 的错误 ID 和多拍错误 R 排空此前没有运行覆盖。现已新增独立 `research/review/tb_dma_review.sv` 和 `run_dma_review.py`，以 Icarus Verilog 重新编译同一冻结 DMA 源。实际 65 周期、10 作业、5 个预期错误：错误 RID 后合法读、先 RLAST=0 后间隔四拍再 RLAST=1 后合法读、错误 BID 后合法写、RRESP 错误后合法读、BRESP 错误后合法写。检查最后 RLAST 前不发 done、error 保持、总 completion 恰好 10 次、read beat=7/write beat=4；每一类故障后新合法请求都清错误并成功。写路径还分开 AW/W 并暂停 W 三拍核对稳定。紧凑证据 `evidence/review/dma.json` 保留脚本/TB/RTL、工具、binary/log 哈希。此验证覆盖有限、最终返回 RLAST 的错误响应，不外推对端永不完成或任意 AXI 违规的恢复。

**R4，P3 原子性定义，未作为设计缺陷。** `sparse_gate_axi.sv:108-118` 同一 32 B 写若同时修改普通配置且包含非法/不完整 COMMAND，普通寄存器的非阻塞赋值可能已排队，然后才判 command 错误。AXI SLVERR 不自动承诺整拍回滚，接口目前也没有这样的原子保证。有效软件使用单独 32 bit COMMAND 写，因此当前验收不受影响。不要描述“任一 rejected write 都零副作用”；若未来要求事务性回滚，须先判完整命令合法再执行配置赋值并补测试。

落实状态：已核对 `interface.md:9` 明确 SLVERR 不保证同拍配置回滚，并要求软件使用独立、自然对齐的 32 bit COMMAND 写。本项也已 fixed-by-document；无需修改 RTL 或重新运行已冻结算术核心测试。

## 与系统证据的边界

本记录是重新编译的 RTL 外围模拟，内存端是字节 BFM。它补足外围容量、协议边界、cache identity 和提交时序的运行证据，不是 CPU/GPU/NPU→UCIe→原生 DRAM 链路结果。原生系统接入和 PPA 必须使用各自来源绑定的证据，不从本 PASS 推定。
