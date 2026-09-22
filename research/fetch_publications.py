#!/usr/bin/env python3
"""Download the primary CSA2 v1 PDF and verify its committed content hash."""
import argparse
import hashlib
import json
from pathlib import Path
import requests

ROOT = Path(__file__).resolve().parent.parent
SOURCES = {
    'deepseek-v4.1-flash-v1.pdf': dict(url='https://arxiv.org/pdf/2609.19969v1',
        title='DeepSeek-V4.1-Flash: Pushing the Limits of KV Cache Compression',
        author='DeepSeek-AI', date='2026-09-17', version='arXiv v1',
        landing_url='https://arxiv.org/abs/2609.19969v1'),
}
REFERENCE_ONLY = [dict(url='https://www.opencompute.org/documents/ocp-microscaling-formats-mx-v1-0-spec-final-pdf',
    title='OCP Microscaling Formats (MX) Specification', author='Open Compute Project',
    version='Version 1.0', date='2023-09-07', verified_online='2026-09-22',
    local_download_status='UNAVAILABLE_HTTP_403',
    scope='Official 16-page PDF readable through web research tool; direct requests download rejected. No local PDF/hash claimed.')]


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'results/research/publications')
    ap.add_argument('--initialize-lock', action='store_true')
    args = ap.parse_args()
    lock_path = ROOT/'research/publications.lock.json'
    if args.initialize_lock:
        assert not lock_path.exists(), 'Existing lock cannot be overwritten'
        lock = None
    else:
        lock = json.loads(lock_path.read_text())
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'manifest.json').unlink(missing_ok=True)
    records = {}
    for filename, meta in SOURCES.items():
        parts, total = [], 0
        with requests.get(meta['url'], stream=True, timeout=90) as response:
            response.raise_for_status()
            for part in response.iter_content(65536):
                total += len(part)
                assert total <= 16*1024*1024
                parts.append(part)
        data = b''.join(parts)
        assert data.startswith(b'%PDF-'), 'Expected primary PDF'
        record = dict(meta, bytes=len(data), sha256=sha(data))
        if lock:
            assert record == lock['files'][filename]
        (args.out/filename).write_bytes(data)
        records[filename] = record
    identity = dict(schema_version=1, files=records, reference_only=REFERENCE_ONLY)
    if args.initialize_lock:
        lock_path.write_text(json.dumps(identity, indent=2, sort_keys=True)+'\n')
    else:
        assert identity == lock
    manifest = dict(passed=True, **identity, source_lock_sha256=sha(lock_path.read_bytes()),
                    producer_sha256=sha(Path(__file__).read_bytes()))
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    print(json.dumps(dict(passed=True, files=len(records), bytes=sum(r['bytes'] for r in records.values()))))


if __name__ == '__main__':
    main()
