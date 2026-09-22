#!/usr/bin/env python3
"""Fresh Verilator build and source-bound additional wrapper review evidence."""
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT/'results/research/wrapper-review'


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT/'summary.json').unlink(missing_ok=True)
    files = ['rtl/sparse_gate/sg_fp32_pkg.sv', 'rtl/sparse_gate/sg_index_core.sv',
        'rtl/sparse_gate_axi/sparse_gate_dma.sv', 'rtl/sparse_gate_axi/sparse_gate_axi.sv',
        'rtl/sparse_gate_axi/tests/test_axi.cpp', 'research/review/test_wrapper_edges.cpp',
        'research/review/run_wrapper_review.py']
    locked = {p: sha(ROOT/p) for p in files}
    obj = OUT/'obj'
    command = ['verilator', '--cc', '--exe', '--build', '-j', '4', '-Wno-fatal',
        '--top-module', 'sparse_gate_axi', '--Mdir', str(obj), '-CFLAGS', '-std=c++17 -O2'] + [str(ROOT/p) for p in files[:4]]+[str(ROOT/files[5])]
    with (OUT/'build.log').open('w') as log:
        subprocess.run(command, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, check=True)
    binary = obj/'Vsparse_gate_axi'
    run = subprocess.run([str(binary)], cwd=ROOT, text=True, capture_output=True)
    (OUT/'test.log').write_text(run.stdout+run.stderr)
    assert run.returncode == 0 and 'PASS EXTRA_WRAPPER_EDGE_REVIEW' in run.stdout
    assert locked == {p: sha(ROOT/p) for p in files}
    checks = re.findall(r'^CHECK (.+) PASS$', run.stdout, re.M)
    report = dict(passed=True, source_sha256=locked, command=command,
        verilator=subprocess.check_output(['verilator', '--version'], text=True).strip(),
        compiler=subprocess.check_output(['g++', '--version'], text=True).splitlines()[0],
        binary_sha256=sha(binary), log_sha256=sha(OUT/'test.log'), build_log_sha256=sha(OUT/'build.log'),
        total_cycles=int(re.search(r'PASS EXTRA_WRAPPER_EDGE_REVIEW cycles=(\d+)', run.stdout).group(1)),
        checks=checks, observation=dict(illegal_command_retains_committed_cache=True,
        oracle_full_cache_format_validation_stricter_than_physical_reindex=True),
        scope='Fresh RTL simulation, additional review sequences use original clock/memory BFM; no native link/mem_sim/PPA claim')
    (OUT/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    evidence = ROOT/'evidence/review';evidence.mkdir(parents=True, exist_ok=True)
    (evidence/'wrapper.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, cycles=report['total_cycles'], checks=checks)))


if __name__ == '__main__':
    main()
