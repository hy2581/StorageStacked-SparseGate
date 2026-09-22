# SparseGate 学习式 token 门控计算核心

这是新写的可综合数字计算通路：packed E2M1 Q/K → 16 lane 小整数乘加 → 32维group FP32缩放 → 128维点积 → ReLU → signed BF16 head weight → FP32跨head累加 → stable Top-K minheap。它真实处理Q/K数据，不接受软件预计算score作为替代。算法/数值接口见 [INTERFACE.md](INTERFACE.md)。

默认32 heads、D128、group32、K上限512；一份68B K记录在各head间复用。Q每head为64B FP4+4B E8M0 scale+2B BF16 weight。外部96B记录padding由wrapper负责，epoch/跨层候选复用/地址转换/DMA不在此核心内。权重有符号，因此没有假定贡献非负的提前终止。

`sg_fp32_pkg.sv` 实现有限输入的FP32 RNE加法、乘法与带二进制尺度整数转换，保留渐进下溢。分组的FP4值先乘2转小整数，32项点积精确落在±4608；全维dot完成后才ReLU。任何中间有限输入溢出都报告错误并终止job，不生成选择结果。运算顺序是公开的自定义参考合同，不声称与CUDA并行规约逐bit相同。

选择堆以分数较低、同分index较大的项为根。新候选不足K时插入，满时仅替换根或丢弃；每周期处理一个heap层级，O(logK)，没有512路宽插入比较器。输出选中集合按heap存储顺序，带last和ready/valid；wrapper若要位置升序需另行排序。

实际计数：`mac_terms`数真实执行的FP4标量乘积项，成功完整scan为 keys×heads×128；`keys_scored`数完成数值打分的key；`cycles`包含job启动后的Q/K字节装载、核心计算、排序及外部输出背压，排除done等待。不能用它直接推断未实现总线的峰值带宽。

## 独立验证

先按 [research/README.md](../../research/README.md) 生成锁定输入；在仓库根运行（完整回归需要 Icarus Verilog、Verilator、C++ 工具链与 Python/NumPy）：

```bash
python3 scripts/sparse_gate/validate_fp32.py --out results/sparse-gate/fp32-final
python3 scripts/sparse_gate/validate_core.py --fixture-manifest results/research/inputs/manifest.json --out results/sparse-gate/core-accepted
python3 scripts/sparse_gate/collect_evidence.py
python3 scripts/sparse_gate/lane_sweep.py
```

浮点参考来自独立编写的 `research/csa2_oracle.py`，以任意精度整数和二进制指数完成RNE，不调用RTL或host浮点作算术oracle。核心测试使用真实输入字节驱动完整运算、逐key核分数并核最终集合，覆盖32 heads、512项heap、随机到达顺序、tie、负权重、subnormal、加载缺失/非法格式/溢出、reset和score/result/done背压。`--fixture path.json`可追加符合research fixture schema的原始Q/K/scale/weight数据。`--quick --simulator iverilog`提供小配置工作量的快速复跑，但实际模块默认资源参数仍为完整32/512/16。

结果summary锁定输入、源码、oracle、仿真二进制和工具哈希；运行期间源码变化导致失败，不自动改绑证据。`evidence/core`保存独立综合证据。当前本机Yosys frontend不接受使用的SV package/int cast，失败记录独立保留；原生Design Compiler SystemVerilog流程如下：

```bash
export SG_LIBRARY=/path/to/your/authorized/tt0p9v25c.db
export SG_DC=/path/to/dc_shell
python3 scripts/sparse_gate/run_dc.py --library "$SG_LIBRARY" --dc "$SG_DC" --out results/sparse-gate/dc-new-run
python3 scripts/sparse_gate/summarize_dc.py results/sparse-gate/dc-new-run
```

本次实测使用完整32/512/16配置、TSMC28HPC+ TT0.9V25°C库和2ns目标。复跑者必须显式提供自己可使用的库与工具路径；改变库会产生新的实现结果，不能沿用本次PPA数字。第一个命令在新目录冻结源代码，不覆盖已有运行；第二个命令要求映射结束，再独立打开已保存的DDC，检查全部叶单元绑定、时序和单位，向 `evidence/core/synthesis.json` 导出小型公开结果。完整日志、网表和DDC留在忽略的 `results/`；库仅本机使用，不复制PDK。已生成报告必须检查完成、映射、单位和时序后才可引用；运行开始、RTL仿真通过或elaborate通过均不等于PPA闭合。

## 尚不属于本核的成果

没有物理SRAM/CIM宏绑定；Q/heap存储可能综合为标准单元寄存器。没有布局布线/时钟树/寄生/功耗签核。没有模型训练、投影/归一化/旋转硬件或最终attention运算。wrapper/系统与模型质量的证据必须分别给出，不能借本核score回归宣称完整大模型或完整物理芯片通过。

参考输入合法性边界：冻结oracle预检查完整K cache的scale格式，core仅检查实际装载的候选记录。与该oracle的等价对照要求完整cache格式合法；未读取位置的损坏不保证被core诊断。既有16个research fixture满足此先决条件。

当前受控并行度实验在相同H32/D128/N640/K512真实训练权重、随机activation、输入次序和背压下运行8/16/32 lane，逐score和最终集合都一致。真实总周期分别608365/444525/362605；详见 `evidence/core/lane_sweep.json`。这里只比较周期，8/32 lane未综合，不能声明面积或已达成时钟的吞吐收益。

吞吐限制必须保留在系统评估中：默认16 lane的H32单key计算与完整性检查需要608周期；扩大为32 lane仍需480周期，因为group转换、FP32规约与head加权按序执行。N640整次job为444525周期；只有实现2ns时钟后才可将其换算为约0.889ms。该核体现真实可综合算术与协议的实现，不据此宣称超过GPU indexer或提高完整模型的端到端速度。

本次完整32/512/16配置的原生DC结果为250241个叶单元、53993个寄存器、0个宏/黑盒，总单元面积301340.925259库单位，其中组合163838.470422、非组合137502.454837；库面积单位与μm²的独立对应见 `evidence/core/area_units.json`。2ns约束下最终setup slack为+0.000006ns（6fs），hold slack为+0.005131ns，报告的电气设计规则违例为0。独立重开DDC后，全部叶单元绑定、时序数值与单位一致；92个数据输入和316个输出的min/max rise/fall延迟均完整，唯一缺input delay的rst_n为已核验的异步复位false-path例外。

最终结果使用理想时钟，未做CTS、布线或寄生提取；clk有53993个load，工具高扇出估计采用1000，未报告其他数据/控制高扇出net。6fs的setup余量不能支持物理频率或鲁棒性结论。`evidence/core/synthesis.json`分别记录timing、设计规则、覆盖检查及最终通过口径；零值面积/功耗优化目标的报告违例另行保留，不混入电气DRV计数。实际运行的旧launcher完整保存在私有source快照，公开入口仅改为通过SG_LIBRARY/SG_DC或显式参数选择环境，两种producer身份分别锁定。
