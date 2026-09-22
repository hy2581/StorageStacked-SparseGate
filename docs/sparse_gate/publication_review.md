# 独立发布审查

审查日期：2026-09-22。对象为 `StorageStacked-SparseGate` 当前工作树。最新一轮仅更新本报告，读取源码、文档、公开摘要及其锁定的本地证据；未重跑仿真或综合、未修改运行源码、未执行 GitHub 写入。四项 launcher 拒绝检查均在启动 EDA 工具之前结束。检查时 HEAD 仍为上游基线 `3be39b697bdc315ae0be08ed2162c322bcf59462`，新内容尚未提交。

## 当前结论

**本地交付审核通过。** 已发现的发布范围和复现入口问题均已关闭；在线系统完整验收、综合摘要、面积单位关联及其生产者证据通过复核。Top-512 父 suite、单例后验和 native aggregate 均为 PASS；正式 7 页论文、生成清单及逐页视觉记录已完成关联核查。当前候选清单没有发现 PDK、数据库、DDC、原始工具报告、模型权重或大型波形产物。

真实远端推送尚待根代理执行并保存验证回执；本报告不提前宣称 GitHub 上传完成。综合的理想时钟、6 fs 裕量及未进行物理签核等限制仍然适用。

## 已关闭的问题

| 原问题 | 修正及实际复核结果 |
|---|---|
| 1：当前配置指向原仓库 | `docs/setup.md` 与 `env/README.md` 的当前克隆、恢复和 origin 配置指向新仓库；历史验收和原 README 明确标为上游历史。 |
| 2：核心回归输出目录不一致 | README 显式使用 `validate_fp32.py --out results/sparse-gate/fp32-final`，与后续收集入口一致，并说明研究输入和工具依赖。 |
| 3：综合入口硬编码个人路径 | 公开 launcher 通过 `--library` / `SG_LIBRARY`、`--dc` / `SG_DC` / PATH 选择环境；缺失库参数、无效库参数、无效环境库路径、无效工具路径四种实测均返回 2，未启动工具、未创建输出。实际旧 producer 的私有快照已保留，新复现入口单独记 SHA，未改写历史归属。 |
| 4：公开 exporter 复制完整 timing report | 当前 exporter 的公开输出仅为选定数值、约束、状态和哈希组成的 JSON；原始报告、网表、DDC、DB 面积表留在忽略的 `results/` 内。候选清单不存在旧 `setup_excerpt.txt`、`hold_excerpt.txt` 或其他 `.rpt`。 |
| 5：Verilator runtime 目录硬编码 | builder 从实际工具或显式 `VERILATOR_ROOT` 解析 runtime，并锁定所用文件；正式模型重建及已完成小例使用相应 build ID。 |
| 6：搬移的上游 README 相对链接失效 | 六处链接均改为固定上游 `3be39b697bdc315ae0be08ed2162c322bcf59462` 的 URL，保留历史归属。 |
| 7：Top-512 可被默认 collector 跳过 | collector 默认包含最终 Top-512 目录，并无条件要求该 suite；曾在缺少完成回执时保持未完成，最终 PASS 已实际纳入该完整回执。 |
| 8：mem_sim 库只有记录哈希而无现查 | collector 重新计算实际 `.so` SHA 并与运行环境记录比较，已完成四份 gate case 的值一致。 |
| 9：suite 与单 case 回执未绑定 | collector 要求父 suite、case 均通过，并核对 case 回执的实际路径、SHA 和 suite 记录。 |
| 10：collector 自身可能在收集期间变化 | 收集开始及写出前均检查 collector 源码哈希，摘要保存该身份。 |

问题 3 的关闭范围是 README 支持的 Python launcher。两个 Tcl 文件继续作为冻结的内部输入，由 launcher/读回入口提供并核验 `SG_LIBRARY`；本轮没有为其补写新 guard，也不声称直接绕过 launcher 调用 Tcl 已得到独立验收。公开新旧 launcher 的差异仅涉及环境解析、私有输出位置和 launcher 快照记录，算术 RTL、综合约束和已运行命令未被替换。

## 综合、面积与生产者关联

本轮重新计算以下文件的完整 SHA，并逐项验证摘要内声明的源码、生产者和私有 artifact 哈希：

| 证据 | SHA256 |
|---|---|
| `evidence/core/synthesis.json` | `781681d86df378f8f663dc6874d07ddc3a3f734ce2c14d1dc685bd337a755d27` |
| `evidence/core/area_units.json` | `b5695ae9ee939fea9d3f6c6918bb154347a4bf1b58e8444ca74eeda8c8155a7d` |
| 实际综合 DB | `5363ad782af12e7cec187d23d27696c136d9d9014b8ba645b544228b18caf8e4` |
| 私有 DB 单元面积读回 TSV | `b735c7f9fe01494a2ef4089211c1f43b08fc42be881bbc07f064aaf41028edf5` |

