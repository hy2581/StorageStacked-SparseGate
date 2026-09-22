#!/usr/bin/env python3
"""Freeze actual baseline receipts, raw logs and the executed gem5 binary."""
import hashlib
import json
from pathlib import Path
import shutil
import sys

def sha(path):
    d=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1<<20),b''):d.update(block)
    return d.hexdigest()

directory=Path(sys.argv[1]).resolve();seal=directory/'closure.json';seal.unlink(missing_ok=True)
summary=json.loads((directory/'summary.json').read_text())
if not summary.get('passed'):raise SystemExit('Cannot seal an incomplete baseline')
environment=json.loads((directory/'environment/manifest.json').read_text())
binary=Path(environment['binary'])
if sha(binary)!=environment['binary_sha256']:raise SystemExit('gem5 binary changed during baseline run')
snapshot=directory/'environment/executed-gem5.opt'
if snapshot.exists():
    if sha(snapshot)!=environment['binary_sha256']:raise SystemExit('Conflicting binary snapshot')
else:shutil.copy2(binary,snapshot)
suffixes={'.json','.csv','.vcd','.log','.txt','.hettrace','.opt','.patch'}
paths=[p for p in directory.rglob('*') if p.is_file() and p.suffix in suffixes and p!=seal]
record={'schema':'unified_baseline_closure_v1','passed':True,'summary_sha256':sha(directory/'summary.json'),
    'sealer_sha256':sha(Path(__file__)),'executed_binary_sha256':sha(snapshot),
    'artifacts_sha256':{str(p.relative_to(directory)):sha(p) for p in sorted(paths)}}
seal.write_text(json.dumps(record,indent=2)+'\n')
if json.loads(seal.read_text())!=record:raise SystemExit('Closure readback failure')
print('Sealed',len(paths),'baseline artifacts:',seal)
