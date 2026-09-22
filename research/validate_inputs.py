#!/usr/bin/env python3
"""Read back frozen research inputs and compile/read the pure-C system fixture."""
import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess

import numpy as np
import torch
import torch.nn.functional as F
import csa2_oracle as oracle

ROOT = Path(__file__).resolve().parent.parent


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--inputs', type=Path, default=ROOT/'results/research/inputs')
    ap.add_argument('--reference', type=Path, default=ROOT/'results/research/reference')
    ap.add_argument('--out', type=Path, default=ROOT/'results/research/readback')
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'summary.json').unlink(missing_ok=True)
    manifest_path = args.inputs/'manifest.json'
    manifest = json.loads(manifest_path.read_text())
    assert manifest['passed']
    checked = {}
    def verify(path, expected):
        path = Path(path)
        assert sha(path) == expected, str(path)
        checked[str(path.relative_to(ROOT))] = expected
    for p, digest in manifest['locked_sha256'].items():
        verify(ROOT/p, digest)
    reference = json.loads((args.reference/'manifest.json').read_text())
    lock = json.loads((ROOT/'research/csa2_sources.lock.json').read_text())
    assert reference['passed'] and not reference['fetched_complete_model']
    verify(ROOT/'research/fetch_reference.py', reference['producer_sha256'])
    verify(ROOT/'research/csa2_sources.lock.json', reference['source_lock_sha256'])
    assert reference['files'] == lock['files'] and reference['tensors'] == lock['tensors']
    for p, rec in reference['files'].items():
        verify(args.reference/p, rec['sha256'])
    for rec in reference['tensors'].values():
        verify(args.reference/rec['file'], rec['sha256'])
    assert sum(rec['bytes'] for rec in reference['tensors'].values()) == 5707008
    publications = json.loads((ROOT/'results/research/publications/manifest.json').read_text())
    assert publications['passed']
    publication_lock = json.loads((ROOT/'research/publications.lock.json').read_text())
    assert publications['files'] == publication_lock['files']
    assert publications['reference_only'] == publication_lock['reference_only']
    verify(ROOT/'research/fetch_publications.py', publications['producer_sha256'])
    verify(ROOT/'research/publications.lock.json', publications['source_lock_sha256'])
    for filename, rec in publications['files'].items():
        verify(ROOT/'results/research/publications'/filename, rec['sha256'])
    for field in ('projection_random_inputs', 'projection_random_inputs_small', 'c_header'):
        rec = manifest[field]
        verify(ROOT/rec['path'], rec['sha256'])
    cases = {}
    statuses = {}
    for record in manifest['cases']:
        path = ROOT/record['path']
        verify(path, record['sha256'])
        case = json.loads(path.read_text())
        result = oracle.evaluate_fixture(case)
        assert result == case['expected']
        assert result['status'] == record['status']
        statuses[result['status']] = statuses.get(result['status'], 0)+1
        cases[case['name']] = case
        for rec in record['wire'].values():
            verify(ROOT/rec['path'], rec['sha256'])
            assert (ROOT/rec['path']).stat().st_size == rec['bytes']
        qc, qs, kc, ks, w, mask = oracle.fixture_arrays(case)
        query_axi = (ROOT/record['wire']['query_axi96.bin']['path']).read_bytes()
        keys_axi = (ROOT/record['wire']['keys_axi96.bin']['path']).read_bytes()
        assert len(query_axi) == case['heads']*96 and len(keys_axi) == case['positions']*96
        for i, (q, sc, weight) in enumerate(zip(qc, qs, w)):
            assert query_axi[i*96:(i+1)*96] == oracle.pack_e2m1(q)+sc.tobytes()+struct.pack('<H', int(weight))+bytes(26)
        for i, (k, sc) in enumerate(zip(kc, ks)):
            assert keys_axi[i*96:(i+1)*96] == oracle.pack_e2m1(k)+sc.tobytes()+bytes(28)
        ids = np.frombuffer((ROOT/record['wire']['candidate_ids_u32le.bin']['path']).read_bytes(), dtype='<u4')
        assert ids.tolist() == np.flatnonzero(mask).tolist()
    # Independent execution of the complete official candidate function. Use
    # strictly ordered scores so stable-vs-unspecified tie policy is irrelevant.
    tree = ast.parse((args.reference/'inference/model.py').read_text())
    candidate_fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'select_candidate_blocks')
    for arg in candidate_fn.args.args:
        arg.annotation = None
    candidate_fn.returns = None
    module = ast.Module(body=[candidate_fn], type_ignores=[])
    ast.fix_missing_locations(module)
    namespace = {'torch': torch, 'F': F}
    exec(compile(module, 'pinned_official_model.py', 'exec'), namespace)
    candidate_cases = []
    for n, visible, blocks in [(1, 1, 2048), (81, 77, 4), (16401, 16401, 2048)]:
        values = np.arange(n, dtype=np.float32)
        values[visible-1] = -100000
        bits = values.view(np.uint32).tolist()
        expected_mask, _ = oracle.select_candidate_blocks(bits, 8, blocks, visible)
        scores = torch.from_numpy(values.copy())
        scores[visible:] = -torch.inf
        actual = namespace['select_candidate_blocks'](scores, visible, blocks, 8)
        # Official prefill block mask also includes future slots inside the
        # newest partial block; its score tensor has already applied causality.
        # A physical DMA list must intersect that mask with visible positions.
        discarded_future = int(actual[visible:].sum())
        actual &= torch.arange(n) < visible
        assert actual.tolist() == expected_mask
        candidate_cases.append(dict(positions=n, visible=visible, topk_blocks=blocks,
                                    retained=sum(expected_mask), official_future_slots_removed=discarded_future))
    # Both C99 and C++17 compile the exact shipped header; stdout bytes must
    # match the independently hashed JSON/wire inputs and oracle expected data.
    header = ROOT/manifest['c_header']['path']
    source = '#include <stdio.h>\n#include "'+str(header)+'"\nint main(void) {\n'
    names = ['sg_real_q', 'sg_real_k', 'sg_real_expected_index', 'sg_real_expected_score',
             'sg_real_reindex_expected_index', 'sg_real_reindex_expected_score', 'sg_real_candidate_ids']
    source += ''.join('if(fwrite(%s,1,sizeof(%s),stdout)!=sizeof(%s)) return 1;\n'%(n, n, n) for n in names)+'return 0;\n}\n'
    src = args.out/'header_readback.c'
    src.write_text(source)
    full = cases[manifest['c_header']['full_case']]
    reindex = cases[manifest['c_header']['reindex_case']]
    wire = next(c['wire'] for c in manifest['cases'] if c['name'] == full['name'])
    expected = (ROOT/wire['query_axi96.bin']['path']).read_bytes() + (ROOT/wire['keys_axi96.bin']['path']).read_bytes()
    for case in (full, reindex):
        ids = case['expected']['indices_position_order']
        expected += np.asarray(ids, dtype='<u4').tobytes()
        expected += np.asarray([int(case['expected']['scores_hex'][i], 16) for i in ids], dtype='<u4').tobytes()
    expected += np.flatnonzero(oracle.fixture_arrays(reindex)[-1]).astype('<u4').tobytes()
    compilers = []
    for cc, std in [('cc', 'c99'), ('c++', 'c++17')]:
        binary = args.out/('header-'+std)
        command = [shutil.which(cc), '-std='+std, '-O2', '-Wall', '-Wextra', '-Werror', str(src), '-o', str(binary)]
        subprocess.run(command, check=True, capture_output=True)
        run = subprocess.run([str(binary)], check=True, capture_output=True)
        assert run.stdout == expected
        compilers.append(dict(command=command, compiler_version=subprocess.check_output([command[0], '--version'], text=True).splitlines()[0],
                              binary_sha256=sha(binary), output_bytes=len(run.stdout), output_sha256=hashlib.sha256(run.stdout).hexdigest()))
    for p, digest in checked.items():
        assert sha(ROOT/p) == digest
    summary = dict(passed=True, audit_source=str(Path(__file__).resolve().relative_to(ROOT)), audit_source_sha256=sha(__file__),
        manifest_path=str(manifest_path.relative_to(ROOT)), manifest_sha256=sha(manifest_path),
        checked_sha256=checked, cases=len(cases), statuses=statuses, candidate_function_cases=candidate_cases,
        c_header_compilers=compilers, mismatches=0,
        scope='Fresh exact-dyadic oracle evaluation, all source/input/wire hashes, official Torch candidate producer, and compiled C/C++ header byte readback; no full-model or hardware claim')
    (args.out/'summary.json').write_text(json.dumps(summary, indent=2)+'\n')
    print(json.dumps(dict(passed=True, cases=len(cases), statuses=statuses, checked_files=len(checked), c_header_bytes=len(expected))))


if __name__ == '__main__':
    main()
