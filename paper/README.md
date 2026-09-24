# SparseGate 论文

仓库只交付一份中文论文：[SparseGate-final.pdf](SparseGate-final.pdf)。源码为
[`zh/main.tex`](zh/main.tex)、[`zh/body.tex`](zh/body.tex) 及 `zh/generated/` 中的
核心测量表格。系统图仅显示 Vortex CP DMA 发出门控请求；论文中的在线系统结果
包括 `evidence/system/vortex_gate_cp.json` 的 H4/N16/K4 冒烟用例，以及
`evidence/system/vortex_gate_sort_ablation.json` 的 H32/N640/K512 同输入排序消融。
后者与独立 RTL 核心的通道数实验分开统计。

论文现阶段定位为可复现的研究基线。关于已测排序改进与顶会级评分机制、真实轨迹及
公平放置对照之间的差距，见 [`innovation-gap.md`](innovation-gap.md)；文中没有把尚未实现的
提前终止机制写成实测成果。

在仓库根目录执行 `bash paper/build.sh`。需要 XeLaTeX、BibTeX、Poppler、
Noto CJK 和 TeX Gyre 字体。构建临时文件写入系统临时目录；完成后仓库内只保留
`paper/SparseGate-final.pdf` 一个 PDF。四张架构概念图保留在
`zh/figures/generated/`，通道数图 `zh/figures/lane_sweep.png` 来自核心实验。

论文为工程研究草稿；Vortex 用例没有执行 GPU 核函数，算术核心综合也没有完成
布局布线和物理签核。

排序消融的插入排序基线位于提交 `8aec365`；当前 `main` 使用原位堆排序。分别在对应
源码版本运行 `bash env/build_sparse_gate.sh` 和
`bash env/run_vortex_gate.sh results/vortex-gate-long-new long`，再对各自的
`results/vortex-gate-long-new/case` 执行 `python3 research/analyze_gate_phases.py` 并写入
`gate_phase_cycles.json`。
两版均通过在线审计后，用当前版本的 `research/compare_sort_ablation.py` 汇总。公开仓库只
保存紧凑的审计结论，原始 VCD 和 UCIe 轨迹保留在本地结果目录。
