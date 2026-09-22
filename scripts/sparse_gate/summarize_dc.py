#!/usr/bin/env python3
"""Read back mapped DDC and publish bounded PPA, keeping all vendor artifacts private."""
import argparse,hashlib,json,os,re,shutil,subprocess
from pathlib import Path
ROOT=Path(__file__).resolve().parents[2]
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def kv(p):return dict(line.split('=',1) for line in p.read_text().splitlines() if '=' in line)
def slack(p):
    vals=re.findall(r'slack\s+\((?:MET|VIOLATED)\)\s+(-?[0-9.]+)',p.read_text());assert vals,p;return min(map(float,vals))
def timing_violated(p):return bool(re.search(r'slack\s+\(VIOLATED\)',p.read_text()))
def constraint_counts(p):
    electrical=('max_transition','min_transition','max_capacitance','min_capacitance','max_fanout')
    known=set(electrical)|{'max_delay/setup','min_delay/hold','max_area','max_dynamic_power','max_leakage_power','min_pulse_width','min_period','recovery','removal','clock_gating_setup','clock_gating_hold'}
    counts={};current=None
    for line in p.read_text().splitlines():
        words=line.strip().split()
        if words and words[0] in known:current=words[0];counts.setdefault(current,0)
        if '(VIOLATED)' in line:
            assert current is not None,'Cannot assign a violated constraint to a report section'
            counts[current]+=1
    assert sum(counts.values())==p.read_text().count('(VIOLATED)')
    return counts,{name:counts.get(name,0) for name in electrical}
def timing_coverage(run,meta,sdc):
    required={'no_clock','no_input_delay','partial_input_delay','unconstrained_endpoints','clock_no_period'}
    check_text=(run/'readback_check_timing.rpt').read_text()
    check_pattern=r"Checking\s+'?([a-z_]+)'?\s*\.\.\."
    performed=re.findall(check_pattern,check_text)
    warning_counts={};current='UNCLASSIFIED';sections={}
    for line in check_text.splitlines():
        found=re.search(check_pattern,line)
        if found:current=found.group(1)
        sections[current]=sections.get(current,'')+line+'\n'
        if re.match(r'^\s*(?:Warning|WARNING):',line):warning_counts[current]=warning_counts.get(current,0)+1
    warning_count=sum(warning_counts.values())
    reset_false_path=any(line.startswith('set_false_path ') and re.search(r'\[get_ports\s+\{?rst_n\}?\]',line) for line in sdc.splitlines())
    out=dict(status='NOT_CHECKED',passed=False,checks_performed=performed,required_checks=sorted(required),warning_count=warning_count,unwaived_warning_count=warning_count,warning_counts_by_check=warning_counts,reset_false_path_verified=reset_false_path,exceptions=[dict(port='clk',reason='Clock source is excluded from data input delay coverage'),dict(port='rst_n',reason='Asynchronous reset is excluded from data input delays and explicitly false-pathed')])
    ports_text=(run/'readback_ports.rpt').read_text();directions=dict(re.findall(r'^\s*(\S+)\s+(in|out|inout)\s+',ports_text,re.M))
    inputs={p for p,d in directions.items() if d=='in'}-{'clk','rst_n'};outputs={p for p,d in directions.items() if d=='out'}
    tables={'Input Delay':{},'Output Delay':{}};table=None;started=False
    for line in ports_text.splitlines():
        if line.strip() in tables:table=line.strip();started=False;continue
        if table and started and not line.strip():table=None;continue
        words=line.split()
        if table and words and words[0] in directions:
            assert words[0] not in tables[table],'Multiple delay rows for one port require explicit handling'
            tables[table][words[0]]=words[1:];started=True
    def matches(row,delay):
        try:return len(row)>=5 and all(float(v)==delay for v in row[:4]) and row[4]=='core_clk'
        except ValueError:return False
    missing_in=sorted(p for p in inputs if not matches(tables['Input Delay'].get(p,[]),meta['input_delay_ns']))
    missing_out=sorted(p for p in outputs if not matches(tables['Output Delay'].get(p,[]),meta['output_delay_ns']))
    io_parsed=bool(inputs and outputs and tables['Input Delay'] and tables['Output Delay']) and not any(d=='inout' for d in directions.values())
    io_ok=io_parsed and not missing_in and not missing_out
    out['io_delay_check']=dict(status=('PASS' if io_ok else 'FAIL') if io_parsed else 'NOT_CHECKED',passed=io_ok,input_data_ports=len(inputs),output_ports=len(outputs),missing_or_mismatched_inputs=missing_in,missing_or_mismatched_outputs=missing_out,checked_edges=['min_rise','min_fall','max_rise','max_fall'],related_clock='core_clk')
    if io_ok and reset_false_path and 'rst_n' in sections.get('no_input_delay',''):
        waived=warning_counts.get('no_input_delay',0);out['unwaived_warning_count']-=waived
        if waived:out['exceptions'].append(dict(check='no_input_delay',waived_warning_count=waived,reason='All data input delays are verified; the reported reset input has an explicit false path'))
    checked=kv(run/'readback_timing_coverage_status.txt').get('status')=='CHECKED_REQUIRES_REVIEW' and required<=set(performed) and io_parsed
    out['passed']=checked and io_ok and reset_false_path and out['unwaived_warning_count']==0
    out['status']=('PASS' if out['passed'] else 'FAIL') if checked else 'NOT_CHECKED'
    return out
