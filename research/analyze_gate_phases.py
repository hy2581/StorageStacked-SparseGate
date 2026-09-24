#!/usr/bin/env python3
"""Count SparseGate wrapper cycles by RTL state from its VCD trace.

This reads the actual state signal, including stalls, rather than estimating
latency from DMA counts or the independent scoring-core testbench.
"""
import argparse
import json
from collections import defaultdict
from pathlib import Path


STATES = (
    'IDLE START JOB QREQ QWAIT QLOAD NEXT_KEY CREQ CWAIT CSELECT '
    'KREQ KWAIT KLOAD KEYSTART KEYWAIT END RESULTS INSERT OUTREQ OUTWAIT '
    'GREAD GWAIT GWRITE GWRITEWAIT ADVANCE FINISH ERROR SORT_SIFT SORT_TAKE'
).split()


def analyze(case: Path):
    wave = case / 'sparse_gate.vcd'
    protocol = json.loads((case / 'protocol_summary.json').read_text())
    period = protocol['period_ticks']
    code = None
    tick = 0
    previous_state = None
    previous_tick = 0
    durations = defaultdict(int)
    entries = defaultdict(int)
    with wave.open() as stream:
        for line in stream:
            fields = line.split()
            if len(fields) >= 5 and fields[:2] == ['$var', 'wire'] and fields[4] == 'es':
                assert code is None
                code = fields[3]
            if '$enddefinitions' in line:
                break
        assert code is not None, 'engine state missing from VCD'
        for line in stream:
            if line.startswith('#'):
                tick = int(line[1:])
            elif line.startswith('b'):
                fields = line.split()
                if len(fields) == 2 and fields[1] == code:
                    state = int(fields[0][1:], 2)
                    assert state < len(STATES)
                    if previous_state is not None:
                        durations[STATES[previous_state]] += tick - previous_tick
                    previous_state, previous_tick = state, tick
                    entries[STATES[state]] += 1
    assert previous_state == 0, 'trace ended with active gate command'
    remainders = {state: value % period for state, value in durations.items()
                  if state != 'IDLE' and value % period}
    assert not remainders, f'nonintegral state durations: {remainders}'
    cycles = {state: durations[state] // period for state in STATES if durations[state]}
    command_cycles = sum(value for state, value in cycles.items() if state != 'IDLE')
    summary = json.loads((case / 'sparse_gate_summary.json').read_text())
    assert summary['drained']
    return {
        'schema': 'gate_rtl_phase_cycles_v1',
        'scope': 'Wrapper RTL state occupancy; includes stalls, excludes guest startup and input upload',
        'period_fs': period,
        'command_cycles': command_cycles,
        'state_cycles': cycles,
        'state_entries': {state: entries[state] for state in STATES if entries[state]},
        'model_build_id': summary['build_id'],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('case', type=Path)
    parser.add_argument('--out', type=Path)
    args = parser.parse_args()
    result = analyze(args.case)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
