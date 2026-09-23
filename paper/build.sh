#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PAPER_PYTHON:-python3}
"$python_bin" "$root/paper/prepare.py" "$@"
if [[ ${1:-} == --preview ]]; then
    output="$root/paper/SparseGate-preview.pdf"
else
    output="$root/paper/SparseGate-paper.pdf"
fi
"$root/paper/compile_tex.sh" "$root/paper" "$root/paper/build" pdflatex "$output"

"$python_bin" "$root/paper/finalize.py" "$@"
