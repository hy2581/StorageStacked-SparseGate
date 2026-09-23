# 中文论文

当前 [Vortex 中文审阅稿](../SparseGate-Vortex-review-zh.pdf)展示 Vortex 命令处理器 DMA 发起的门控路径，与[英文审阅稿](../SparseGate-Vortex-review.pdf)使用相同的数值证据。正文保留算法归属、公式、结果和验证边界；四张概念图为中文，三张测量图由证据生成。

从仓库根目录同时构建中英文审阅稿：

```sh
PAPER_PYTHON=python3 bash paper/build_vortex_review.sh
```

`body.tex` 是中文正文；`prepare_results.py`、`generate_figures.py` 和 `figures/manifest.json` 记录此前封存的数值段落与测量图来源。当前构建核对封存数值表与 Vortex 系统回执，不把旧 CPU 实验重新记为当前源码的新实验。

[旧版中文 PDF](../SparseGate-paper-zh.pdf)、`delivery.json` 和 `visual_review.json` 对应 Vortex 修改前的源码快照。`build.sh` 仅供在相应历史版本中重建旧版。当前稿使用思源 Noto CJK、TeX Gyre Termes 和嵌入的测量图字体；协议术语与未完成的模型质量、物理签核边界以正文为准。
