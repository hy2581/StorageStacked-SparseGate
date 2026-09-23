#!/usr/bin/env bash
set -euo pipefail
[[ $# == 4 ]] || { echo 'Usage: compile_tex.sh SOURCE_DIR BUILD_DIR ENGINE OUTPUT_PDF' >&2; exit 2; }
source_dir=$(cd -- "$1" && pwd)
mkdir -p "$2"
build_dir=$(cd -- "$2" && pwd)
engine=$3
output=$4
case "$engine" in
    pdflatex|xelatex) ;;
    *) echo "Unsupported TeX engine: $engine" >&2; exit 2 ;;
esac
cd "$source_dir"
"$engine" -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex > "$build_dir/latex.stdout"
(cd "$build_dir" && BIBINPUTS="$source_dir": bibtex main > bibtex.stdout)
"$engine" -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex >> "$build_dir/latex.stdout"
"$engine" -interaction=nonstopmode -halt-on-error -output-directory="$build_dir" main.tex >> "$build_dir/latex.stdout"
cp "$build_dir/main.pdf" "$output"
