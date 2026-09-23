# Sources and attribution

The independent project starts at `fmq03/StorageStacked` commit `3be39b697bdc315ae0be08ed2162c322bcf59462`. Its prior history, component notices and pinned external submodule identities are retained. Existing licenses apply to their respective components; this document does not relicense the upstream repository as a whole.

CSA2, its pretrained indexer, cross-layer reuse and candidate construction are DeepSeek-AI work. Primary sources and exact revisions appear in `research/csa2_sources.lock.json`. Bounded download scripts preserve the official source/license text under ignored `results/research/reference/`. The corresponding official MIT notice is reproduced below for attribution of the reference-derived research material. The checkpoint tensors themselves are not committed. The small committed fixture contains generated intermediate numeric inputs from learned weights and seeded random activations, not copied weight tensors.

Wang Ruitai's thesis is a referenced, user-provided source. The original PDF and its illustrations are not republished. `docs/sparse_gate/thesis_redesign.md` records the architectural ideas studied. The new RTL is an independent implementation informed by those documented ideas; no unavailable author RTL or SRAM macro is claimed as included.

Generated conceptual figures use the image-generation tool; the selected images are in `paper/zh/figures/generated/`. The numerical lane-sweep figure comes from repository evidence. Proprietary technology libraries and their derived library databases remain local and are excluded from Git.

## Official DeepSeek-V4.1-Flash license notice

MIT License

Copyright (c) 2023 DeepSeek

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
