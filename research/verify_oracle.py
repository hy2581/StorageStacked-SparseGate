#!/usr/bin/env python3
"""Independent host IEEE and exact-rational checks for the ordered CSA2 oracle."""
import argparse
from fractions import Fraction
import hashlib
import json
from pathlib import Path
import warnings

import numpy as np
import csa2_oracle as oracle

ROOT = Path(__file__).resolve().parent.parent


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def fraction(bits):
    m, e = oracle.dyadic_fp32(bits)
    return Fraction(m) * Fraction(2)**e


def check_round(m, e):
    """Check output's exact rational Voronoi cell, not a duplicate rounder."""
    exact = Fraction(m) * Fraction(2)**e
    threshold = Fraction(2)**128 - Fraction(2)**103
    try:
        got = oracle.round_fp32(m, e)
    except oracle.ArithmeticOverflow:
        assert abs(exact) >= threshold
        return 'overflow'
    mag = got & 0x7fffffff
    target = abs(exact)
    value = fraction(mag)
    # -0 and +0 share the same rounding interval.
    lower = Fraction(0) if mag == 0 else (value + fraction(mag-1))/2
    upper = threshold if mag == 0x7f7fffff else (value + fraction(mag+1))/2
    assert lower <= target <= upper, (m, e, hex(got))
    if target in (lower, upper) and target != 0:
        assert not (mag & 1), (m, e, hex(got), 'not ties-to-even')
    assert int(exact < 0) == int(got >> 31) or exact == 0
    return 'finite'


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'results/research/oracle-audit')
    ap.add_argument('--seed', type=int, default=20260922)
    ap.add_argument('--random-pairs', type=int, default=100000)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'summary.json').unlink(missing_ok=True)
    source = {str(p.resolve().relative_to(ROOT)): sha(p) for p in (Path(__file__), Path(oracle.__file__))}
    rng = np.random.default_rng(args.seed)
    pairs = rng.integers(0, 2**32, (args.random_pairs, 2), dtype=np.uint32)
    pairs = pairs[np.all((pairs >> 23) & 255 != 255, axis=1)]
    values = pairs.view(np.float32)
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', RuntimeWarning)
        adds = (values[:, 0] + values[:, 1]).view(np.uint32)
        muls = (values[:, 0] * values[:, 1]).view(np.uint32)
    counts = dict(add_checked=0, multiply_checked=0, host_overflow_checked=0,
                  rational_round_checked=0, rational_overflow_checked=0)
    for (a, b), expected_add, expected_mul in zip(pairs, adds, muls):
        for name, fn, expected in [('add', oracle.add_fp32, expected_add), ('multiply', oracle.multiply_fp32, expected_mul)]:
            try:
                got = fn(int(a), int(b))
                assert got == int(expected), (name, hex(int(a)), hex(int(b)), hex(got), hex(int(expected)))
            except oracle.ArithmeticOverflow:
                assert int(expected) & 0x7fffffff == 0x7f800000
                counts['host_overflow_checked'] += 1
            counts[name+'_checked'] += 1
    # Independent exact-fraction rounding-cell checks include IEEE corners and
    # large exact products/sums extending well beyond host FP64 precision.
    directed = [(0, 0), (1, -150), (3, -150), (1, -149), (-1, -149),
                (2**24+1, -24), (2**24+3, -24), (2**25-1, 103),
                (2**25-2, 103), (2**25-3, 103)]
    for i in range(5000):
        bits = int(rng.integers(1, 160))
        m = int.from_bytes(rng.bytes((bits+7)//8), 'little') & ((1 << bits)-1)
        if rng.integers(2):
            m = -m
        directed.append((m, int(rng.integers(-330, 160))))
    for m, e in directed:
        kind = check_round(m, e)
        counts['rational_round_checked'] += 1
        counts['rational_overflow_checked'] += int(kind == 'overflow')
    assert oracle.add_fp32(0x80000000, 0x80000000) == 0x80000000
    assert oracle.add_fp32(0x3f800000, 0xbf800000) == 0
    assert oracle.multiply_fp32(0x80000000, 0x3f800000) == 0x80000000
    assert oracle.stable_topk([0x80000000, 0, 0xbf800000, 0x3f800000], 4) == [3, 0, 1, 2]
    for bad in (0x7f80, 0xff80, 0x7fc0, 0x7fff):
        try:
            oracle.bf16_to_fp32(bad)
            assert False
        except oracle.FormatError:
            pass
    # Full official 2048 x 8 pool boundary and mandatory final partial block.
    raw_scores = [oracle.round_fp32(i+1, 0) for i in range(16401)]
    raw_scores[-1] = oracle.round_fp32(-100000, 0)
    mask, blocks = oracle.select_candidate_blocks(raw_scores)
    assert len(blocks) == 2048 and blocks[0] == 2050 and len(set(blocks)) == 2048
    assert sum(mask) == 2047*8+1 and mask[-1] and not any(mask[:24])
    summary = dict(passed=True, seed=args.seed, counts=counts, locked_sha256=source,
        python_numpy_version=np.__version__, mismatches=0,
        candidate_pool_test=dict(positions=16401, block_size=8, topk_blocks=2048,
                                 retained_positions=sum(mask), mandatory_last_block=blocks[0]),
        scope='Independent exact-rational FP32 rounding cells, NumPy host IEEE add/mul, format and stable tie checks; not RTL or CUDA equivalence')
    assert source == {p: sha(ROOT/p) for p in source}
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
