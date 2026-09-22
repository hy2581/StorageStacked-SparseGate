#!/usr/bin/env python3
"""Export compact, self-contained research evidence outside ignored results/."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def sha(p):
    return hashlib.sha256(Path(p).read_bytes()).hexdigest()


def main():
    base = ROOT/'results/research'
    readback = json.loads((base/'readback/summary.json').read_text())
    inputs = json.loads((base/'inputs/manifest.json').read_text())
    audit = json.loads((base/'oracle-audit/summary.json').read_text())
    lock = json.loads((ROOT/'research/csa2_sources.lock.json').read_text())
    pubs = json.loads((ROOT/'research/publications.lock.json').read_text())
    assert readback['passed'] and inputs['passed'] and audit['passed']
    assert sha(ROOT/readback['manifest_path']) == readback['manifest_sha256']
    assert sha(ROOT/readback['audit_source']) == readback['audit_source_sha256']
    for p, digest in dict(readback['checked_sha256'], **audit['locked_sha256']).items():
        assert sha(ROOT/p) == digest
    compact_cases = []
    for c in inputs['cases']:
        case = json.loads((ROOT/c['path']).read_text())
        compact_cases.append(dict(name=c['name'], fixture_sha256=c['sha256'],
            status=c['status'], heads=c['heads'], dimension=c['dimension'], positions=c['positions'],
            topk=c['topk'], candidate_positions=c['candidate_positions'],
            input_scope=case['input_scope'], torch_comparison=c['torch_comparison'],
            official_parameter_variant=case.get('official_parameter_variant', False)))
    report = dict(schema='sparse_gate_research_evidence_v1', passed=True, verified_date='2026-09-22',
        model=lock['model'], revision=lock['revision'], tensor_payload_bytes=5707008,
        tensor_sha256={k: dict(sha256=v['sha256'], bytes=v['bytes'], metadata=v['safetensors_metadata'],
                              source_url=v['source_url'], http_range=v['range']) for k, v in lock['tensors'].items()},
        source_code_sha256={k: dict(sha256=v['sha256'], url=v['url']) for k, v in lock['files'].items()},
        publications=pubs, arithmetic_contract=inputs['contract'], arithmetic_audit=audit['counts'],
        arithmetic_mismatches=audit['mismatches'], seed=inputs['seed'],
        fixture_cases=compact_cases, readback_cases=readback['cases'], statuses=readback['statuses'],
        readback_checked_files=len(readback['checked_sha256']),
        official_candidate_function_checks=readback['candidate_function_cases'],
        c_header=dict(path=inputs['c_header']['path'], sha256=inputs['c_header']['sha256'],
            bytes_readback=readback['c_header_compilers'][0]['output_bytes'],
            c99_and_cpp17_executed=True, heads=32, positions=64, topk=8, reindex_candidates=16),
        environment=dict(python=inputs['python_version'], torch=inputs['torch_version'], numpy=inputs['numpy_version'], cpu_threads=inputs['cpu_threads']),
        claims=inputs['claims'], physical_records=dict(query_per_head=96, key_per_position=96, axi_beat=32),
        oracle_precondition='Reindex score oracle validates the entire supplied K cache format. Equivalence to physically skipping RTL is asserted for fully valid caches; malformed unselected cache bytes are outside that equivalence precondition.',
        source_sha256={str(p.relative_to(ROOT)): sha(p) for p in sorted((ROOT/'research').glob('*.py'))},
        source_lock_sha256=sha(ROOT/'research/csa2_sources.lock.json'),
        evidence_digest=dict(input_manifest_sha256=sha(base/'inputs/manifest.json'), readback_sha256=sha(base/'readback/summary.json'), oracle_audit_sha256=sha(base/'oracle-audit/summary.json')),
        scope='Source-locked CSA2 operator inputs, independent arithmetic and C/C++ fixture validation. RTL/system/PPA have separate evidence; no full-model quality or CUDA-bitexact claim.')
    out = ROOT/'evidence/research';out.mkdir(parents=True, exist_ok=True)
    (out/'summary.json').write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(dict(passed=True, output='evidence/research/summary.json', cases=len(compact_cases))))


if __name__ == '__main__':
    main()
