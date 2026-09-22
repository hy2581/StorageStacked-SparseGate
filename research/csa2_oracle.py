#!/usr/bin/env python3
"""Independent CSA2-compatible indexer oracle with integer-defined FP32 RNE.

The arithmetic contract is deliberately explicit, not CUDA/Torch bit equality:
exact 32-element E2M1 integer dot -> FP32 scaled group -> ordered four-group
FP32 sum -> ReLU -> signed BF16 weight FP32 multiply -> ordered head FP32 sum.
Finite input overflow is an arithmetic error; subnormals are retained.
"""
import json
from pathlib import Path
import struct

import numpy as np

MAGNITUDES_X2 = (0, 1, 2, 3, 4, 6, 8, 12)
CONTRACT = 'CSA2_FP4_G32_FP32_RNE_ORDERED_V1'


class FormatError(ValueError):
    pass


class ArithmeticOverflow(ArithmeticError):
    pass


def rounded_integer(n, shift):
    """Round nonnegative n*2**shift to integer, ties to even."""
    assert n >= 0
    if shift >= 0:
        return n << shift
    bits = -shift
    q, rem = divmod(n, 1 << bits)
    half = 1 << (bits-1)
    return q + (rem > half or (rem == half and q & 1))


def round_fp32(mantissa, exponent, zero_sign=0):
    """Exact signed integer times power-of-two -> IEEE binary32 RNE bits."""
    if not mantissa:
        return (zero_sign & 1) << 31
    sign = int(mantissa < 0)
    n = abs(int(mantissa))
    log = n.bit_length()-1+int(exponent)
    if log < -126:
        frac = rounded_integer(n, int(exponent)+149)
        assert frac <= 1 << 23
        return (sign << 31) | frac
    significand = rounded_integer(n, int(exponent)-(log-23))
    if significand == 1 << 24:
        significand >>= 1
        log += 1
    if log > 127:
        raise ArithmeticOverflow('finite input rounds to FP32 infinity')
    assert 1 << 23 <= significand < 1 << 24
    return (sign << 31) | ((log+127) << 23) | (significand-(1 << 23))


def dyadic_fp32(bits):
    bits = int(bits)
    exp, frac = (bits >> 23) & 255, bits & 0x7fffff
    if exp == 255:
        raise FormatError('nonfinite binary32 operand')
    m, e = (frac, -149) if exp == 0 else ((1 << 23) | frac, exp-150)
    return (-m if bits >> 31 else m), e


def add_fp32(a, b):
    am, ae = dyadic_fp32(a)
    bm, be = dyadic_fp32(b)
    exp = min(ae, be)
    m = (am << (ae-exp)) + (bm << (be-exp))
    # RNE cancellation gives +0; only -0 + -0 retains -0.
    return round_fp32(m, exp, zero_sign=int((a & b) >> 31))


def multiply_fp32(a, b):
    am, ae = dyadic_fp32(a)
    bm, be = dyadic_fp32(b)
    return round_fp32(am*bm, ae+be, zero_sign=(a ^ b) >> 31)


def bf16_to_fp32(bits):
    bits = int(bits)
    if not 0 <= bits <= 65535 or (bits >> 7) & 255 == 255:
        raise FormatError('nonfinite or invalid BF16 head weight')
    return bits << 16


def fp32_to_float(bits):
    return struct.unpack('<f', struct.pack('<I', int(bits)))[0]


def fp32_order_key(bits):
    """Monotone integer key for finite floats, with +/-0 equal."""
    bits = int(bits)
    if bits & 0x7fffffff == 0:
        bits = 0
    return (~bits & 0xffffffff) if bits >> 31 else bits ^ 0x80000000


def unpack_e2m1(data, elements):
    raw = np.frombuffer(data, dtype=np.uint8)
    codes = np.empty(len(raw)*2, dtype=np.uint8)
    codes[0::2] = raw & 15
    codes[1::2] = raw >> 4
    assert elements <= len(codes) <= elements+1
    return codes[:elements]


def pack_e2m1(codes):
    codes = np.asarray(codes, dtype=np.uint8).reshape(-1)
    assert np.all(codes < 16)
    if len(codes) % 2:
        codes = np.append(codes, np.uint8(0))
    return (codes[0::2] | (codes[1::2] << 4)).tobytes()


def e2m1_integers(codes):
    codes = np.asarray(codes)
    if np.any(codes < 0) or np.any(codes > 15):
        raise FormatError('invalid E2M1 nibble')
    mag = np.take(np.asarray(MAGNITUDES_X2, dtype=np.int32), codes & 7)
    return np.where(codes & 8, -mag, mag)