`run_producer.used_sha256` 与私有 `source/run_dc.py`、原 `run.json` 的 producer 字段一致；`reproduction_entrypoint.sha256` 与当前便携 launcher 一致。两次 DDC 读回后的最终 TSV 哈希一致。公开摘要所列全部原始报告、网表、DDC、run metadata 的实际文件哈希均匹配。这里的 DDC 重新打开、叶单元绑定及报告一致性检查不是门级逻辑等价证明。

实际 DB 的 1,142 项面积与 Liberty 全部精确匹配，Liberty 的同一 1,142 个单元又与 LEF 的 `SIZE` 宽×高全部精确匹配；两步最大绝对/相对误差均为零，绝对/相对容差均为零。LEF 另有 44 个不在该 NLDM 库中的宏，不构成 Liberty 缺失。厂商 release note 的 kit 依赖关系以及公开 LEF 手册的微米语义已由面积脚本解析核查。两个 JSON 的 DB SHA、TSV SHA 和 1,142 行计数逐项相等，因此该映射库的 cell area 可解释为 μm²，而不是凭工艺名称或相似文件名推断。

正式映射范围为 H32 / K512 / L16 算术、heap 和寄存器阵列；不含 AXI wrapper、DMA 或物理 SRAM 宏。摘要为 `MAPPED_TIMING_MET / passed=true`，250,241 个叶单元、53,993 个寄存器、零未绑定引用；单元总面积为 301,340.925259 μm²。该数字是标准单元面积之和，不是布局 core/die 面积。

在 TT 0.9 V / 25 °C、2 ns 约束下，最终与独立读回的 setup slack 均为 **+0.000006 ns（6 fs）**，hold slack 均为 +0.005131 ns。覆盖检查确认 92 个数据输入、316 个输出的 min/max rise/fall delay 及关联时钟；唯一 `no_input_delay` 警告针对有显式 false path 的异步 reset，未豁免其他未约束端点。电气约束违例计数为零；零值 max-area/max-leakage 优化目标的违例单独保留，不能把该电气计数称作物理 DRC 通过。

**6 fs 的 setup 余量几乎没有工程裕量。** 时钟仍为理想模型，未做 CTS、布线、寄生提取或多角验证；53,993 个时钟负载使用工具的高扇出估计，不能据此声称 500 MHz 物理实现已闭合。`physical_signoff=false`、`gate_level_equivalence_status=NOT_RUN` 与这些边界一致，论文须保留。

## 候选上传清单

清单由 `git ls-files -z` 与 `git ls-files --others --exclude-standard -z` 的并集形成，不把外部子模块工作树展开为主仓库内容。正式 PDF 加入后、本轮修改报告前的快照为 **538 个普通文件、14,413,676 字节**，最大文件是 4,465,599 字节的正式 PDF，无超过 5 MiB 的文件。最终暂存和远端对象仍由根代理核对。

- 候选文件中没有 `.db/.lib/.alib/.ddc/.svf/.gds/.safetensors/.pt/.pth/.onnx/.bin/.so/.a/.o/.vcd/.fst/.fsdb/.rpt`，也没有完整 timing excerpt。当前公开的综合及面积材料为源码与摘要 JSON。
- 继承的 `gem5_new/docs/zhongxing-20260907.tar.gz` 再次在内存检查：126 个成员、普通文件展开量 715,986 字节，无链接成员、受限扩展名或凭据模式；未解包到工作树。
- 候选文件及继承归档未命中 GitHub token、私钥头和 AWS access-key 模式；这只是所列模式扫描，不宣称覆盖全部秘密形式。
- `git check-ignore` 实测确认原始 DDC、timing report、DB 面积 TSV 所在 `results/`、历史 `evidence/core/dc-*/`、`paper/build/` 和 preview PDF 不进入默认候选。ignore 不防止强制添加，最终暂存仍须核对真实清单。
- 子模块 HEAD 保持锁定；原运行中的本地适配不作为新 gitlink 更新。此前确认的新仓库 origin 与只读 upstream 归属保持不变，本轮未执行远端变更。

## 在线系统最终验收

最终 `evidence/system/summary.json` 的 SHA256 为 `fdea5797fe4a7c58d1764a52b355e81b9053828ebf34b21b5398c8bb40bec4db`，状态为 `PASS / passed=true`，failures 为空。baseline CPU（19 项 native、7 组链路）、baseline XPU（4 组）、CPU synthetic、CPU learned-weight、三源共存、慢内存对照和完整 Top-512 均纳入该回执。

README 的“新增 5 个原生运行用例、22 条命令、4 条预期拒绝”经逐项计数一致：synthetic、learned-weight、three-source、slow 各 5 条，Top-512 为 2 条；前四个运行各包含一次预期过期版本拒绝。这里是 5 个运行实例，快/慢对照使用同一 guest 可执行文件，不应表述为 5 份互不相同的程序源码。

