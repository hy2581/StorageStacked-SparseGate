#!/usr/bin/env python3
"""Generate source-locked CSA2 operator fixtures; no full-model activation claim.

Five real pretrained layer-20 indexer tensors drive independent random x, qr,
and latent tensors. The CPU projection/quantization port is readable and is
not the official CUDA kernel. Arithmetic fixtures use the exact-dyadic oracle.
"""
import argparse
import ast
import hashlib
import json
import math
from pathlib import Path
import sys
import time

import numpy as np
import torch
import torch.nn.functional as F
import csa2_oracle as oracle

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def quantize_fp4(x):
    """CPU port of group32 E8M0 FP4 quantization, ties to even significand."""
    x = x.float().contiguous()
    shape = x.shape
    z = x.reshape(-1, 32)
    amax = z.abs().amax(-1).clamp_min(6*2.0**-126)
    # Match the FP32 amax*(1/6) input to fast_log2_ceil in official kernel.py.
    raw = (amax * (1.0/6)).numpy().view(np.uint32)
    exponents = ((raw >> 23) & 255).astype(np.int32)-127 + ((raw & 0x7fffff) != 0)
    assert np.all((exponents >= -127) & (exponents <= 127))
    scales = np.ldexp(np.ones(len(exponents), np.float32), exponents)
    value = (z.numpy()/scales[:, None]).clip(-6, 6)
    magnitude = np.asarray(oracle.MAGNITUDES_X2, np.float32)/2
    distance = np.abs(np.abs(value)[..., None]-magnitude)
    # Even code has an even final significand bit; visit it first for exact ties.
    order = np.asarray([0, 2, 4, 6, 1, 3, 5, 7])
    codes = order[np.argmin(distance[..., order], axis=-1)].astype(np.uint8)
    codes |= np.signbit(value).astype(np.uint8) << 3
    codes = codes.reshape(shape)
    return codes, (exponents+127).astype(np.uint8).reshape(*shape[:-1], shape[-1]//32)


def dequantize(codes, scales):
    val = oracle.e2m1_integers(codes).astype(np.float32)/2
    return torch.from_numpy((val.reshape(*scales.shape, 32)*
        np.ldexp(np.ones(scales.shape, np.float32), scales.astype(np.int32)-127)[..., None]).reshape(codes.shape))


def official_score_function(source):
    """Execute the two actual official Torch score statements, without CUDA deps."""
    tree = ast.parse(Path(source).read_text())
    cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Indexer')
    forward = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == 'forward')
    statements = [n for n in forward.body if isinstance(n, ast.Assign) and
                  isinstance(n.targets[0], ast.Name) and n.targets[0].id == 'index_score'][:2]
    assert len(statements) == 2
    wrapper = ast.parse('def official(q, index_k, weights):\n    return index_score\n')
    wrapper.body[0].body = statements + wrapper.body[0].body
    ast.fix_missing_locations(wrapper)
    namespace = {'torch': torch}
    exec(compile(wrapper, str(source), 'exec'), namespace)
    return namespace['official'], [n.lineno for n in statements]