def clock_model(run):
    clock_rows=re.findall(r'^core_clk\s+[0-9.]+\s+\{[^}]+\}\s*(.*?)\s+\{clk\}\s*$',(run/'clocks.rpt').read_text(),re.M)
    assert len(clock_rows)==1,'Cannot identify the saved clock attributes'
    attributes=clock_rows[0].strip()
    final_log=(run/'dc.log').read_text().split('Optimization Complete')[-1]
    warning_rows=re.findall(r"contains (\d+) high-fanout nets\. A fanout number of (\d+) will be used",final_log)
    assert len(set(warning_rows))<=1,'Inconsistent final high-fanout warning counts'
    nets={name:dict(name=name,loads=int(loads),drivers=int(drivers)) for name,loads,drivers in re.findall(r"Net '([^']+)': (\d+) load\(s\), (\d+) driver\(s\)",final_log)}
    count=int(warning_rows[0][0]) if warning_rows else 0
    assert len(nets)==count,'Final high-fanout warning lacks a complete net list'
    return dict(clock='core_clk',source='clk',ideal_clock='p' not in attributes,clock_attributes=attributes,cts_status='NOT_RUN',physical_clock_tree_status='NOT_IMPLEMENTED',extracted_parasitics_status='NOT_RUN',high_fanout_net_count=count,assumed_fanout_for_delay=int(warning_rows[0][1]) if warning_rows else None,high_fanout_nets=list(nets.values()),non_clock_high_fanout_net_count=sum(name!='clk' for name in nets),note='Mapped synthesis uses an ideal clock and no physical clock-tree load or skew model; this is not clock-network signoff.')