def scores(q_codes, q_scales, k_codes, k_scales, weights_bf16, candidates=None):
    q, k = e2m1_integers(q_codes), e2m1_integers(k_codes)
    qs, ks = np.asarray(q_scales), np.asarray(k_scales)
    h, d = q.shape
    n, kd = k.shape
    if d != kd or d % 32 or qs.shape != (h, d//32) or ks.shape != (n, d//32):
        raise FormatError('shape mismatch')
    if np.any(qs < 0) or np.any(qs > 254) or np.any(ks < 0) or np.any(ks > 254):
        raise FormatError('E8M0 byte 255 is NaN, not a valid scale')
    if len(weights_bf16) != h:
        raise FormatError('head weight count mismatch')
    weights = [bf16_to_fp32(w) for w in weights_bf16]
    candidates = np.ones(n, dtype=bool) if candidates is None else np.asarray(candidates, dtype=bool)
    assert candidates.shape == (n,)
    # Each np integer matmul is exact (maximum absolute sum 32*12*12=4608).
    dots = [k[:, g*32:(g+1)*32] @ q[:, g*32:(g+1)*32].T for g in range(d//32)]
    out = [None]*n
    for s in np.flatnonzero(candidates):
        total = 0
        for head in range(h):
            dot = 0
            for group in range(d//32):
                # Each code was doubled; undo x4 in the product, then apply both scales.
                term = round_fp32(int(dots[group][s, head]), int(qs[head, group])+int(ks[s, group])-256)
                dot = add_fp32(dot, term)
            if dot >> 31:
                dot = 0
            total = add_fp32(total, multiply_fp32(dot, weights[head]))
        out[s] = total
    return out


def stable_topk(score_bits, k):
    if k < 0:
        raise FormatError('negative K')
    valid = [i for i, s in enumerate(score_bits) if s is not None]
    return sorted(valid, key=lambda i: (-fp32_order_key(score_bits[i]), i))[:k]


def select_candidate_blocks(score_bits, block_size=8, topk_blocks=2048, visible=None):
    """Source-layer block-max pool with mandatory newest reachable block."""
    n = len(score_bits)
    visible = n if visible is None else visible
    assert 0 <= visible <= n and block_size > 0 and topk_blocks > 0
    if not visible:
        return [False]*n, []
    ranked = []
    last = (visible-1)//block_size
    for b in range((visible+block_size-1)//block_size):
        valid = [s for s in score_bits[b*block_size:min((b+1)*block_size, visible)] if s is not None]
        if valid:
            key = max(map(fp32_order_key, valid))
            ranked.append((b, key))
    blocks = [b for b, _ in sorted(ranked, key=lambda z: (z[0] != last, -z[1], z[0]))[:topk_blocks]]
    keep = set(blocks)
    return [i < visible and i//block_size in keep for i in range(n)], blocks


def fixture_arrays(case):
    h, d, n = case['heads'], case['dimension'], case['positions']
    q = unpack_e2m1(bytes.fromhex(case['query_codes_hex']), h*d).reshape(h, d)
    k = unpack_e2m1(bytes.fromhex(case['key_codes_hex']), n*d).reshape(n, d)
    qs = np.frombuffer(bytes.fromhex(case['query_scales_hex']), dtype=np.uint8).reshape(h, d//32)
    ks = np.frombuffer(bytes.fromhex(case['key_scales_hex']), dtype=np.uint8).reshape(n, d//32)
    w = np.frombuffer(bytes.fromhex(case['weights_bf16_le_hex']), dtype='<u2')
    cand = np.unpackbits(np.frombuffer(bytes.fromhex(case['candidate_mask_hex']), dtype=np.uint8), bitorder='little')[:n].astype(bool)
    return q, qs, k, ks, w, cand


def evaluate_fixture(case):
    try:
        out = scores(*fixture_arrays(case))
        ids = stable_topk(out, case['topk'])
        result = dict(status='OK', scores_hex=[None if x is None else '%08x'%x for x in out],
                      indices_score_order=ids, indices_position_order=sorted(ids))
        if case.get('candidate_source'):
            mask, blocks = select_candidate_blocks(out, case.get('candidate_block_size', 8),
                case.get('candidate_topk_blocks', 2048), case.get('visible_positions', len(out)))
            result['source_candidate_mask_hex'] = np.packbits(mask, bitorder='little').tobytes().hex()
            result['source_candidate_blocks_score_order'] = blocks
        return result
    except FormatError as e:
        return dict(status='FORMAT_ERROR', reason=str(e))
    except ArithmeticOverflow as e:
        return dict(status='ARITHMETIC_ERROR', reason=str(e))


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('fixture', type=Path)
    args = ap.parse_args()
    print(json.dumps(evaluate_fixture(json.loads(args.fixture.read_text())), indent=2))
