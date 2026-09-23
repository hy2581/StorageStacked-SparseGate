#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
work=$(mktemp -d)
trap 'rm -rf -- "$work"' EXIT
"$root/paper/compile_tex.sh" "$root/paper/zh" "$work" xelatex "$root/paper/SparseGate-final.pdf"
pdfinfo "$root/paper/SparseGate-final.pdf" | grep '^Pages:'
pdftotext "$root/paper/SparseGate-final.pdf" "$work/paper.txt"
grep -q 'Vortex' "$work/paper.txt"
grep -q '命令处理器' "$work/paper.txt"
echo "$root/paper/SparseGate-final.pdf"
