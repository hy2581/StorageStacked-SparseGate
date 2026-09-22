#!/usr/bin/env python3
"""Fetch pinned CSA2 reference code and only five small indexer tensors.

Never downloads a complete model shard. Tensor reads require HTTP 206 and an
exact Content-Range; a server ignoring Range is rejected before reading it.
"""
import argparse
import concurrent.futures
import hashlib
import json
from pathlib import Path
import struct
import requests

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
REVISION = 'dba1be0a40aa45a94ad051997016db3960a90277'
MODEL = 'deepseek-ai/DeepSeek-V4.1-Flash'
BASE = 'https://huggingface.co/'+MODEL+'/resolve/'+REVISION+'/'
FILES = ('config.json', 'inference/config.json', 'inference/model.py', 'inference/kernel.py',
         'LICENSE', 'README.md', 'model.safetensors.index.json')
TENSORS = tuple('layers.20.attn.indexer.'+s for s in
                ('k_norm.weight', 'weights_proj.weight', 'wk.weight', 'wq_b.scale', 'wq_b.weight'))


def sha(data):
    return hashlib.sha256(data).hexdigest()


def get_file(name):
    r = requests.get(BASE+name, timeout=90)
    r.raise_for_status()
    assert len(r.content) < 12*1024*1024, 'Unexpectedly large non-tensor reference'
    return name, r.content


def get_range(name, first, last):
    assert 0 <= first <= last and last-first+1 <= 8*1024*1024
    with requests.get(BASE+name, headers={'Range': f'bytes={first}-{last}'}, stream=True, timeout=90) as r:
        r.raise_for_status()
        assert r.status_code == 206, 'Server ignored Range; refusing shard download'
        content_range = r.headers.get('Content-Range', '')
        assert content_range.startswith(f'bytes {first}-{last}/'), content_range
        chunks, size = [], 0
        for chunk in r.iter_content(65536):
            size += len(chunk)
            assert size <= last-first+1, 'Oversized range response'
            chunks.append(chunk)
        data = b''.join(chunks)
        assert len(data) == last-first+1
        return data, content_range


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--out', type=Path, default=ROOT/'results/research/reference')
    ap.add_argument('--initialize-lock', action='store_true', help='First local lock creation from immutable official revision')
    args = ap.parse_args()
    lock_path = HERE/'csa2_sources.lock.json'
    lock = None if args.initialize_lock else json.loads(lock_path.read_text())
    if args.initialize_lock:
        assert not lock_path.exists(), 'Existing source lock cannot be overwritten'
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out/'manifest.json').unlink(missing_ok=True)
    outputs = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for name, data in pool.map(get_file, FILES):
            if lock:
                assert sha(data) == lock['files'][name]['sha256'], name
            p = args.out/name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(data)
            outputs[name] = dict(url=BASE+name, sha256=sha(data), bytes=len(data))
    index = json.loads((args.out/'model.safetensors.index.json').read_text())['weight_map']
    shards = sorted({index[t] for t in TENSORS})
    headers = {}
    ranges = []
    for shard in shards:
        data, cr = get_range(shard, 0, 7)
        header_size = struct.unpack('<Q', data)[0]
        assert header_size < 8*1024*1024
        head, cr2 = get_range(shard, 8, 7+header_size)
        headers[shard] = (header_size, json.loads(head))
        ranges.extend([dict(shard=shard, range=cr, bytes=8, sha256=sha(data)),
                       dict(shard=shard, range=cr2, bytes=len(head), sha256=sha(head))])
        hp = args.out/'headers'/(shard+'.json')
        hp.parent.mkdir(exist_ok=True)
        hp.write_bytes(head)
    tensor_records = {}
    tensor_bytes = 0
    for name in TENSORS:
        shard = index[name]
        header_size, header = headers[shard]
        desc = header[name]
        start, end = desc['data_offsets']
        first, last = 8+header_size+start, 8+header_size+end-1
        data, cr = get_range(shard, first, last)
        tensor_bytes += len(data)
        assert tensor_bytes < 16*1024*1024, 'Small-tensor budget exceeded'
        if lock:
            assert sha(data) == lock['tensors'][name]['sha256'], name
            assert desc == lock['tensors'][name]['safetensors_metadata']
        filename = 'tensors/'+name+'.bin'
        p = args.out/filename
        p.parent.mkdir(exist_ok=True)
        p.write_bytes(data)
        tensor_records[name] = dict(file=filename, sha256=sha(data), bytes=len(data),
            safetensors_metadata=desc, shard=shard, range=cr, source_url=BASE+shard)
        print('tensor', name, desc['dtype'], desc['shape'], len(data), flush=True)
    identity = dict(schema_version=1, model=MODEL, revision=REVISION, files=outputs, tensors=tensor_records)
    if args.initialize_lock:
        lock_path.write_text(json.dumps(identity, indent=2, sort_keys=True)+'\n')
    else:
        assert identity == lock
    manifest = dict(passed=True, **identity, header_ranges=ranges, tensor_payload_bytes=tensor_bytes,
        fetched_complete_model=False, source_lock_sha256=sha(lock_path.read_bytes()),
        producer_sha256=sha(Path(__file__).read_bytes()),
        scope='Pinned official source and five layer-20 indexer tensors only; no model forward or activation provenance claim')
    (args.out/'manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True)+'\n')
    print(json.dumps(dict(passed=True, tensor_payload_bytes=tensor_bytes, output=str(args.out))))


if __name__ == '__main__':
    main()
