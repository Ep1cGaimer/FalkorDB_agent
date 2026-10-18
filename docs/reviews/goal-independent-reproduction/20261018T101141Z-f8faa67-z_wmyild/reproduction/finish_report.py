"""Publish new reproduction evidence only after the unchanged run has finished."""
import datetime
import hashlib
import json
import pathlib
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET

BASE=pathlib.Path(__file__).resolve().parent
OUT=BASE/'artifacts'
REPO=BASE/'repo'
PARENT=pathlib.Path('/Users/vinay2047/.codex/worktrees/4f55/FalkorDB_agent')

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def main():
    results=json.loads((OUT/'check-results.json').read_text())
    approval=json.loads((BASE/'approved-target.json').read_text())
    target=approval['commit']
    root=ET.parse(OUT/'pytest.xml').getroot()
    cases=[]
    for node in root.iter('testcase'):
        status='PASS';detail=''
        for name in ['failure','error','skipped']:
            child=node.find(name)
            if child is not None:status={'failure':'FAIL','error':'ERROR','skipped':'SKIPPED'}[name];detail=child.get('message','');break
        cases.append({'class':node.get('classname'),'name':node.get('name'),'seconds':float(node.get('time','0')),'status':status,'detail':detail})
    counts={s:sum(c['status']==s for c in cases) for s in ['PASS','FAIL','ERROR','SKIPPED']}
    pytest_log=next(pathlib.Path(r['log']) for r in results if r['label']=='pytest-final')
    text=pytest_log.read_text()
    deselected=re.findall(r'(\d+) deselected',text)
    summary_lines=[line for line in text.splitlines() if re.search(r'\d+ passed|\d+ failed|\d+ skipped|\d+ error',line)]
    skips=[c for c in cases if c['status']=='SKIPPED']
    failed=[c for c in cases if c['status'] in ('FAIL','ERROR')]
    before=json.loads((OUT/f'target-{target[:7]}-manifest-before.json').read_text())
    after=json.loads((OUT/f'target-{target[:7]}-manifest-after.json').read_text())
    seal=PARENT/'artifacts/confirmatory/sealed/sealed-integrity.draft-v2.json'
    sealed=json.loads(seal.read_text())
    seal_errors=[]
    for rel,expected in sealed['files'].items():
        actual=sha(PARENT/rel)
        if actual!=expected:seal_errors.append({'path':rel,'expected':expected,'actual':actual})
    with (OUT/'seal-preservation-after-tests.json').open('x') as f:json.dump({'at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'operation':'Byte hash only; no oracle prose used','files':len(sealed['files']),'mismatches':seal_errors},f,indent=2,sort_keys=True);f.write('\n')
    pytest_result=next(r for r in results if r['label']=='pytest-final')
    js_result=next(r for r in results if r['label'].startswith('javascript-host'))
    smoke_result=next(r for r in results if r['label']=='deterministic-smoke-final')
    js_text=pathlib.Path(js_result['log']).read_text()
    js_count=lambda label: int(re.search(r'(?:ℹ |# )'+label+r' (\d+)',js_text).group(1))
    env=json.loads((OUT/'39-linux-env-final.log').read_text())
    realrepo=[c for c in cases if ('test_e1_onboarding' in (c['class'] or '')) or 'test_requests_bounded_slice_smoke' in c['name']]
    owned=json.loads((BASE/'run-attempt2.json').read_text())
    remaining=[]
    for name in [owned['container'],owned['python_container']]:
        r=subprocess.run(['docker','inspect',name],capture_output=True)
        if r.returncode==0:remaining.append(name)
    report={'schema':'independent-development-reproduction/v1','recorded_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'reviewer':'Independent Codex AI subagent; AI-assisted, no human review asserted','scope':'Development deterministic reproduction, not full T11 or v1 validation','initial_setup_commit':'812ecf7e2153d7662f6523a80365b0622cf92ceb','tested_commit':target,'pin_amendment':approval,'clean_clone':str(REPO),'preserved_run_root':str(BASE),'environment':env,'database_image':owned['image'],'python_image_id':owned['python_image_id'],'database_host_binding':owned['host_endpoint'],'test_namespace_endpoint':owned['namespace_endpoint'],'tests':{'pytest':{'command':pytest_result['command'],'returncode':pytest_result['returncode'],'elapsed_seconds':pytest_result['elapsed_seconds'],'counts':counts,'collected_run_cases':len(cases),'deselected_live_cases':int(deselected[-1]) if deselected else None,'summary_lines':summary_lines[-3:],'skips':skips,'failures':failed,'realrepo_cases':realrepo},'javascript':{'returncode':js_result['returncode'],'passed':js_count('pass'),'failed':js_count('fail'),'skipped':js_count('skipped'),'scope':'Host Node, same approved commit; zero DB/model use'},'smoke':{'returncode':smoke_result['returncode'],'elapsed_seconds':smoke_result['elapsed_seconds'],'scope':'Synthetic deterministic fixture, fixed grounding; no model calls'}},'source_integrity':{'before':{'files':before['files_checked'],'mismatches':len(before['mismatches'])},'after':{'files':after['files_checked'],'mismatches':len(after['mismatches'])},'tracked_git_status_after':(OUT/next(p.name for p in OUT.glob('*-git-approved-after.log'))).read_text(),'source_or_test_expectation_edits':False},'seal_integrity':{'files_checked':len(sealed['files']),'mismatches':seal_errors,'heldout_product_questions_run':0,'click_repository_used':False},'setup_attempts':{'host_python':'Fresh Python3.12.13 venv, all42 pinned dependencies installed; unused for Python tests because two fixtures hardcode6379','first_container':'Debian HTTP sources403; owned DB/Python containers removed','https_retry':'HTTP sources replaced by HTTPS inside owned runner only. Original driver held/replaced at parent request; raw apt result was not collected, partial package downloads retained','harness_errors_preserved':['Attempt2 driver string quoting syntax error before any product invocation','Parallel setup used noncanonical /tmp mount path; corrected to /private/tmp','uv status banner in merged freeze log was filtered into a new exact-requirements.clean.txt; original retained'],'completed_system_setup':'Git-only apt install resumed successfully from cached downloads. Node binary copied from pinned owned FalkorDB image; initial missing libatomic was resolved by installing libatomic1. All commands/raw failures retained.','pin_migration':'Parent amended source before pytest started; original812 setup and new168-file verification retained separately'},'cleanup':{'remaining_owned_containers':remaining,'unrelated_services_stopped':False,'clone_and_artifacts_retained':True},'limitations':['No independent new oracle authoring after implementation/results access; sealed cases unchanged','No Click/confirmatory product execution, no live held-out rerun, no blinded answer/evidence scoring or adjudication','No complete T0 freeze/signature/model/baseline/token/power verification','No T6 performance acceptance, T10 comparative advantage or three live T11 demos; no broader requirement validation claimed']}
    timestamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    destination=PARENT/'docs/reviews/goal-independent-reproduction'/f'{timestamp}-{target[:7]}-z_wmyild'
    destination.mkdir(parents=True,exist_ok=False)
    with (destination/'report.json').open('x') as f:json.dump(report,f,indent=2,sort_keys=True);f.write('\n')
    shutil.copytree(OUT,destination/'artifacts')
    scripts=destination/'reproduction'
    scripts.mkdir()
    for name in ['reproduce.py','container_checks.py','container_checks_attempt2.py','run_final_checks.py','finish_report.py','run.json','run-attempt2.json','approved-target.json','exact-requirements.txt','exact-requirements.clean.txt']:
        shutil.copy2(BASE/name,scripts/name)
    generated=destination/'generated-development-artifacts'
    for path in sorted((REPO/'artifacts').rglob('*.json')):
        rel=path.relative_to(REPO/'artifacts')
        if 'repos' in rel.parts:continue
        target_path=generated/rel;target_path.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target_path)
    pytest_line=f"{counts['PASS']} passed, {counts['FAIL']} failed, {counts['ERROR']} errors, {counts['SKIPPED']} skipped"
    verdict='PASS' if all(r['returncode']==0 for r in results) and not before['mismatches'] and not after['mismatches'] and not seal_errors and not remaining else 'FAIL_OR_INCOMPLETE'
    markdown=f'''# Independent development reproduction — {target[:7]}

Outcome: **{verdict}** for the recorded development checks. This is an independent
AI-assisted reproduction, not a human review or full T11/v1 validation.

| Check | Observed result |
|---|---|
| Full Python suite, `-m "not live"`, both realrepo flags enabled | {pytest_line}; {report['tests']['pytest']['deselected_live_cases']} live cases deselected |
| JavaScript tests on host Node | {report['tests']['javascript']['passed']} passed, {report['tests']['javascript']['failed']} failed, {report['tests']['javascript']['skipped']} skipped |
| Deterministic synthetic smoke | exit {smoke_result['returncode']} |
| Approved source bytes before/after | {before['files_checked']}/{after['files_checked']} files checked; {len(before['mismatches'])}/{len(after['mismatches'])} mismatches |
| Sealed evaluator bytes | {len(sealed['files'])} files checked; {len(seal_errors)} mismatches |
| Owned containers remaining | {len(remaining)} |

The clean clone is `{REPO}` and remains retained with its artifacts and fresh
environments. Setup began on `812ecf7`; before any Python test ran, the parent
amended the target to immutable `{target}`. The original setup and approved
source-manifest receipts are both retained. No source or test expectations were
edited to obtain a pass.

Python tests ran on Linux/aarch64 with Python {env['python'].split()[0]} in a fresh
venv installing the exact pyproject pins, MCP2.3.0 and pytest9.1.1, plus their42
resolved pins. The pinned FalkorDB image was `{owned['image']}`. Its host port was
OS-assigned on loopback; the Python runner shared only that owned DB's network
namespace and used127.0.0.1:6379 internally. This isolates two legacy fixtures
that explicitly select6379. The shared host6379 service was never used or stopped.

Requests and ItsDangerous were fresh `--bare --no-hardlinks` development copies
at configuration paths. Click's repository and the confirmatory questions were
not used. Node used for Python subprocess checks came from the pinned owned
FalkorDB image; host JavaScript tests used the host Node runtime. Exact versions,
binary provenance, commands, environment, raw setup/test logs and JUnit are retained.

Setup attempts are retained, including Debian HTTP403, a driver quoting error,
mount-path correction, freeze-banner filtering and initial missing libatomic for
Node. Those are setup outcomes, not product-test failures. The final Git-only apt
install and Node prerequisite checks completed before pytest. The initial driver
was stopped/replaced to honor the parent's pre-test source-pin hold.

The exact skip reasons, per-test statuses, realrepo-case outcomes and failure
details are in[report.json](report.json), with raw output under[artifacts/](artifacts/).
The full commands run the unmodified source at the approved pin. To repeat, use a
new clone at that commit, exact pinned requirements, and an owned DB/Python network
namespace; mount the clone at the same absolute path used by its test processes.

No held-out generation, live12-question T11 rerun, blind scoring/recomputation,
comparative advantage experiment or three live demos was performed. T0's frozen
contract and remaining mandatory fields are still pending. These development
checks cannot validate all T0–T11 goals or establish FalkorDB advantage.
'''
    with (destination/'report.md').open('x') as f:f.write(markdown)
    files={str(p.relative_to(destination)):sha(p) for p in sorted(destination.rglob('*')) if p.is_file()}
    manifest={'schema':'independent-reproduction-artifact-manifest/v1','created_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'tested_commit':target,'verdict':verdict,'files':files}
    with (destination/'MANIFEST.json').open('x') as f:json.dump(manifest,f,indent=2,sort_keys=True);f.write('\n')
    final={'report_directory':str(destination),'report_json_sha256':sha(destination/'report.json'),'manifest_sha256':sha(destination/'MANIFEST.json'),'verdict':verdict,'pytest':counts,'javascript':report['tests']['javascript'],'smoke_returncode':smoke_result['returncode'],'owned_containers_remaining':remaining}
    with (BASE/'final-handoff.json').open('x') as f:json.dump(final,f,indent=2,sort_keys=True);f.write('\n')
    print(json.dumps(final,indent=2))

if __name__=='__main__':main()