def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('run',type=Path);ap.add_argument('--out',type=Path,default=ROOT/'evidence/core/synthesis.json');a=ap.parse_args();run=a.run.resolve();meta=json.loads((run/'run.json').read_text())
    assert meta['status']=='COMPLETED_REPORTS_REQUIRE_REVIEW' and meta['exit_code']==0 and (run/'completed.txt').exists()
    for rel,digest in meta['source_sha256'].items():
        assert sha(run/'source'/Path(rel).name)==digest
        assert sha(ROOT/rel)==digest,'Current synthesis source differs from the frozen run'
    runner=ROOT/meta['producer_path'];frozen_runner=run/'source'/runner.name
    if not frozen_runner.exists():
        assert sha(runner)==meta['producer_sha256'],'Original runner must be frozen before portable launcher changes'
        shutil.copyfile(runner,frozen_runner)
    assert sha(frozen_runner)==meta['producer_sha256'],'Frozen synthesis runner differs from actual run metadata'
    library=Path(meta['library_path']);dc=Path(meta['tool_path']);assert sha(library)==meta['library_sha256'] and sha(dc)==meta['tool_sha256']
    assert not re.search(r'^Error:',(run/'dc.log').read_text(),re.M),'DC error in original log'
    script=ROOT/'rtl/sparse_gate/synth/recheck_dc.tcl';producer_locks={p:sha(p) for p in [Path(__file__).resolve(),script]};shutil.copyfile(script,run/'source'/script.name)
    p=subprocess.run([str(dc),'-f','source/recheck_dc.tcl'],cwd=run,env=dict(os.environ,SG_LIBRARY=str(library)),capture_output=True,text=True);(run/'readback.log').write_text(p.stdout+p.stderr)
    assert p.returncode==0,'DC readback process failed'
    readback_errors=re.findall(r'^Error:.*$',p.stdout+p.stderr,re.M)
    if readback_errors:
        assert kv(run/'readback_timing_coverage_status.txt').get('status')=='NOT_CHECKED','DC readback failure'
        coverage_errors=set(re.findall(r'^Error:.*$',(run/'readback_check_timing.rpt').read_text(),re.M))
        assert all(error in coverage_errors for error in readback_errors),'Error outside the explicitly unsupported timing-coverage query'
    m=kv(run/'mapping_status.txt');r=kv(run/'readback_mapping.txt');assert m['current_design']==r['current_design']=='sg_index_core';assert m['is_mapped']=='true' and r['is_mapped']=='true';assert int(m['gtech_or_seqgen_cells'])==0 and int(r['unbound_leaf_reference_count'])==0
    for key in ['leaf_cells','registers']:assert m[key]==r[key]
    assert '1.0e-09 Second(ns)' in (run/'units.rpt').read_text() and '1.0e-09 Second(ns)' in (run/'readback_units.rpt').read_text()
    assert '1.0e-12 Farad(pF)' in (run/'units.rpt').read_text() and '1.0e-12 Farad(pF)' in (run/'readback_units.rpt').read_text()
    sdc=(run/'mapped.sdc').read_text()
    actual_periods=re.findall(r'^create_clock\s+.*?-period\s+([0-9.eE+-]+)',sdc,re.M)
    assert len(actual_periods)==1 and float(actual_periods[0])==meta['clock_ns'],'Saved SDC clock differs from declared constraint'
    setup=slack(run/'setup.rpt');hold=slack(run/'hold.rpt');assert setup==slack(run/'readback_setup.rpt') and hold==slack(run/'readback_hold.rpt')
    setup_violated=timing_violated(run/'setup.rpt');hold_violated=timing_violated(run/'hold.rpt')
    assert setup_violated==timing_violated(run/'readback_setup.rpt') and hold_violated==timing_violated(run/'readback_hold.rpt')
    area_text=(run/'area.rpt').read_text()
    match=re.search(r'Total cell area:\s*([0-9.]+)',area_text);assert match;area=float(match.group(1))
    assert area>0 and int(m['leaf_cells'])>0 and int(m['registers'])>0,'Empty or zero-area implementation'
    area_parts={}
    for label,key in [('Combinational area','combinational_cell_area_library_units'),('Noncombinational area','noncombinational_cell_area_library_units'),('Macro/Black Box area','macro_or_black_box_area_library_units')]:
        part=re.search(r'^\s*'+re.escape(label)+r':\s*([0-9.]+)',area_text,re.M)
        if part:area_parts[key]=float(part.group(1))
    lib_rows=(run/'readback_library_cell_areas.tsv').read_text().splitlines()
    assert lib_rows[0]=='cell\tarea_library_units'
    lib_areas=[row.split('\t') for row in lib_rows[1:]]
    assert lib_areas and all(len(row)==2 and float(row[1])>0 for row in lib_areas)
    assert len({row[0] for row in lib_areas})==len(lib_areas),'Duplicate library cell in readback'
    reports=['area.rpt','setup.rpt','hold.rpt','units.rpt','mapped.sdc','references.rpt','mapping_status.txt','check_mapped.rpt','clocks.rpt','qor.rpt','violations.rpt','completed.txt','readback_setup.rpt','readback_hold.rpt','readback_units.rpt','readback_mapping.txt','readback_check.rpt','readback_library_cell_areas.tsv','readback_check_timing.rpt','readback_timing_coverage_status.txt','readback_ports.rpt','dc.log','readback.log','mapped.ddc','mapped.v','run.json']
    timing_ok=setup>=0 and hold>=0 and not setup_violated and not hold_violated
    all_constraint_counts,drv_counts=constraint_counts(run/'violations.rpt');drv_count=sum(drv_counts.values());drv_ok=drv_count==0
    coverage=timing_coverage(run,meta,sdc)
    clock=clock_model(run)
    known_tt_library=meta['library_sha256']=='5363ad782af12e7cec187d23d27696c136d9d9014b8ba645b544228b18caf8e4'
    out=dict(schema_version=1,status='MAPPED_TIMING_MET' if timing_ok else 'MAPPED_TIMING_NOT_CLOSED',passed=timing_ok and drv_ok and coverage['passed'],completed=True,mapped=True,mapping_passed=True,physical_signoff=False,gate_level_equivalence_status='NOT_RUN',target_period_ns=meta['clock_ns'],library_corner='TT 0.9V 25C' if known_tt_library else 'UNSPECIFIED_FOR_DIFFERENT_LIBRARY',timing_coverage=coverage,
        scope=meta['scope'],config=meta['config'],clock_ns=meta['clock_ns'],setup_slack_ns=setup,hold_slack_ns=hold,setup_violated=setup_violated,hold_violated=hold_violated,timing_passed=timing_ok,cell_area_library_units=area,area_unit_note='Supplied library cell area units; not routed/core/die area or node scaling',leaf_cells=int(m['leaf_cells']),registers=int(m['registers']),unmapped_leaf_references=0,
        units=dict(time='ns',capacitance='pF'),constraints={k:meta[k] for k in ['uncertainty_ns','input_delay_ns','output_delay_ns','output_load_pF']},
        design_rule_violation_count=drv_count,design_rule_violation_counts=drv_counts,design_rules_passed=drv_ok,constraint_violation_counts=all_constraint_counts,design_rule_count_scope='Reported electrical-constraint violation rows; same object may occur in multiple categories. Excludes setup/hold and zero-valued area/power optimization objectives; not physical DRC.',clock_model=clock,
        source_sha256=meta['source_sha256'],library=dict(name=library.name,sha256=meta['library_sha256'],copied=False,cell_area_readback_count=len(lib_areas)),library_cell_areas=dict(sha256=sha(run/'readback_library_cell_areas.tsv'),rows=len(lib_areas)),tool=dict(name=dc.name,sha256=meta['tool_sha256']),
        private_run_path=str(run.relative_to(ROOT)),artifact_sha256={name:sha(run/name) for name in reports},
        run_producer=dict(source_path=meta['producer_path'],used_sha256=meta['producer_sha256'],private_snapshot='source/'+runner.name),
        reproduction_entrypoint=dict(source_path=meta['producer_path'],sha256=sha(runner),note='Public launcher may differ in portable tool/library path resolution, private output location, and launcher snapshot bookkeeping; used runner identity remains separately frozen'),
        producer_sha256={str(p.relative_to(ROOT)):digest for p,digest in producer_locks.items()},
        commands=['dc_shell -f source/core_dc.tcl','dc_shell -f source/recheck_dc.tcl'],elapsed_seconds=meta['elapsed_seconds'],**area_parts)
    for rel,digest in meta['source_sha256'].items():
        assert sha(run/'source'/Path(rel).name)==digest
        assert sha(ROOT/rel)==digest,'Current synthesis source changed during readback'
    assert sha(library)==meta['library_sha256'] and sha(dc)==meta['tool_sha256'] and sha(frozen_runner)==meta['producer_sha256']
    for p,digest in producer_locks.items():assert sha(p)==digest,'Readback producer changed while executing'
    assert sha(run/'source'/script.name)==producer_locks[script]
    a.out.parent.mkdir(parents=True,exist_ok=True);a.out.write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps(out,indent=2))
if __name__=='__main__':main()
