# SparseGate v1 integration contract

This design offloads the **post-projection CSA2 index/selection and packed-KV gather** operators. Projection, RMSNorm, RoPE, compression, FP4 quantization, candidate-block production, and final sparse attention remain software/processor responsibilities. It is not a complete DeepSeek LLM accelerator. The stored data are genuine E2M1 FP4 and E8M0 scales, not INT4 substitutes.

## Location and clock

Vortex CP DMA -> native AXI256 -> AXI2Flit -> UCIe -> AouTarget -> memory-side dispatcher. Ordinary traffic continues to MemSimBackend. The reserved register window passes through a cycle-driven AXI256 slave implemented in `sparse_gate_axi.sv`; its AXI256 DMA master shares the single online mem_sim authority. C++ converts existing whole-burst FIFO objects to/from signal handshakes; it must never calculate scores or supply data from a separate image. All RTL clocks use the existing gem5/SystemC time axis.

The Vortex CP DMA path uses physical register base `0x1900f0000` and 1 MiB data window `0x190000000`; the Vortex device sees register address `0x900f0000` through its BAR. The RTL is built with matching `MEM_BASE` and `REG_BASE` parameters. The current gate test does not execute a GPU kernel. The integration dispatcher rejects exclusive (AxLOCK) requests with SLVERR before driving the RTL. The RTL boundary handles ordinary accesses and does not expose lock/cache/protection/QoS sidebands. The slave supports single-beat, naturally aligned AXI accesses up to 32 B, honoring all 32 WSTRB bits and address lanes; unsupported bursts/accesses receive an error. AW and W handshake independently. A SLVERR does not guarantee rollback of other writable configuration bytes in the same beat; software uses a separate naturally aligned 32-bit COMMAND write. IDs and response payloads remain stable during backpressure. The DMA emits one aligned 32 B INCR beat at a time (ID 1); no transfer crosses a 4 KiB boundary. Serialize DMA completion before advancing. This first implementation deliberately bounds outstanding requests to one.

## MMIO, little endian 32-bit registers

| Offset | Register | Meaning |
|---|---|---|
| 0x00 | ID | `0x53474154` |
| 0x04 | STATUS | bit0 busy, bit1 done, bit2 error; bits15:8 error code |
| 0x08 | COMMAND | write 1 start, 2 invalidate index cache; only idle |
| 0x0c | MODE | 0 FULL, 1 REINDEX, 2 REUSE |
| 0x10/14 | Q_BASE | low/high address of Q records |
| 0x18/1c | K_BASE | low/high address of index K records |
| 0x20/24 | CAND_BASE | low/high address of expanded candidate IDs |
| 0x28/2c | OUT_BASE | low/high output result records |
| 0x30/34 | KV_BASE | low/high address of packed main-KV records |
| 0x38/3c | GATHER_BASE | low/high output of packed main-KV records |
| 0x40 | N_KEYS | index-cache record count, 1..65536; complete buffers must fit the aperture |
| 0x44 | N_CAND | expanded candidate count, 1..N_KEYS for REINDEX; empty lists are rejected |
| 0x48 | TOP_K | 1..512 |
| 0x4c | HEADS | 1..32; dimension fixed 128 |
| 0x50 | CONTEXT | explicitly provided context identifier |
| 0x54 | EPOCH | query/cache generation; producer-managed |
| 0x58 | KV_BYTES | 0 disables gather; otherwise positive multiple of32, max4096; CSA2 main record288 |
| 0x5c | RESULT_COUNT | committed count; consume only with successful DONE |
| 0x60 | CYCLES_LO | active RTL cycles |
| 0x64 | CYCLES_HI | active RTL cycles |
| 0x68 | DMA_READ_BEATS | completed 32 B DMA reads |
| 0x6c | DMA_WRITE_BEATS | completed 32 B DMA writes |
| 0x70 | SCORE_COUNT | actually scored keys |
| 0x74 | CACHE_VALID | committed index cache valid |

All address bases are 32 B aligned. Hardware checks complete buffer ranges against the configured memory aperture and rejects outputs overlapping Q, K, candidates, main-KV, or the other output. Input buffers may overlap if the caller intentionally shares immutable bytes. Q records: 96 B/head, byte0..63 packed FP4 low nibble first, byte64..67 four E8M0 scales, byte68..69 signed BF16 head weight, zero padding. K records: 96 B/index, same FP4/scales, no weight. The 28 B K padding is accounted in DMA traffic; the logical68B record is not misreported as 68B physical transfer.

CAND_BASE holds ascending, unique little-endian uint32 IDs; IDs must be < N_KEYS. These are raw compressed index/KV positions, not original-token IDs. Software applies the official offset when combining them with sliding-window entries and handles invisible-entry -1 placeholders; neither operation is performed by this RTL. Software expands the official 8-entry candidate blocks, including its forced recent block. REINDEX physically reads only listed records. Bad IDs, duplicates or nonascending lists terminate with error. FULL scans [0,N_KEYS). REUSE performs no score/Q/K traffic and requires exact equality of context, epoch, N_KEYS, TOP_K, HEADS, Q_BASE and K_BASE to the committed cached selection. Software must increment EPOCH or invalidate when inputs change; this is not hardware cache coherence. Output/gather addresses may change on reuse. A valid START that subsequently fails invalidates its speculative cache and reports error. Illegal doorbell values and rejected AXI writes do not start a job and preserve an earlier committed selection; an illegal doorbell reports SLVERR/error6. Format checks cover fetched records; unread keys in a REINDEX task are not examined.

Each result is a 32 B aligned record: uint32 index, uint32 FP32 score bits, remaining24B zero. Results are in ascending index order (stable Top-K tie chooses smaller index). GATHER_BASE holds selected main-KV records concatenated in result order, `KV_BYTES` each, copied byte-exactly from `KV_BASE+index*KV_BYTES`; no main-KV arithmetic is asserted. All result/gather writes must receive successful BRESP before DONE. An error may leave partial output; software must only consume DONE && !ERROR. RESULT_COUNT may retain a previous count after an error (the stale-REUSE test observes this); neither that count nor residual output bytes constitute a successful result of the failing command when ERROR is set. CACHE_VALID independently controls whether the selection can be reused; explicit invalidation does not erase previous output memory. Readback STATUS/RESULT_COUNT occurs through the original UCIe return path.

Error codes: 1 configuration/address alignment, 2 invalid/stale reuse, 3 bad candidate, 4 DMA response/protocol error, 5 arithmetic/format error, 6 illegal command. Validity is fail-closed. No claim of reset recovery from in-flight external writes; startup reset only. No proof of general AXI4 interoperability beyond the documented subset.

## Numeric contract

For each head and four groups: exact signed small-integer E2M1 products are summed, group scales applied, then groups accumulated in order with FP32 round-to-nearest-even. Apply ReLU after the complete dot, multiply by signed BF16 head weight represented exactly as FP32, then accumulate heads in order using FP32 RNE. The supplied head weight already includes the official projected weight's D^(-1/2) H^(-1/2) normalization; the RTL must not apply it a second time. Invalid scale255, nonfinite weights and FP32 overflow/NaN fail. Subnormal handling and tests are mandatory. Different accumulation order/BF16 output rounding in the official GPU reference can change scores; report comparisons separately from the RTL's bit-exact contract.
