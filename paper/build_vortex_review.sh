#!/usr/bin/env bash
set -euo pipefail
root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
python_bin=${PAPER_PYTHON:-python3}
mkdir -p "$root/paper/build/vortex-en" "$root/paper/build/vortex-zh"
"$python_bin" - "$root" <<'PY'
import hashlib,json,sys
from pathlib import Path
root=Path(sys.argv[1])
for name in ('paper/generated/manifest.json','paper/zh/generated/manifest.json'):
    record=json.loads((root/name).read_text())
    assert not record.get('preview',False) and not record.get('missing_evidence',[])
    for path,digest in record['outputs'].items():
        assert hashlib.sha256((root/path).read_bytes()).hexdigest()==digest,path
PY
"$python_bin" "$root/paper/prepare_vortex.py" > "$root/paper/build/vortex_preparation.json"
cd "$root/paper"
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/vortex-en main.tex > build/vortex-en/latex.stdout
(cd build/vortex-en && BIBINPUTS=../..: bibtex main > bibtex.stdout)
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/vortex-en main.tex >> build/vortex-en/latex.stdout
pdflatex -interaction=nonstopmode -halt-on-error -output-directory=build/vortex-en main.tex >> build/vortex-en/latex.stdout
cp build/vortex-en/main.pdf SparseGate-Vortex-review.pdf
cd "$root/paper/zh"
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$root/paper/build/vortex-zh" main.tex > "$root/paper/build/vortex-zh/latex.stdout"
(cd "$root/paper/build/vortex-zh" && BIBINPUTS="$root/paper/zh": bibtex main > bibtex.stdout)
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$root/paper/build/vortex-zh" main.tex >> "$root/paper/build/vortex-zh/latex.stdout"
xelatex -interaction=nonstopmode -halt-on-error -output-directory="$root/paper/build/vortex-zh" main.tex >> "$root/paper/build/vortex-zh/latex.stdout"
cp "$root/paper/build/vortex-zh/main.pdf" "$root/paper/SparseGate-Vortex-review-zh.pdf"
"$python_bin" - "$root" <<'PY'
import hashlib,json,re,subprocess,sys
from pathlib import Path
root=Path(sys.argv[1])
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
pdfs={}
for name in ('SparseGate-Vortex-review.pdf','SparseGate-Vortex-review-zh.pdf'):
    p=root/'paper'/name
    info=subprocess.check_output(['pdfinfo',str(p)],text=True)
    text=subprocess.check_output(['pdftotext',str(p),'-'],text=True)
    assert 'Vortex' in text and ('命令处理器' in text if name.endswith('-zh.pdf') else 'command-processor' in text)
    pdfs[name]={'sha256':sha(p),'pages':int(re.search(r'^Pages:\s+(\d+)',info,re.M).group(1))}
for sub in ('vortex-en','vortex-zh'):
    log=(root/'paper/build'/sub/'main.log').read_text(errors='replace')
    for marker in ('Overfull \\hbox','Overfull \\vbox','Missing character:','There were undefined references'):
        assert marker not in log,(sub,marker)
record={'schema':'vortex_paper_review_v1','status':'REVIEW_DRAFT',
        'legacy_english_manifest_sha256':sha(root/'paper/generated/manifest.json'),
        'legacy_chinese_manifest_sha256':sha(root/'paper/zh/generated/manifest.json'),
        'vortex_receipt_sha256':sha(root/'evidence/system/vortex_gate_cp.json'),
        'source_sha256':{name:sha(root/name) for name in
            ('paper/main.tex','paper/zh/main.tex','paper/zh/body.tex','paper/prepare_vortex.py',
             'paper/build_vortex_review.sh')},'pdfs':pdfs,
        'figures_sha256':{name:sha(root/name) for name in
            ('paper/figures/generated/system.png','paper/zh/figures/generated/system.png')},
        'scope':'Updated Vortex CP DMA case; legacy measured tables remain tied to their earlier source snapshots'}
(root/'paper/vortex_review.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
print(json.dumps(record,ensure_ascii=False,indent=2))
PY
