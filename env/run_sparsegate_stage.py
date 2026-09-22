#!/usr/bin/env python3
"""Run a named, recorded build/acceptance stage in this checkout only.

The dependency prefix may be reused; every build output stays in this checkout.
A successful process exit is recorded as COMPLETED, never as experiment PASS.
The relevant native/online verification summary supplies acceptance evidence.
"""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess
import time

ROOT = Path(__file__).resolve().parents[1]


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('stage')
    p.add_argument('--deps', type=Path, required=True)
    p.add_argument('--jobs', type=int, default=16)
    p.add_argument('command', nargs=argparse.REMAINDER)
    a = p.parse_args()
    if not a.stage.replace('-', '').replace('_', '').isalnum():
        raise SystemExit('Unsafe stage name')
    command = a.command[1:] if a.command[:1] == ['--'] else a.command
    if not command:
        raise SystemExit('Missing command')
    deps = a.deps.resolve()
    if not (deps / 'toolchain/bin/python').is_file():
        raise SystemExit('Missing dependency toolchain')
    directory = ROOT / 'results/baseline-build'
    directory.mkdir(parents=True, exist_ok=True)
    log, receipt = directory / (a.stage + '.log'), directory / (a.stage + '.json')
    if log.exists() or receipt.exists():
        raise SystemExit('Stage already exists; use a distinct stage name')
    env = dict(os.environ)
    for key in ('LD_LIBRARY_PATH', 'LD_PRELOAD', 'LD_AUDIT', 'PYTHONPATH', 'PYTHONHOME',
                'VIRTUAL_ENV', 'CONDA_PREFIX', 'CONDA_DEFAULT_ENV', 'CPATH', 'C_INCLUDE_PATH',
                'CPLUS_INCLUDE_PATH', 'LIBRARY_PATH', 'CFLAGS', 'CXXFLAGS', 'CPPFLAGS',
                'LDFLAGS', 'CC', 'CXX'):
        env.pop(key, None)
    # Some upstream host Makefiles invoke bare gcc/g++ instead of CC/CXX.
    host_bin = ROOT / 'build/host-bin'
    host_bin.mkdir(parents=True, exist_ok=True)
    for name, target in [('gcc', 'x86_64-conda-linux-gnu-gcc'),
                         ('g++', 'x86_64-conda-linux-gnu-g++')]:
        link = host_bin / name
        expected = deps / 'toolchain/bin' / target
        if link.is_symlink():
            if link.resolve() != expected.resolve():
                raise SystemExit('Existing compiler link differs: ' + str(link))
        elif link.exists():
            raise SystemExit('Refusing to replace compiler wrapper: ' + str(link))
        else:
            link.symlink_to(expected)
    env.update(PATH=str(host_bin) + ':/usr/local/bin:/usr/bin:/bin',
               SS_DEPS_ROOT=str(deps), AXI_JOBS=str(a.jobs),
               SS_BAZEL_OUTPUT_ROOT=str(ROOT / 'build/bazel'), GIT_TERMINAL_PROMPT='0')
    record = dict(stage=a.stage, status='RUNNING', passed=False, command=command,
                  cwd=str(ROOT), dependency_prefix=str(deps), jobs=a.jobs,
                  started_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  source_lock_sha256=hashlib.sha256((ROOT / 'env/sources.lock.json').read_bytes()).hexdigest(),
                  runner_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(), log=str(log))
    receipt.write_text(json.dumps(record, indent=2) + '\n')
    print('Running', a.stage, 'log:', log, flush=True)
    start = time.monotonic()
    try:
        with log.open('x') as output:
            result = subprocess.run(command, cwd=ROOT, env=env, stdout=output, stderr=subprocess.STDOUT)
        record.update(status='COMPLETED' if result.returncode == 0 else 'FAILED',
                      returncode=result.returncode, elapsed_seconds=time.monotonic() - start,
                      log_sha256=hashlib.sha256(log.read_bytes()).hexdigest())
        receipt.write_text(json.dumps(record, indent=2) + '\n')
        print(json.dumps(record, indent=2), flush=True)
        if result.returncode:
            print('\n'.join(log.read_text(errors='replace').splitlines()[-35:]), flush=True)
        return result.returncode
    except BaseException as exc:
        record.update(status='INTERRUPTED_OR_ERROR', passed=False, error=repr(exc),
                      elapsed_seconds=time.monotonic() - start)
        receipt.write_text(json.dumps(record, indent=2) + '\n')
        raise


if __name__ == '__main__':
    raise SystemExit(main())
