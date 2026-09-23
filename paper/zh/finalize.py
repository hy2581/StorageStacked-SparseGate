#!/usr/bin/env python3
"""Seal the Chinese edition after source, equation, evidence and PDF checks."""
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ZH = ROOT / 'paper/zh'
PDF = ROOT / 'paper/SparseGate-paper-zh.pdf'

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def verify(mapping):
    for name,digest in mapping.items():
        assert (ROOT/name).is_file() and sha(ROOT/name)==digest, name

def read_pdf(command):
    result=subprocess.run(command,text=True,stdout=subprocess.PIPE,stderr=subprocess.PIPE,check=True)
    assert not result.stderr.strip(), 'PDF reader reported a compatibility issue: '+result.stderr
    return result.stdout

def collect_sources():
    sources={}
    for p in sorted(ZH.rglob('*')):
        if not p.is_file() or '__pycache__' in p.parts:continue
        if p.suffix in ['.tex','.py','.sh','.bib','.png','.pdf'] or p.name in ['prompts.json','manifest.json']:
            sources[str(p.relative_to(ROOT))]=sha(p)
    return sources

def main():
    snapshot=ROOT/'paper/build/zh/source_snapshot.json'
    if sys.argv[1:]==['--snapshot']:
        snapshot.write_text(json.dumps(collect_sources(),indent=2)+'\n')
        return
    english = json.loads((ROOT/'paper/delivery.json').read_text())
    assert not english['preview'] and sha(ROOT/english['pdf'])==english['pdf_sha256']
    verify(english['source_sha256'])
    translated = json.loads((ZH/'generated/manifest.json').read_text())
    assert translated['passed']
    verify(translated['input_sha256']); verify(translated['outputs'])
    assert sha(ZH/'prepare_results.py')==translated['generator_sha256']
    plots = json.loads((ZH/'figures/manifest.json').read_text())
    verify(plots['input_sha256']); verify(plots['output_sha256'])
    assert sha(ZH/'generate_figures.py')==plots['generator_sha256']
    assert plots['source_manifest_sha256']==sha(ROOT/'paper/generated/manifest.json')
    assert not (ROOT/'paper/build/zh/figures.stderr').read_text().strip(), 'Measurement figure generator reported warnings'
    concept_dir=ZH/'figures/generated'
    concepts=json.loads((concept_dir/'manifest.json').read_text())
    assert concepts['status']=='VISUALLY_REVIEWED' and concepts['png_frozen']
    assert set(concepts['outputs'])=={'system','core','layout','flow'}
    for record in concepts['outputs'].values():
        assert record['selected'] and record['status']=='VISUALLY_REVIEWED'
        assert sha(concept_dir/record['file'])==record['sha256'], record['file']
        assert sha(ROOT/record['source'])==record['source_sha256'], record['source']
    for name in ['prompts','readme']:
        record=concepts[name]
        assert sha(concept_dir/record['file'])==record['sha256'], record['file']
    english_main = (ROOT/'paper/main.tex').read_text()
    chinese_body = (ZH/'body.tex').read_text()
    equations = lambda s:[re.sub(r'\s+','',x) for _,x in re.findall(r'\\begin\{(equation|align)\}(.*?)\\end\{\1\}',s,re.S)]
    assert equations(english_main)==equations(chinese_body)
    citations = lambda s:re.findall(r'\\cite\{([^}]+)\}',s)
    assert citations(english_main)==citations(chinese_body)
    assert (ZH/'generated/results.tex').read_bytes()==(ROOT/'paper/generated/results.tex').read_bytes()
    combined=chinese_body+'\n'+''.join(p.read_text() for p in (ZH/'generated').glob('*.tex'))
    figure_count=len(re.findall(r'\\begin\{figure\*?\}',combined))
    table_count=len(re.findall(r'\\begin\{table\*?\}',combined))
    assert figure_count==7 and table_count==3
    log=(ROOT/'paper/build/zh/main.log').read_text()
    for marker in ['Overfull \\hbox','Overfull \\vbox','There were undefined references','Citation `','Reference `','Missing character:']:
        assert marker not in log, 'Unresolved Chinese TeX issue: '+marker
    biblog=(ROOT/'paper/build/zh/main.blg').read_text()
    assert "I didn't find a database entry" not in biblog
    text=read_pdf(['pdftotext',str(PDF),'-'])
    cjk=len(re.findall(r'[\u4e00-\u9fff]',text))
    assert cjk>=3000 and '稀疏索引' in text and '参考文献' in text
    compact=re.sub(r'[\s,]','',text)
    for number in ['670572','115776','147456','301340.93','0.000006','130009','181.530']:
        assert number in compact, 'Missing numerical result: '+number
    assert 'Preview:' not in text and 'still running' not in text
    fontlist=read_pdf(['pdffonts',str(PDF)])
    flags=re.findall(r'\s+(yes|no)\s+(yes|no)\s+(yes|no)\s+\d+\s+\d+\s*$',fontlist,re.M)
    assert flags and all(row[0]=='yes' for row in flags), 'PDF has an unembedded font'
    info=read_pdf(['pdfinfo',str(PDF)])
    sources=collect_sources()
    assert sources==json.loads(snapshot.read_text()), 'Chinese manuscript sources changed while compiling'
    record={'schema':'sparse_gate_chinese_paper_delivery_v1','status':'PASS','language':'zh-CN',
            'pdf':str(PDF.relative_to(ROOT)),'pdf_sha256':sha(PDF),
            'pages':int(re.search(r'^Pages:\s+(\d+)',info,re.M).group(1)),
            'figures':figure_count,'tables':table_count,'extracted_chinese_characters':cjk,
            'english_edition':{'pdf':english['pdf'],'pdf_sha256':english['pdf_sha256'],
                               'delivery_sha256':sha(ROOT/'paper/delivery.json')},
            'source_sha256':sources,
            'checks':{'english_sources_unchanged':True,'same_numerical_evidence':True,'displayed_equations_unchanged':True,
                      'citation_keys_unchanged':True,'numeric_macros_identical':True,'no_overfull_boxes':True,
                      'no_missing_characters_or_references':True,'fonts_embedded':True,'pdf_reader_no_warnings':True,
                      'conceptual_image_review_hashes_verified':True},
            'visual_review':'Separate inspection of every rendered final page is required; see visual_review.json.',
            'scope':'Faithful Chinese edition using the accepted experiments; no new experiments or physical-signoff claims.',
            'xelatex_version':subprocess.check_output(['xelatex','--version'],text=True).splitlines()[0]}
    (ZH/'delivery.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
    print(f"{PDF.name}: {record['pages']} pages; SHA256 {record['pdf_sha256']}")

if __name__=='__main__':main()
