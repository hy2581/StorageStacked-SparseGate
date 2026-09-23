# 中文论文

本目录为已定版英文论文的完整中文译稿。正文按中文学术行文习惯润色，保持算法归属、公式、实验数字和验证边界。四张架构概念图同步中文化，三张测量图直接由原有验证数据绘制；接口信号、数据格式和执行模式保留原标识。

新增 Vortex 命令处理器 DMA 发起门控命令的[中文审阅稿](../SparseGate-Vortex-review-zh.pdf)采用已更新的系统图，并对应单独的系统回执；原最终版 PDF 的旧图与 CPU 等测量数据仍对应此前封存的源码快照。
审阅稿复现入口为仓库根目录下的 `PAPER_PYTHON=python3 bash paper/build_vortex_review.sh`。

- 最终 PDF：[SparseGate-paper-zh.pdf](../SparseGate-paper-zh.pdf)。
- `main.tex`、`body.tex`、`references.bib`：中文正文与参考文献；参考文献采用 GB/T 7714 数字顺序格式，外文资料保留原题名。
- `prepare_results.py`：核查英文定版清单及证据，生成中文数值段落与四张表；不执行或改写英文生成器。
- `generate_figures.py`：从相同 JSON 生成中文坐标和图例的测量图。
- `generated/manifest.json`、`figures/manifest.json`：中文数值和测量图的输入、生成器及输出摘要。
- `delivery.json`、`visual_review.json`：最终 PDF、来源一致性、字体/排版检查与独立的逐页查看记录。

在仓库根目录执行：

```sh
# Python 环境沿用 paper/requirements.txt。
# 安装 XeLaTeX、CTeX、GB/T 7714 BibTeX 样式、Noto CJK、Droid Sans Fallback 字体及 Poppler。
PAPER_PYTHON=python3 bash paper/zh/build.sh
```

排版使用思源系列 Noto CJK 字体和 TeX Gyre Termes 西文字体。测量图使用 `DroidSansFallbackFull.ttf` 和 DejaVu Sans，确保以 TrueType 格式正确嵌入 PDF；也可用 `SPARSE_GATE_ZH_FONT` 指向其他具备所需中文字符的 TrueType 字体文件。临时 TeX 文件、日志和逐页渲染放在已忽略的 `paper/build/zh/`。

统一术语：contract 根据语境译为“数值约定”或“接口约定”；oracle 译为“独立参考模型”；beat 译为“数据拍”；backpressure 译为“背压”；gather 指选中 KV 的聚集读取与搬运。建立时间裕量仅为 6 fs、理想时钟及未完成 SRAM-CIM 宏绑定和物理签核等限制沿用英文版，不因翻译而改变。
