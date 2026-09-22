# Generated conceptual figures

Created with the built-in `image_gen` tool, six calls in total: four original figures and two corrections of the system return path. Exact prompts are preserved in `prompts.json`. No CLI fallback or image-editing script was used. The selected images are copied into this repository; no paper path depends on the tool's default output directory.

| File | Purpose | Review |
|---|---|---|
| system.png | Position after UCIe and one shared online memory authority | First draft's direct lower return wire and later orphan left bus were removed; the main AXI/UCIe chain is bidirectional. No measured performance is encoded. |
| core.png | FP4 lane, group, head and heap organization | Checked 16 lane labels, group count, shared K, signed weight location and K bound against RTL. |
| layout.png | Query/index-key/main-KV physical records | Labels and byte totals checked; shapes are schematic and not to scale. The main-KV data are copied opaquely, not computed by the index core. |
| flow.png | FULL/REINDEX/REUSE and successful result commit | Applies to accepted START jobs. Rejected illegal doorbell writes are a separate MMIO error and need not invalidate a previously committed cache. |

These are explanatory illustrations, not circuit schematics, waveforms, layout screenshots or experimental data. Actual plots are independently generated from evidence JSON by `paper/prepare.py`; numerical charts are never produced by image generation. Final PDF rendering is checked at paper size.
