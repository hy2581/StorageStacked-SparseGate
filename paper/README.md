# SparseGate 论文

仓库只交付一份中文论文：[SparseGate-final.pdf](SparseGate-final.pdf)。源码为
[`zh/main.tex`](zh/main.tex)、[`zh/body.tex`](zh/body.tex) 及 `zh/generated/` 中的
核心测量表格。系统图仅显示 Vortex CP DMA 发出门控请求；论文中的在线系统结果
只使用 `evidence/system/vortex_gate_cp.json` 记录的 H4/N16/K4 FULL 用例。
H32/N640/K512 属于独立 RTL 核心验证，不是当前 Vortex 在线系统实验。

论文现阶段定位为可复现的研究基线。关于现有贡献与顶会级机制、对照实验之间的差距，
见 [`innovation-gap.md`](innovation-gap.md)；文中没有把尚未实现的提前终止机制写成实测成果。

在仓库根目录执行 `bash paper/build.sh`。需要 XeLaTeX、BibTeX、Poppler、
Noto CJK 和 TeX Gyre 字体。构建临时文件写入系统临时目录；完成后仓库内只保留
`paper/SparseGate-final.pdf` 一个 PDF。四张架构概念图保留在
`zh/figures/generated/`，通道数图 `zh/figures/lane_sweep.png` 来自核心实验。

论文为工程研究草稿；Vortex 用例没有执行 GPU 核函数，算术核心综合也没有完成
布局布线和物理签核。
