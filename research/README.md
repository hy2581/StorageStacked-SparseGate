# CSA2 sources, arithmetic oracle, and reproducible inputs

This directory targets the **post-projection DeepSeek-V4.1-Flash CSA2 indexer**. The algorithm is attributed to DeepSeek-AI. Arithmetic and integration are the hardware work; FP4, Top-K, cross-layer reuse, and hierarchical candidates are existing mechanisms. [algorithm.md](algorithm.md) records the primary-source comparison and implementation boundaries. The native hardware interface is [../docs/sparse_gate/interface.md](../docs/sparse_gate/interface.md).

## Reproduce

Run from the repository root with Python, NumPy, PyTorch, requests, and C/C++ compilers available. The recorded environment used Python 3.8, NumPy 1.24.3 and PyTorch 2.4.1+cu121 on CPU; no CUDA kernel or whole-model inference is required.

```sh
python research/fetch_reference.py
python research/fetch_publications.py
python research/verify_oracle.py
python research/generate_inputs.py
python research/validate_inputs.py
```

The committed locks are immutable expected content. `--initialize-lock` is only for first establishment of a missing lock and refuses an existing one. Normal reproduction never replaces the expected hashes. `fetch_reference.py` reads only seven source/metadata files, a safetensors header, and five tensor slices. It requires HTTP 206 and an exact Content-Range; a server returning a whole shard is rejected before reading the body. Tensor payload totals **5,707,008 bytes**. No model weights are committed; downloaded artifacts live under ignored `results/research/reference/`.

| Artifact | Meaning |
|---|---|
| `csa2_sources.lock.json` | Fixed official revision, source URLs/hashes, five tensor names/shapes/dtypes and byte ranges |
| `publications.lock.json` | Original CSA2 v1 report hash; OCP MX specification citation and local-download limitation |
| `results/research/reference/manifest.json` | Actual successful bounded fetch and source binding |
| `results/research/oracle-audit/summary.json` | Independent exact-fraction rounding-cell checks and NumPy IEEE add/mul checks |
| `results/research/inputs/manifest.json` | All fixture/wire hashes, source hashes, CPU Torch comparisons and input provenance |
| `results/research/readback/summary.json` | Fresh oracle, source/byte readback, official candidate function and C99/C++17 header execution |
| `fixtures/csa2_real_weights_fixture.h` | Small C/C++ shared fixture; true trained weights, explicitly random activations |

The OCP MX 1.0 specification was read at its official URL using the web research tool. Direct download returned HTTP 403, so no local OCP PDF/hash is claimed. The CSA2 v1 report is downloaded and hashed normally.

The two official Torch `index_score` assignments are AST-extracted from the pinned `inference/model.py` and executed on CPU in FP32 and BF16. This tests the published expression without importing TileLang/CUDA dependencies. It does **not** replay the official GPU projection or score kernel. Projection, RMSNorm, RoPE and FP4 quantization are readable CPU ports, with that scope recorded in each weight-derived fixture.

## Arithmetic and input contract

`csa2_oracle.py` uses integer dyadics for every FP32 round-to-nearest-even step. E2M1 is decoded to twice its value, each group32 integer dot is exact, group scales are applied, four groups are added in order, then ReLU, signed BF16 weight multiplication, and 32 heads added in order. Subnormals are retained. Invalid E8M0 255 or BF16 NaN/Inf returns `FORMAT_ERROR`; any finite-input intermediate FP32 overflow returns `ARITHMETIC_ERROR`. These errors have no successful Top-K output.

Use `evaluate_fixture(case)` or:

```sh
python research/csa2_oracle.py results/research/inputs/pretrained-layer20-small-full.json
```

Fixtures contain packed FP4 Q/K, group scales, signed head weights, an LSB-first candidate bitmap, and independently generated expected score bits and indices. Hardware result order is ascending position; selection order is descending score then ascending position. Zero ties therefore need not match the arbitrary indices returned by Torch `topk`.

The frozen oracle validates scales throughout the supplied K array before scoring. Equivalence to RTL Reindex therefore assumes that the supplied cache is format-valid throughout. Physical Reindex only checks fetched records: corrupt unselected records are not observed. The wrapper review explicitly tests that distinction; it does not require the hardware to read skipped records for validation.

All generated tests use D=128 and H=32. Full Top-512 is exercised at N=520, 600, 640 and 1024; small K cases are explicitly marked parameter variants. Boundary cases include all-zero ties, negative weights, cancellation across groups, subnormal/zero underflow, overflow, invalid formats, sparse Reindex masks and a smaller candidate-block pool. An independent software check exercises the official 2048-block capacity at N=16401. **The hardware does not implement candidate-block generation.**

`select_candidate_blocks` is an external producer reference. It performs block maxima, pins the newest visible block, applies stable ties, and intersects selected blocks with the visible-position range. The official prefill block bitmap can include invisible tail positions, whose scores were already causally masked; physical DMA IDs must exclude them. `validate_inputs.py` executes the complete official Torch function and compares this visible intersection at three sizes.

## Physical byte layout

Logical `query.bin` is 2048 B FP4 + 128 B scales + 64 B weights; logical `keys.bin` is 68 B per index. These are compact oracle interchange files, **not the physical AXI traffic count**.

Native `query_axi96.bin` uses one 96 B record per head: packed FP4[64], scales[4], little-endian BF16[2], zero padding[26]. `keys_axi96.bin` uses packed FP4[64], scales[4], zero padding[28]. `candidate_ids_u32le.bin` contains ascending unique uint32 positions. Every physical record is three 32 B AXI beats; padding is real traffic.

The C header defines `SG_REAL_HEADS=32`, `SG_REAL_KEYS=64`, `SG_REAL_TOPK=8`, `SG_REAL_NCAND=16`, `sg_real_q`, `sg_real_k`, `sg_real_candidate_ids`, and separate FULL/REINDEX expected index/score arrays. The two Reindex candidate blocks are [8,16) and [56,64). This explicit test mask is not claimed to be a Top-2048 output at N=64, where all eight blocks would fit.

The true-weight fixtures use the official layer20 indexer weights with independently seeded Gaussian x[5120], qr[1280] and latent[N,512]. They are **not text-derived hidden states, a full-model trace, quality/perplexity evaluation, or CUDA bit-exact inference**. The header's generated activations do not contain the five original trained weight arrays.

## Current numerical evidence

The audit checks 99,244 finite input pairs for each of FP32 addition and multiplication, plus 5,010 exact-rational rounding cells, with zero mismatch. The generated corpus has 11 successful operator cases, three format-error cases and two arithmetic-overflow cases. These counts describe software/oracle validation; RTL and system results have their own manifests.

`python research/export_evidence.py` checks the frozen provenance and exports a self-contained, tracked `evidence/research/summary.json` for documentation. The compact record has no dependency on the ignored downloaded tensor/PDF files for reading its numerical results; regeneration still requires the source-locked inputs above. The additional wrapper review is separately reproduced by `python research/review/run_wrapper_review.py` and exported to `evidence/review/wrapper.json`.

For the real-weight N=640 Top-512 case, the CPU FP32 official expression matches this ordered oracle on these particular 640 scores. The BF16 expression has relative L2 error 0.00395188 and maximum absolute score difference 0.0328097; the selected set is unchanged in this case. This observation is not a general equivalence guarantee. The all-zero N=520 case has a 16-element symmetric difference between stable hardware selection and Torch's arbitrary tied selection, with equal scores at every differing position. Both outcomes are retained in the manifest.