本轮对五个运行逐一重算 suite、case、环境、集成源码锁、模型 manifest 和关键小型 artifact 的 SHA；重新核对所有声明的当前集成/RTL/model 源码、guest 可执行文件、gem5、mem_sim 库、RTL DLL。累计重新计算 101 个不同文件，全部匹配。suite 中实际回执路径及 SHA 与 aggregate 和当前 case 文件一致；每条命令的计数与已验 RTL busy 起止、读写拍数、无 outstanding 及最终 B/DONE 顺序对应。完整原始 VCD/Flit 的逐事件检查由已锁定 checker 完成，本轮未重复运行该耗时检查或仿真。

Top-512 单例回执 SHA256 为 `0a58fbe4eb8375693689e9499db3312a16eb01a60cd103f258f6e6e493c7b7aa`。其父 suite 和后验均通过，记录 81,278 个主机协议入口请求、93,536 个 native 内存请求、71,639 个 RTL 波形握手；总 DMA 读/写为 11,232 / 10,240 拍。FULL 与 REUSE 的周期为 670,572 / 115,776，读写为 6,624/5,120 与 4,608/5,120 拍，每条命令核对 512 个结果及 147,456 B gather；这些数字与 README 一致。

H32/N64/K8 快例 FULL/REUSE/REINDEX 的周期分别为 55,155 / 1,949 / 18,788，读拍为 360 / 72 / 218，写拍均为 80；4 倍内存周期使成功命令变慢，而分数、索引及 DMA 拍数保持一致，完整主机时间增加 181.530 μs。论文和 README 区分了 RTL busy 周期、完整主机运行时间、原协议入口请求和存储侧 DMA，未把不同模式作为可互换的准确率基线。

三源用例中的 host/Vortex/CoralNPU 均出现，但 gate busy 内 Vortex/CoralNPU 事件各为零，因此是共存验收，不是三处理器与 gate 并发争用。learned-weight 输入配随机中间激活，KV 为确定性搬运图案，不是完整模型推理或质量评测。

## 正式论文与本地交付

正式论文通过无 preview 的严格构建，7 页、7 幅图、4 张表、8 条参考文献。系统、综合和面积证据未因排版调整而变化。最终文件锁定为：

| 文件 | SHA256 |
|---|---|
| `paper/SparseGate-paper.pdf` | `10a5fd028b5cec677c52e3d29631efbd8fac83f165af3c01e0d9760acdb494d6` |
| `paper/delivery.json` | `1f8ab3d4bf44882e93491b52f3be8169b88a020dbd1cf4edbcade970ef6f5d15` |
| `paper/visual_review.json` | `7a4ff95de7243b0934332e7c8e30aca5a01b8700c8392a8f02ac0592759106e5` |

本轮实际重算 PDF、delivery、visual review、全部 delivery source/figure/TeX、生成 manifest 中的证据输入及输出哈希，全部匹配；`preview=false`、缺失证据列表为空、自动检查全部通过。PDF 文本中 7 个图号、4 个表号和 8 个参考文献编号完整，不含 preview、未完成提示或缺失引用占位。

正文中的 670,572 / 115,776 周期、6,624/5,120 与 4,608/5,120 拍、147,456 B gather、快慢小例周期、181.530 μs 主机差、301,340.93 μm² 表格面积、250,241 个叶单元、53,993 个寄存器和 6 fs setup 裕量均与冻结证据相符。摘要的 0.301 mm² 是标准单元面积的舍入值，不是 die 面积。物理实现、模型质量、随机中间激活和三源共存的限制保留在论文中。

逐页视觉检查由**根代理**完成，并单独记录在 `paper/visual_review.json`；本轮审阅没有冒称重新执行同一视觉检查，而是实际核对其 7 张最终页面渲染文件的 SHA、PDF SHA 和 delivery SHA，全部匹配。根代理记录图、表、公式可读且无裁切，孤立参考文献末页已消除；该记录不是额外仿真或独立科学同行评审。

最终暂存前仅清理了许可证文本的换行和自动摘要的末尾空格，生成器增加写出时的 `rstrip()`。严格重建后的 PDF、delivery、visual review 和全部 manifest 哈希再次匹配；7 张新页面 PNG 的字节哈希与逐页审阅版本完全相同，因此沿用该视觉审阅。运行源码、实验数据和数值结论未改变。

## 远端发布边界

本地内容可以进入最终暂存与推送。根代理另已只读复核原仓库工作区干净、原 main/gmx 保留且 Release 为零，新仓库 origin 和外部子模块锁正确。实际新仓库 commit/push、远端 SHA 和公开 PDF 回读由根代理随后执行并单独保存回执；在该回执产生前，本报告不把远端发布列为已完成。
