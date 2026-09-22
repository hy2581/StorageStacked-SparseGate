#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PAPER_PYTHON:-python3}
"$python_bin" "$root/paper/prepare.py" "$@"
mkdir -p "$root/paper/build"
cd "$root/paper"
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build main.tex > build/latex.stdout
(cd build && BIBINPUTS=..: bibtex main > bibtex.stdout)
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build main.tex >> build/latex.stdout
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build main.tex >> build/latex.stdout
if [[ ${1:-} == --preview ]]; then
    cp build/main.pdf SparseGate-preview.pdf
else
    cp build/main.pdf SparseGate-paper.pdf
fi

"$python_bin" "$root/paper/finalize.py" "$@"
