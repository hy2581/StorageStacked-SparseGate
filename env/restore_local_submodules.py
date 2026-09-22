#!/usr/bin/env python3
"""Restore pinned submodules from independent copies of a local donor's Git objects.

Never copies donor worktree changes, uses alternates/hardlinks, or modifies donor
files. Subsequent adaptation and builds occur only in this checkout.
"""
import argparse
import json
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def git(path, *args):
    return subprocess.check_output(['git', '-C', str(path), *args], text=True).strip()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('donor', type=Path)
    a = p.parse_args()
    donor = a.donor.resolve()
    if donor == ROOT or ROOT in donor.parents or donor in ROOT.parents:
        raise SystemExit('Donor must be an independent checkout')
    locks = json.loads((ROOT / 'env/sources.lock.json').read_text())
    for name, revision in locks.items():
        if git(donor / name, 'rev-parse', 'HEAD') != revision:
            raise SystemExit('Donor revision differs from lock: ' + name)
    states = git(donor, 'submodule', 'status', '--recursive')
    pairs = []
    for line in states.splitlines():
        parts = line.split()
        if line.lstrip().startswith(('-', '+', 'U')) or len(parts) < 2:
            raise SystemExit('Donor submodule is not pinned: ' + line)
        revision, name = parts[:2]
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise SystemExit('Unsafe submodule name: ' + name)
        pairs.append((revision, name))
    for revision, name in sorted(pairs, key=lambda item: (len(Path(item[1]).parts), item[1])):
        source, target = donor / name, ROOT / name
        if (target / '.git').exists():
            if git(target, 'rev-parse', 'HEAD') != revision:
                raise SystemExit('Existing target revision differs; no reset: ' + name)
        else:
            if target.exists() and any(target.iterdir()):
                raise SystemExit('Refuse nonempty destination: ' + str(target))
            target.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(['git', 'clone', '--local', '--no-hardlinks', '--no-checkout',
                            str(source), str(target)], check=True)
            subprocess.run(['git', '-C', str(target), 'checkout', '--detach', revision], check=True)
            subprocess.run(['git', '-C', str(target), 'remote', 'set-url', 'origin',
                            git(source, 'remote', 'get-url', 'origin')], check=True)
        if git(target, 'rev-parse', 'HEAD') != revision:
            raise SystemExit('Post-copy revision mismatch: ' + name)
        alternate = Path(git(target, 'rev-parse', '--git-path', 'objects/info/alternates'))
        if not alternate.is_absolute():
            alternate = target / alternate
        if alternate.exists():
            raise SystemExit('Unexpected dependency on donor object alternates: ' + name)
        print('Pinned independent clone:', name, revision, flush=True)
    subprocess.run(['git', '-C', str(ROOT), 'submodule', 'init'], check=True)
    for _, name in sorted(pairs, key=lambda item: len(Path(item[1]).parts)):
        if (ROOT / name / '.gitmodules').is_file():
            subprocess.run(['git', '-C', str(ROOT / name), 'submodule', 'init'], check=True)
    subprocess.run(['git', '-C', str(ROOT), 'submodule', 'absorbgitdirs'], check=True)
    subprocess.run(['python3', str(ROOT / 'env/check_sources.py')], check=True)


if __name__ == '__main__':
    main()
