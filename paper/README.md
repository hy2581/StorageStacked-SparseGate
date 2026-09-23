# SparseGate manuscript

The current Vortex CP DMA manuscript is available in [English](SparseGate-Vortex-review.pdf) and [Chinese](SparseGate-Vortex-review-zh.pdf). Both editions show the Vortex command path and include the independently checked Vortex source result. They are research drafts, not peer-reviewed papers or a new all-suite finalization.

Build both editions from the repository root with Python 3, LaTeX, BibTeX, and Poppler:

```sh
PAPER_PYTHON=python3 bash paper/build_vortex_review.sh
```

This build checks the frozen numerical tables and `evidence/system/vortex_gate_cp.json`, compiles both PDFs, and writes `vortex_review.json` with source, figure, and PDF hashes. `compile_tex.sh` is the shared TeX/BibTeX compile step. The numerical tables and plots come from measured evidence; the four conceptual figures and their prompts are in `figures/generated/` and `zh/figures/generated/`.

The current drafts omit the four-row finish-time table because its programs perform different amounts of work. All underlying JSON evidence remains intact. The remaining three tables and seven figures were regenerated in an isolated worktree at `4815f85eed64a5cd37584bb358a4a05b620c6800` using the current `prepare.py` and `zh/prepare_results.py`, plus `zh/generate_figures.py`. The current Vortex source changes three files sealed by the older Chinese receipt, so those historical measurements cannot be regenerated from this checkout directly.

The earlier [English](SparseGate-paper.pdf) and [Chinese](SparseGate-paper-zh.pdf) PDFs, with `delivery.json` and `zh/delivery.json`, are historical snapshots. Their CPU measurements and source hashes predate the Vortex command-source change. Rebuilding those sealed editions requires their corresponding historical checkout; `build.sh` and `zh/build.sh` are retained for that purpose. The current checkout's build entry is `build_vortex_review.sh`.

The implementation and evidence boundaries are stated in the manuscripts. The repository does not distribute proprietary synthesis libraries or full model weights.
