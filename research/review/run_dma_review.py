#!/usr/bin/env python3
"""Compile the standalone DMA RTL and run directed response-error recovery."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'results/research/dma-review'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'summary.json').unlink(missing_ok=True)
    sources = ['rtl/sparse_gate_axi/sparse_gate_dma.sv', 'research/review/tb_dma_review.sv', 'research/review/run_dma_review.py']
    locked = {p: sha(ROOT/p) for p in sources}
    binary = OUT/'dma.vvp'
    command = ['iverilog', '-g2012', '-s', 'tb_dma_review', '-o', str(binary)]+[str(ROOT/p) for p in sources[:2]]
    build = subprocess.run(command, text=True, capture_output=True)
    (OUT/'build.log').write_text(build.stdout+build.stderr)
    assert build.returncode == 0
    run = subprocess.run(['vvp', str(binary)], text=True, capture_output=True)
    (OUT/'test.log').write_text(run.stdout+run.stderr)
    assert run.returncode == 0 and 'PASS DMA_EDGE_REVIEW' in run.stdout
    assert locked == {p: sha(ROOT/p) for p in sources}
    match = re.search(r'PASS DMA_EDGE_REVIEW cycles=(\d+) jobs=(\d+) errors=(\d+) read_beats=(\d+) write_beats=(\d+)', run.stdout)
    report = dict(passed=True, tested_date='2026-09-22', source_sha256=locked, command=command,
        iverilog=subprocess.run(['iverilog', '-V'], text=True, capture_output=True).stdout.splitlines()[0],
        binary_sha256=sha(binary), log_sha256=sha(OUT/'test.log'), build_log_sha256=sha(OUT/'build.log'),
        counts=dict(zip(['cycles','jobs','errors','read_beats','write_beats'], map(int, match.groups()))),
        checks=re.findall(r'^CHECK (.+) PASS$', run.stdout, re.M),
        scope='Standalone real DMA RTL: incorrect RID/BID, a nonlast R beat followed after a gap by last R, RRESP/BRESP, and immediate legal-request recovery. Not general arbitrary AXI violation recovery or native-memory service.')
    (OUT/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    evidence = ROOT/'evidence/review';evidence.mkdir(parents=True, exist_ok=True)
    (evidence/'dma.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, counts=report['counts'])))


if __name__ == '__main__':
    main()
