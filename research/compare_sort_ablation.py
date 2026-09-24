#!/usr/bin/env python3
"""Compare two audited Vortex FULL commands using the same fixed fixture."""
import argparse
import csv
import json
from collections import Counter
from pathlib import Path


def load(case, name):
    return json.loads((case / name).read_text())


def link_requests_during_command(case, command):
    regions = {
        'q': (0x190010000, 0x190010000 + 32 * 96),
        'k': (0x190012000, 0x190012000 + 640 * 96),
        'kv': (0x190024000, 0x190024000 + 640 * 288),
        'out': (0x190053000, 0x190053000 + 512 * 32),
        'gather': (0x190059000, 0x190059000 + 512 * 288),
        'mmio': (0x1900f0000, 0x1900f1000),
    }
    counts = Counter()
    with (case / 'axi_flit_path.csv').open() as stream:
        for row in csv.DictReader(stream):
            if row['message'] not in ('WriteReq', 'ReadReq'):
                continue
            tick = int(row['axi_tick_fs'])
            if not command['start_tick_fs'] <= tick <= command['end_tick_fs']:
                continue
            address = int(row['address'])
            region = next((name for name, (lo, hi) in regions.items()
                           if lo <= address < hi), 'other')
            counts[region] += 1
    return dict(counts)


def compare(baseline: Path, optimized: Path):
    b, o = (load(case, 'vortex_gate_check.json') for case in (baseline, optimized))
    bp, op = (load(case, 'gate_phase_cycles.json') for case in (baseline, optimized))
    for record in (b, o):
        assert record['passed'] and record['host_mmio_requests'] == 0
        assert record['source'] == 'Vortex command-processor DMA'
        cmd = record['rtl_command']
        assert (cmd['mode'], cmd['heads'], cmd['nkeys'], cmd['topk'],
                cmd['status'], cmd['score_count'], cmd['result_count']) == (0, 32, 640, 512, 2, 640, 512)
    assert b['source_files'] == o['source_files'], 'workload or checker input changed'
    assert b['rtl_command']['reads'] == o['rtl_command']['reads'] == 6624
    assert b['rtl_command']['writes'] == o['rtl_command']['writes'] == 5120
    assert b['binary_bytes'] == o['binary_bytes']
    for check, phase in ((b, bp), (o, op)):
        assert check['rtl_command']['cycles'] == phase['command_cycles']
        assert check['model_build_id'] == phase['model_build_id']
    old_sort = bp['state_cycles']['RESULTS'] + bp['state_cycles']['INSERT']
    new_sort = (op['state_cycles']['RESULTS'] + op['state_cycles']['SORT_SIFT'] +
                op['state_cycles']['SORT_TAKE'])
    old_cycles, new_cycles = bp['command_cycles'], op['command_cycles']
    assert new_cycles < old_cycles and new_sort < old_sort
    baseline_link = link_requests_during_command(baseline, b['rtl_command'])
    optimized_link = link_requests_during_command(optimized, o['rtl_command'])
    assert all(link.get(name, 0) == 0 for link in (baseline_link, optimized_link)
               for name in ('q', 'k', 'kv', 'out', 'gather'))
    return {
        'schema': 'vortex_sort_ablation_v1',
        'passed': True,
        'scope': 'One fixed H32/N640/K512 FULL command; trained indexer weights and seeded synthetic activations; same Vortex CP DMA, memory and link configuration',
        'fixture': 'research/fixtures/csa2_top512_fixture.h',
        'baseline_case': str(baseline),
        'optimized_case': str(optimized),
        'baseline_model_build_id': b['model_build_id'],
        'optimized_model_build_id': o['model_build_id'],
        'baseline_command_cycles': old_cycles,
        'optimized_command_cycles': new_cycles,
        'cycles_saved': old_cycles - new_cycles,
        'command_cycle_reduction_fraction': (old_cycles - new_cycles) / old_cycles,
        'baseline_position_sort_cycles': old_sort,
        'optimized_position_sort_cycles': new_sort,
        'position_sort_cycles_saved': old_sort - new_sort,
        'dma_read_beats_each': 6624,
        'dma_write_beats_each': 5120,
        'selected_records_checked_each': 512,
        'gather_bytes_checked_each': 512 * 288,
        'source': 'Vortex command-processor DMA',
        'baseline_vortex_mmio_requests': b['vortex_mmio_requests'],
        'optimized_vortex_mmio_requests': o['vortex_mmio_requests'],
        'host_mmio_requests_each': 0,
        'link_aou_wave_guest_checks_passed_each': True,
        'baseline_ucie_requests_during_command_by_region': baseline_link,
        'optimized_ucie_requests_during_command_by_region': optimized_link,
        'ucie_region_scope': 'Only command busy interval and submitted AXI requests; fixture upload and result readback occur outside this interval',
        'physical_area_or_energy_measured': False,
        'baseline_state_cycles': {key: bp['state_cycles'][key] for key in
                                  ('KEYWAIT', 'KLOAD', 'KWAIT', 'RESULTS', 'INSERT',
                                   'GWAIT', 'GWRITEWAIT')},
        'optimized_state_cycles': {key: op['state_cycles'][key] for key in
                                   ('KEYWAIT', 'KLOAD', 'KWAIT', 'RESULTS', 'SORT_SIFT',
                                    'SORT_TAKE', 'GWAIT', 'GWRITEWAIT')},
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('optimized', type=Path)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = compare(args.baseline, args.optimized)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