def true_weight_inputs(reference, rng, n):
    lock = json.loads((ROOT/'research/csa2_sources.lock.json').read_text())
    cfg = json.loads((reference/'inference/config.json').read_text())
    tensors = {}
    for name, desc in lock['tensors'].items():
        path = reference/desc['file']
        assert sha(path) == desc['sha256']
        raw = torch.from_numpy(np.frombuffer(path.read_bytes(), dtype=np.uint8).copy())
        dtype = desc['safetensors_metadata']['dtype']
        if dtype == 'BF16':
            tensor = raw.view(torch.bfloat16)
        elif dtype == 'F8_E4M3':
            tensor = raw.view(torch.float8_e4m3fn).float()
        elif dtype == 'F8_E8M0':
            assert not (raw == 255).any()
            tensor = torch.pow(2.0, raw.to(torch.int32)-127)
        else:
            raise ValueError(dtype)
        tensors[name.split('indexer.')[1]] = tensor.reshape(desc['safetensors_metadata']['shape'])
    x = torch.from_numpy(rng.standard_normal((1, cfg['dim'])).astype(np.float32)).to(torch.bfloat16)
    qr = torch.from_numpy(rng.standard_normal((1, cfg['q_lora_rank'])).astype(np.float32)).to(torch.bfloat16)
    latent = torch.from_numpy(rng.standard_normal((n, cfg['head_dim'])).astype(np.float32)).to(torch.bfloat16)
    # Official FP8 projection format: input group32 E4M3, 32x32 weight scales.
    qrg = qr.float().reshape(-1, 32)
    amax = qrg.abs().amax(-1).clamp_min(1e-4)
    raw = (amax*(1.0/448)).numpy().view(np.uint32)
    exponent = ((raw >> 23) & 255).astype(np.int32)-127 + ((raw & 0x7fffff) != 0)
    s = torch.from_numpy(np.ldexp(np.ones(len(exponent), np.float32), exponent))
    qrd = ((qrg/s[:, None]).clamp(-448, 448).to(torch.float8_e4m3fn).float()*s[:, None]).reshape_as(qr)
    wq = tensors['wq_b.weight']*tensors['wq_b.scale'].repeat_interleave(32, 0).repeat_interleave(32, 1)
    q = F.linear(qrd, wq).to(torch.bfloat16).reshape(cfg['index_n_heads'], cfg['index_head_dim'])
    k = F.linear(latent, tensors['wk.weight'])
    kf = k.float()
    kf = kf*torch.rsqrt(kf.square().mean(-1, keepdim=True)+cfg['norm_eps'])
    k = (tensors['k_norm.weight'].float()*kf).to(torch.bfloat16)
    weights = (F.linear(x, tensors['weights_proj.weight'])*
               (cfg['index_head_dim']**-0.5*cfg['index_n_heads']**-0.5)).reshape(-1)
    # Exact readable port of official adjacent-pair RoPE + YaRN frequency formula.
    rd = cfg['rope_head_dim']
    freqs = 1.0/(cfg['compress_rope_theta']**(torch.arange(0, rd, 2, dtype=torch.float32)/rd))
    def corrected(rot):
        return rd*math.log(cfg['original_seq_len']/(rot*2*math.pi))/(2*math.log(cfg['compress_rope_theta']))
    lo, hi = max(math.floor(corrected(cfg['beta_fast'])), 0), min(math.ceil(corrected(cfg['beta_slow'])), rd-1)
    smooth = 1-((torch.arange(rd//2, dtype=torch.float32)-lo)/max(hi-lo, 1e-3)).clamp(0, 1)
    freqs = freqs/cfg['rope_factor']*(1-smooth)+freqs*smooth
    def rotate(value, positions):
        angles = positions[:, None]*freqs
        phase = torch.polar(torch.ones_like(angles), angles)
        tail = torch.view_as_complex(value[..., -rd:].float().reshape(len(value), rd//2, 2))
        value[..., -rd:] = torch.view_as_real(tail*phase).flatten(-2).to(torch.bfloat16)
    rotate(q, torch.full((len(q),), n-1))
    rotate(k, torch.arange(n))
    qc, qs = quantize_fp4(q)
    kc, ks = quantize_fp4(k)
    report = dict(layer=20, model=lock['model'], revision=lock['revision'],
        input_scope='Independent seeded Gaussian x[1,5120], qr[1,1280], latent[N,512]; real pretrained indexer weights; NOT full-model hidden states or text traces',
        projection_scope='CPU BF16 linear + readable FP8 projection/dequantization + official-formula RMSNorm/RoPE/FP4 port; NOT execution of TileLang CUDA kernels',
        negative_head_weights=int((weights < 0).sum()), positive_head_weights=int((weights > 0).sum()),
        query_scale_byte_range=[int(qs.min()), int(qs.max())], key_scale_byte_range=[int(ks.min()), int(ks.max())],
        tensor_sha256={name: desc['sha256'] for name, desc in lock['tensors'].items()})
    activations = dict(x_bf16=x.view(torch.uint16).numpy(), qr_bf16=qr.view(torch.uint16).numpy(),
                       latent_bf16=latent.view(torch.uint16).numpy())
    return (qc, qs, kc, ks, weights.view(torch.uint16).numpy()), report, activations


def fixture(name, arrays, k=512, candidate=None, scope='synthetic arithmetic fixture', **extra):
    qc, qs, kc, ks, weights = arrays
    n, d = kc.shape
    candidate = np.ones(n, bool) if candidate is None else np.asarray(candidate, bool)
    return dict(schema_version=1, name=name, contract=oracle.CONTRACT, heads=len(qc), dimension=d,
        positions=n, topk=k, query_codes_hex=oracle.pack_e2m1(qc).hex(),
        key_codes_hex=oracle.pack_e2m1(kc).hex(), query_scales_hex=qs.astype(np.uint8).tobytes().hex(),
        key_scales_hex=ks.astype(np.uint8).tobytes().hex(), weights_bf16_le_hex=weights.astype('<u2').tobytes().hex(),
        candidate_mask_hex=np.packbits(candidate, bitorder='little').tobytes().hex(), input_scope=scope, **extra)


def torch_comparison(case, official):
    if case['expected']['status'] != 'OK':
        return None
    qc, qs, kc, ks, weights, mask = oracle.fixture_arrays(case)
    q, k = dequantize(qc, qs), dequantize(kc, ks)
    w = torch.from_numpy(weights.copy()).view(torch.bfloat16).float()
    refbits = np.asarray([0 if v is None else int(v, 16) for v in case['expected']['scores_hex']], np.uint32)
    ref = refbits.view(np.float32).astype(np.float64)
    expected_set = set(case['expected']['indices_score_order'])
    output = {}
    for mode, dtype in [('fp32', torch.float32), ('bf16_demo', torch.bfloat16)]:
        value = official(q.to(dtype)[None, None], k.to(dtype)[None], w.to(dtype)[None, None]).flatten().float().numpy()
        if not np.isfinite(value[mask]).all():
            output[mode] = dict(finite=False, scope='Expected possible overflow in reference expression; oracle fixture retains its own explicit error contract')
            continue
        score = torch.from_numpy(value.copy()).masked_fill(~torch.from_numpy(mask), -torch.inf)
        actual = set(score.topk(min(case['topk'], int(mask.sum()))).indices.tolist())
        error = value[mask].astype(np.float64)-ref[mask]
        cutoff = min((ref[i] for i in expected_set), default=0)
        tie_only = all(ref[i] == cutoff for i in actual ^ expected_set)
        output[mode] = dict(finite=True, max_abs_error=float(np.max(np.abs(error), initial=0)),
            relative_l2_error=float(np.linalg.norm(error)/max(np.linalg.norm(ref[mask]), 1e-300)),
            topk_symmetric_difference=len(actual ^ expected_set), difference_only_oracle_cutoff_ties=tie_only,
            bitwise_equal_scores=int(np.sum(value[mask].view(np.uint32) == refbits[mask])), evaluated_scores=int(mask.sum()))
    return output


def emit_c_header(path, full, reindex):
    qc, qs, kc, ks, w, _ = oracle.fixture_arrays(full)
    qrows = [oracle.pack_e2m1(row)+sc.tobytes()+np.asarray([weight], dtype='<u2').tobytes()+bytes(26)
             for row, sc, weight in zip(qc, qs, w)]
    krows = [oracle.pack_e2m1(row)+sc.tobytes()+bytes(28) for row, sc in zip(kc, ks)]
    lines = ['/* Generated by research/generate_inputs.py. DO NOT hand edit.',
        ' * CSA2 real layer20 pretrained indexer weights + seeded RANDOM activations.',
        ' * Not text-derived, not a full-model trace, not CUDA bit-exact.',
        ' * Source: deepseek-ai/DeepSeek-V4.1-Flash revision dba1be0a40aa45a94ad051997016db3960a90277.',
        ' * Upstream source/tensor hashes: research/csa2_sources.lock.json.',
        ' * Arithmetic: CSA2_FP4_G32_FP32_RNE_ORDERED_V1. Records physically padded to 96 B.',
        ' * Expected results are sorted by position, and ties choose smaller index. */',
        '#ifndef CSA2_REAL_WEIGHTS_FIXTURE_H', '#define CSA2_REAL_WEIGHTS_FIXTURE_H', '#include <stdint.h>',
        '#define SG_REAL_HEADS 32', '#define SG_REAL_KEYS 64', '#define SG_REAL_TOPK 8', '#define SG_REAL_NCAND 16']
    for name, rows in [('sg_real_q', qrows), ('sg_real_k', krows)]:
        lines.append('static const uint8_t %s[%d][96] = {'%(name, len(rows)))
        lines.extend('  {'+','.join('0x%02x'%b for b in row)+'},' for row in rows)
        lines.append('};')
    def u32(name, vals):
        lines.append('static const uint32_t %s[%d] = {%s};'%(name, len(vals), ','.join('0x%08xu'%x for x in vals)))
    for prefix, case in [('sg_real_', full), ('sg_real_reindex_', reindex)]:
        ids = case['expected']['indices_position_order']
        u32(prefix+'expected_index', ids)
        u32(prefix+'expected_score', [int(case['expected']['scores_hex'][i], 16) for i in ids])
    u32('sg_real_candidate_ids', np.flatnonzero(oracle.fixture_arrays(reindex)[-1]).tolist())
    lines += ['#endif', '']
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text('\n'.join(lines))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--reference', type=Path, default=ROOT/'results/research/reference')
    ap.add_argument('--out', type=Path, default=ROOT/'results/research/inputs')
    ap.add_argument('--seed', type=int, default=20260922)
    args = ap.parse_args()
    torch.set_num_threads(4)
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'manifest.json').unlink(missing_ok=True)
    sources = [Path(__file__).resolve(), Path(oracle.__file__).resolve(), ROOT/'research/csa2_sources.lock.json',
               args.reference/'manifest.json', args.reference/'inference/model.py', args.reference/'inference/kernel.py',
               args.reference/'inference/config.json']
    locked = {str(p.relative_to(ROOT)): sha(p) for p in sources}
    h, d = 32, 128
    def random_arrays(n):
        qc = rng.integers(0, 16, (h, d), dtype=np.uint8)
        kc = rng.integers(0, 16, (n, d), dtype=np.uint8)
        qs = rng.integers(122, 131, (h, 4), dtype=np.uint8)
        ks = rng.integers(122, 131, (n, 4), dtype=np.uint8)
        weights = torch.from_numpy(rng.standard_normal(h).astype(np.float32)).to(torch.bfloat16).view(torch.uint16).numpy()
        return qc, qs, kc, ks, weights
    def zero_arrays(n):
        return (np.zeros((h, d), np.uint8), np.full((h, 4), 127, np.uint8),
                np.zeros((n, d), np.uint8), np.full((n, 4), 127, np.uint8), np.full(h, 0x3f80, np.uint16))
    cases = [fixture('random-small-k8', random_arrays(24), k=8, official_parameter_variant=True),
             fixture('random-top512', random_arrays(600)),
             fixture('zero-ties-top512', zero_arrays(520))]
    a = list(random_arrays(80)); a[-1] |= 0x8000
    cases.append(fixture('negative-head-weights', a, k=32, official_parameter_variant=True))
    a = list(zero_arrays(4)); a[0][0, 0] = 1; a[1][0, 0] = 53; a[2][:, 0] = 1
    a[3][:, 0] = [53, 54, 55, 56]; a[4][1:] = 0
    cases.append(fixture('subnormal-underflow', a, k=4, official_parameter_variant=True))
    a = list(zero_arrays(3)); a[0][0, :] = 2; a[2][0, :32] = 2; a[2][0, 32:64] = 10
    a[2][1, :32] = 10; a[2][1, 32:64] = 2; a[2][2, :32] = 2; a[4][1:] = 0
    cases.append(fixture('cross-group-cancellation', a, k=3, official_parameter_variant=True))
    a = list(random_arrays(1024)); candidate = (np.arange(1024)//8) % 3 != 1
    candidate[-8:] = True
    cases.append(fixture('reindex-sparse-top512', a, candidate=candidate,
        candidate_scope='Synthetic block-aligned source candidate mask; not claimed to originate from a full model source layer'))
    cases.append(fixture('source-block-pool-small', random_arrays(81), k=32, candidate_source=True,
        candidate_block_size=8, candidate_topk_blocks=4, official_parameter_variant=True))
    real, projection, activations = true_weight_inputs(args.reference, rng, 640)
    cases.append(fixture('pretrained-layer20-random-activation-top512', real,
        scope=projection['input_scope'], projection=projection, candidate_source=True))
    np.savez_compressed(args.out/'projection_random_inputs.npz', **activations)
    real64, projection64, activations64 = true_weight_inputs(args.reference, rng, 64)
    cases.append(fixture('pretrained-layer20-small-full', real64, k=8,
        scope=projection64['input_scope'], projection=projection64, official_parameter_variant=True))
    cand64 = np.zeros(64, bool); cand64[8:16] = True; cand64[56:64] = True
    cases.append(fixture('pretrained-layer20-small-reindex', real64, k=8, candidate=cand64,
        scope=projection64['input_scope'], projection=projection64, official_parameter_variant=True,
        candidate_scope='Two explicit block8 ranges [8,16), [56,64); software-produced test mask, NOT claimed official Top2048 output at N64'))
    np.savez_compressed(args.out/'projection_random_inputs_small.npz', **activations64)
    a = list(zero_arrays(1)); a[1][0, 0] = 255
    cases.append(fixture('invalid-e8m0-nan', a, k=1))
    a = list(zero_arrays(1)); a[4][0] = 0x7f80
    cases.append(fixture('invalid-bf16-infinity', a, k=1))
    a = list(zero_arrays(1)); a[4][0] = 0x7fc0
    cases.append(fixture('invalid-bf16-nan', a, k=1))
    a = list(zero_arrays(1)); a[0][0, 0] = 7; a[2][0, 0] = 7; a[1][0, 0] = 254; a[3][0, 0] = 254
    cases.append(fixture('group-overflow', a, k=1))
    a = list(zero_arrays(1)); a[0][0, :32] = 7; a[2][0, :32] = 7; a[4][0] = 0x7f7f
    cases.append(fixture('weighted-overflow', a, k=1))
    official, lines = official_score_function(args.reference/'inference/model.py')
    records = []
    for case in cases:
        begin = time.monotonic()
        case['expected'] = oracle.evaluate_fixture(case)
        case['torch_comparison'] = torch_comparison(case, official)
        case['producer_seed'] = args.seed
        path = args.out/(case['name']+'.json')
        path.write_text(json.dumps(case, indent=2)+'\n')
        # Hardware transport payload: query has three contiguous planes; each
        # shared K record is packed64 + scale4. No BF16-expanded cache traffic.
        wire = args.out/'wire'/case['name']; wire.mkdir(parents=True, exist_ok=True)
        qc, qs, kc, ks, w, mask = oracle.fixture_arrays(case)
        (wire/'query.bin').write_bytes(oracle.pack_e2m1(qc)+qs.tobytes()+w.astype('<u2').tobytes())
        (wire/'keys.bin').write_bytes(b''.join(oracle.pack_e2m1(row)+sc.tobytes() for row, sc in zip(kc, ks)))
        (wire/'candidates.bin').write_bytes(bytes.fromhex(case['candidate_mask_hex']))
        # Native AXI256 wrapper layout, separately named and physically padded.
        (wire/'query_axi96.bin').write_bytes(b''.join(oracle.pack_e2m1(row)+sc.tobytes()+
            np.asarray([weight], dtype='<u2').tobytes()+bytes(26) for row, sc, weight in zip(qc, qs, w)))
        (wire/'keys_axi96.bin').write_bytes(b''.join(oracle.pack_e2m1(row)+sc.tobytes()+bytes(28) for row, sc in zip(kc, ks)))
        (wire/'candidate_ids_u32le.bin').write_bytes(np.flatnonzero(mask).astype('<u4').tobytes())
        (wire/'expected.json').write_text(json.dumps(case['expected'], indent=2)+'\n')
        records.append(dict(name=case['name'], path=str(path.relative_to(ROOT)), sha256=sha(path),
            status=case['expected']['status'], positions=case['positions'], heads=h, dimension=d,
            topk=case['topk'], candidate_positions=int(mask.sum()),
            wire={p.name: dict(path=str(p.relative_to(ROOT)), bytes=p.stat().st_size, sha256=sha(p)) for p in sorted(wire.iterdir())},
            oracle_seconds=time.monotonic()-begin, torch_comparison=case['torch_comparison']))
        print(case['name'], case['expected']['status'], '%.3fs'%records[-1]['oracle_seconds'], flush=True)
    assert cases[2]['expected']['indices_score_order'] == list(range(512))
    assert cases[4]['expected']['scores_hex'] == ['00000000', '00000001', '00000002', '00000004']
    assert cases[5]['expected']['scores_hex'] == ['00000000', '00000000', '42000000']
    assert sum(c['expected']['status'] == 'OK' for c in cases) == 11
    assert sum(c['expected']['status'] == 'FORMAT_ERROR' for c in cases) == 3
    assert sum(c['expected']['status'] == 'ARITHMETIC_ERROR' for c in cases) == 2
    assert locked == {p: sha(ROOT/p) for p in locked}
    header_path = ROOT/'research/fixtures/csa2_real_weights_fixture.h'
    emit_c_header(header_path, cases[9], cases[10])
    manifest = dict(passed=True, schema_version=1, contract=oracle.CONTRACT, seed=args.seed,
        locked_sha256=locked, cases=records, torch_version=torch.__version__, numpy_version=np.__version__,
        python_version=sys.version, cpu_threads=4,
        official_executed_statements=dict(path=str((args.reference/'inference/model.py').relative_to(ROOT)), lines=lines,
            scope='Two official torch index_score assignment statements AST-extracted verbatim, CPU FP32 and BF16 execution; projection/quantizer are readable ports; no TileLang/CUDA execution'),
        projection_random_inputs=dict(path=str((args.out/'projection_random_inputs.npz').relative_to(ROOT)), sha256=sha(args.out/'projection_random_inputs.npz')),
        projection_random_inputs_small=dict(path=str((args.out/'projection_random_inputs_small.npz').relative_to(ROOT)), sha256=sha(args.out/'projection_random_inputs_small.npz')),
        c_header=dict(path=str(header_path.relative_to(ROOT)), sha256=sha(header_path), full_case=cases[9]['name'], reindex_case=cases[10]['name']),
        wire_layout=dict(query_bytes=2240, query_planes='2048 packed FP4 + 128 E8M0 + 64 BF16 little endian',
            key_record_bytes=68, key_record='64 packed FP4 followed by 4 E8M0', candidates='LSB-first bitmap',
            native_axi_record_bytes=96, native_query='64 packed FP4 + 4 scales + 2 BF16 weight + 26 zero bytes per head',
            native_key='64 packed FP4 + 4 scales + 28 zero bytes per position', native_candidates='Ascending unique uint32 little-endian expanded IDs',
            fp4_byte_order='even element low nibble; odd element high nibble'),
        claims=dict(full_model_run=False, real_text_activations=False, cuda_bit_exact=False,
            pretrained_indexer_weights=True, algorithm_novelty=False))
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    print(json.dumps(dict(passed=True, cases=len(cases), output=str(args.out))))


if __name__ == '__main__':
    main()
