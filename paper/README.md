# SparseGate hardware manuscript

The English IEEE-style manuscript accompanies the independently implemented digital hardware and its online system integration. It is an engineering research draft, not a peer-reviewed publication. Algorithm attribution, hardware boundaries, evidence limitations and measured timing margins are retained explicitly.

完整中文译稿见 [SparseGate-paper-zh.pdf](SparseGate-paper-zh.pdf)。正文与全部七张图、四张表已中文化并进行学术语言润色，保留英文版的公式、实验数据和结论边界。中文 LaTeX、图表提示词与独立构建命令见 [zh/README.md](zh/README.md)；两种语言分别记录交付与逐页检查结果。

- `main.tex`, `references.bib`: editable manuscript and primary references.
- `export_completion.py`: exports a small actual VCD window from the accepted native CPU case when regenerating system evidence.
- `prepare.py`: generates numerical macros, tables and measured plots from evidence JSON; verifies the recorded source hashes and refuses final publication when required system evidence is incomplete.
- `figures/generated/`: four academic conceptual illustrations created through six built-in image-generation calls. Exact prompts and semantic review are preserved there.
- `generated/manifest.json`: numerical input/output digests.
- `delivery.json`: final PDF digest, page count, source/figure digests, and automated TeX/PDF checks.
- `visual_review.json`: separate rendered-page inspection record for the final seven-page PDF, including seven figures and four tables.
- `SparseGate-paper.pdf`: final manuscript, produced only after the required evidence is available.

Build from the repository root with Python 3.8–3.11 (the pinned NumPy/Matplotlib versions), TeX Live (`IEEEtran`, `amsmath`, `booktabs`, `microtype`, `hyperref`) BibTeX, and Poppler (`pdfinfo`, `pdftotext`):

```sh
# Use a Python 3.8–3.11 interpreter for these pinned packages.
python3 -m venv .venv-paper
. .venv-paper/bin/activate
python -m pip install -r paper/requirements.txt
bash paper/build.sh
```

For an explicitly incomplete local preview, use `bash paper/build.sh --preview`. A preview is not the final deliverable. Generated numerical tables/plots are derived from measured records; the image-generation tool never supplies experimental data. Proprietary synthesis libraries and full model weights are not included in the repository. See the root README and evidence summaries for independent reproduction of the measurements.
