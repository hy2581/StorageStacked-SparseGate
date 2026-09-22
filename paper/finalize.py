#!/usr/bin/env python3
"""Seal a compiled paper only after evidence generation and PDF sanity checks."""
import hashlib,json,re,subprocess,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parent.parent
paper=ROOT/'paper';preview='--preview' in sys.argv
pdf=paper/('SparseGate-preview.pdf' if preview else 'SparseGate-paper.pdf')
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
record=json.loads((paper/'generated/manifest.json').read_text())
assert record['preview']==preview
assert preview or not record['missing_evidence']
for relative,digest in record['input_sha256'].items():assert sha(ROOT/relative)==digest,relative
for relative,digest in record['outputs'].items():assert sha(ROOT/relative)==digest,relative
assert sha(paper/'prepare.py')==record['generator_sha256']
log=(paper/'build/main.log').read_text()
for marker in ['Overfull \\hbox','Overfull \\vbox','There were undefined references','Citation `','Reference `']:
 assert marker not in log, 'Unresolved TeX layout/reference issue: '+marker
info=subprocess.check_output(['pdfinfo',str(pdf)],text=True)
text=subprocess.check_output(['pdftotext',str(pdf),'-'],text=True)
assert 'FP4 Sparse Indexing' in text and len(text)>15000
if not preview:
 assert 'Preview:' not in text and 'still running' not in text
sources={}
for pattern in ['*.tex','*.bib','*.py','*.sh','requirements.txt','figures/*.pdf','figures/generated/*.png','figures/generated/prompts.json','generated/*.tex','generated/manifest.json']:
 for p in paper.glob(pattern):sources[str(p.relative_to(ROOT))]=sha(p)
result={'schema':'sparse_gate_paper_delivery_v1','preview':preview,'pdf':str(pdf.relative_to(ROOT)),'pdf_sha256':sha(pdf),'pages':int(re.search(r'^Pages:\s+(\d+)',info,re.M).group(1)),'source_sha256':sources,'automated_checks':{'evidence_inputs_unchanged':True,'generated_tables_unchanged':True,'no_overfull_boxes':True,'no_undefined_references':True,'text_extracted':True},'visual_review':'Separate manual rendered-page review; these automated checks do not certify figure semantics','tools':{'pdflatex':subprocess.check_output(['pdflatex','--version'],text=True).splitlines()[0],'bibtex':subprocess.check_output(['bibtex','--version'],text=True).splitlines()[0],'pdfinfo':subprocess.run(['pdfinfo','-v'],capture_output=True,text=True).stderr.splitlines()[0]}}
target=paper/('build/preview-delivery.json' if preview else 'delivery.json')
target.write_text(json.dumps(result,indent=2)+'\n');print(f'{pdf.name}: {result["pages"]} pages; SHA256 {result["pdf_sha256"]}')
