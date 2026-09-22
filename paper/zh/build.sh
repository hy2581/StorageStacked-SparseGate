#!/usr/bin/env bash
set -euo pipefail
source_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
repo_dir=$(cd -- "$source_dir/../.." && pwd)
build_dir="$repo_dir/paper/build/zh"
python_bin=${PAPER_PYTHON:-python3}
mkdir -p "$build_dir" "$source_dir/generated"
"$python_bin" "$source_dir/prepare_results.py" > "$source_dir/generated/manifest.json"
"$python_bin" "$source_dir/generate_figures.py" > "$build_dir/figures.log" 2> "$build_dir/figures.stderr"
for figure in system core layout flow; do
    test -s "$source_dir/figures/generated/$figure.png"
done
"$python_bin" "$source_dir/finalize.py" --snapshot
cd "$source_dir"
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex > "$build_dir/latex.stdout"
(cd "$build_dir" && BIBINPUTS="$source_dir": bibtex main > bibtex.stdout)
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex >> "$build_dir/latex.stdout"
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex >> "$build_dir/latex.stdout"
cp "$build_dir/main.pdf" "$repo_dir/paper/SparseGate-paper-zh.pdf"
"$python_bin" "$source_dir/finalize.py"
