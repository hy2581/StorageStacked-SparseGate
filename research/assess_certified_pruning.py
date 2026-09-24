#!/usr/bin/env python3
"""Explore a conservative head-pruning certificate on an existing CSA2 fixture.

This is an oracle-side feasibility study, not an RTL implementation or a cycle model.
It deliberately uses no file digests and reports source paths and input dimensions.
"""
import argparse
import heapq
import json
import random
from pathlib import Path

import numpy as np

from csa2_oracle import (ArithmeticOverflow, add_fp32, bf16_to_fp32,
                         dyadic_fp32, e2m1_integers, fixture_arrays,
                         fp32_order_key, multiply_fp32, round_fp32,
                         stable_topk)


ROOT = Path(__file__).resolve().parents[1]


def nonnegative_ceil_fp32(mantissa, exponent):
    """Smallest finite binary32 no less than mantissa*2**exponent."""
    if mantissa == 0:
        return 0
    bits = round_fp32(mantissa, exponent)
    rounded_m, rounded_e = dyadic_fp32(bits)
    common = min(exponent, rounded_e)
    if rounded_m << (rounded_e - common) < mantissa << (exponent - common):
        if bits == 0x7f7fffff:
            raise ArithmeticOverflow('bound exceeds finite FP32')
        bits += 1
    return bits


def head_interval(q_l1, k_max, qs, ks, weight_bits):
    """Conservative contribution interval for one weighted ReLU head."""
    dot_upper = 0
    dot_lower = 0
    for g in range(4):
        group_bound = nonnegative_ceil_fp32(
            int(q_l1[g]) * int(k_max[g]), int(qs[g]) + int(ks[g]) - 256)
        dot_upper = add_fp32(dot_upper, group_bound)
        dot_lower = add_fp32(dot_lower, group_bound | 0x80000000)
    # Both signed bounds must remain finite so skipped group arithmetic cannot hide errors.
    weight = bf16_to_fp32(weight_bits)
    if weight & 0x7fffffff == 0:
        return 0, 0
    if weight >> 31:
        return multiply_fp32(dot_upper, weight), 0
    return 0, multiply_fp32(dot_upper, weight)


def score_prefixes(q_int, k_int, qs, ks, weights):
    """Exact RTL-order score after each complete head."""
    total = 0
    prefixes = []
    for h in range(len(weights)):
        dot = 0
        for g in range(4):
            start = 32 * g
            product = int(np.dot(q_int[h, start:start + 32], k_int[start:start + 32]))
            group = round_fp32(product, int(qs[h, g]) + int(ks[g]) - 256)
            dot = add_fp32(dot, group)
        if dot >> 31:
            dot = 0
        total = add_fp32(total, multiply_fp32(dot, bf16_to_fp32(weights[h])))
        prefixes.append(total)
    return prefixes


def assess(fixture, budgets, order_seed):
    q, qs, k, ks, weights, candidate = fixture_arrays(fixture)
    assert q.shape == (32, 128) and k.shape[1] == 128 and candidate.all()
    q_int, k_int = e2m1_integers(q), e2m1_integers(k)
    q_l1 = np.abs(q_int).reshape(32, 4, 32).sum(axis=2)
    k_max = np.abs(k_int).reshape(len(k), 4, 32).max(axis=2)
    order = list(range(len(k)))
    random.Random(order_seed).shuffle(order)
    heaps = {budget: [] for budget in budgets}
    saved_heads = {budget: 0 for budget in budgets}
    pruned_keys = {budget: 0 for budget in budgets}
    checked_keys = {budget: 0 for budget in budgets}
    failed_bounds = 0
    scores = [None] * len(k)
    for i in order:
        prefixes = score_prefixes(q_int, k_int[i], qs, ks[i], weights)
        scores[i] = prefixes[-1]
        bounds = []
        try:
            for h in range(32):
                bounds.append(head_interval(q_l1[h], k_max[i], qs[h], ks[i], int(weights[h])))
        except ArithmeticOverflow:
            bounds = None
            failed_bounds += 1
        for budget, heap in heaps.items():
            cutoff = heap[0] if len(heap) == budget else None
            if cutoff is not None:
                checked_keys[budget] += 1
            if cutoff is not None and bounds is not None:
                for h in range(31):
                    upper, lower = prefixes[h], prefixes[h]
                    try:
                        for lo, hi in bounds[h + 1:]:
                            upper = add_fp32(upper, hi)
                            lower = add_fp32(lower, lo)
                    except ArithmeticOverflow:
                        break
                    # Float monotonicity preserves this interval despite ordered RNE.
                    assert fp32_order_key(lower) <= fp32_order_key(prefixes[-1]) <= fp32_order_key(upper)
                    if (fp32_order_key(upper), -i) <= cutoff:
                        assert (fp32_order_key(prefixes[-1]), -i) <= cutoff
                        saved_heads[budget] += 31 - h
                        pruned_keys[budget] += 1
                        break
            entry = (fp32_order_key(prefixes[-1]), -i)
            if len(heap) < budget:
                heapq.heappush(heap, entry)
            elif entry > heap[0]:
                heapq.heapreplace(heap, entry)
    results = []
    for budget, heap in heaps.items():
        selected = { -entry[1] for entry in heap }
        assert selected == set(stable_topk(scores, budget))
        results.append(dict(topk=budget, keys=len(k), heads=32,
                            checked_keys=checked_keys[budget],
                            certified_rejections=pruned_keys[budget],
                            avoided_head_scores=saved_heads[budget],
                            avoided_fraction_of_all_head_scores=saved_heads[budget] / (len(k) * 32),
                            full_head_scores=len(k) * 32))
    return dict(schema='certified_pruning_feasibility_v1',
                scope='Oracle-side conservative bound on fixed real weights plus synthetic activation; no RTL, online cycles, area or energy measured',
                fixture=fixture['name'], fixture_heads=fixture['heads'],
                fixture_positions=fixture['positions'], order_seed=order_seed,
                inputs_with_unusable_bound=failed_bounds, results=results)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--fixture', type=Path,
                    default=ROOT / 'results/research/inputs/pretrained-layer20-random-activation-top512.json')
    ap.add_argument('--out', type=Path,
                    default=ROOT / 'evidence/research/certified_pruning_feasibility.json')
    ap.add_argument('--budgets', type=int, nargs='+', default=[512, 128, 64])
    args = ap.parse_args()
    fixture = json.loads(args.fixture.read_text())
    assert all(0 < b <= fixture['positions'] for b in args.budgets)
    result = assess(fixture, args.budgets, 1922)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
