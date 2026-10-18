import hashlib,json,os,shutil,subprocess,tempfile,time,uuid,xml.etree.ElementTree as ET
from pathlib import Path
root=Path.cwd().resolve()
base=Path(tempfile.mkdtemp(prefix='rw-goal-current-',dir='/private/tmp')).resolve()
stage=base/'repo'
out=root/'artifacts/goal-current-qa/full-001'
out.mkdir(exist_ok=False,parents=True)
venv=Path('/private/tmp/rw-independent-812ecf7-z_wmyild/linux-venv-attempt2')
image='rw-goal-qa:20261018'
db_image='falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6'
token=uuid.uuid4().hex[:10]
db_name='rw-goal-current-'+token
runner_name=db_name+'-python'
record={'classification':'PARENT_STAGED_WORKING_SOURCE_QA_NOT_INDEPENDENT','acceptance_validated':False,'heldout_questions_run':0,'stage':str(stage),'base':str(base),'containers':[db_name,runner_name],'commands':[]}
def command(args,label,*,env=None):
 t=time.monotonic()
 with (out/(label+'.log')).open('wb') as stream:
  p=subprocess.run(args,env=env,stdout=stream,stderr=subprocess.STDOUT)
 record['commands'].append({'command':list(map(str,args)),'log':label+'.log','exit_code':p.returncode,'seconds':time.monotonic()-t})
 (out/'progress.json').write_text(json.dumps(record,indent=2)+'\n')
 return p.returncode
try:
 assert command(['git','clone','--no-hardlinks',str(root),str(stage)],'01-clone')==0
 modified=subprocess.check_output(['git','ls-files','-m','-z'],cwd=root).split(b'\0')
 untracked=subprocess.check_output(['git','ls-files','--others','--exclude-standard','-z'],cwd=root).split(b'\0')
 overlay=[]
 for raw in modified+untracked:
  if not raw:continue
  rel=os.fsdecode(raw)
  if rel=='docs/GOAL_HANDOFF.md':continue
  if 'sealed' in Path(rel).parts or Path(rel).name.startswith('.env'):
   raise RuntimeError('private path unexpectedly selected for overlay')
  source=root/rel
  if source.is_file():
   dest=stage/rel;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,dest);overlay.append(rel)
 record['overlay_files']=sorted(set(overlay))
 manifest=json.loads((root/'docs/reviews/goal-model-runner-evidence/implementation-manifest.json').read_text())
 paths=set(manifest['files'])|{'evals/confirmatory/graph_tools.py','tests/repo/test_confirmatory_graph_tools.py','tests/repo/test_corpus_path_matching.py','tests/repo/test_parameterized_bases.py'}
 expected={rel:hashlib.sha256((root/rel).read_bytes()).hexdigest() for rel in sorted(paths)}
 before={rel:hashlib.sha256((stage/rel).read_bytes()).hexdigest() for rel in expected}
 assert before==expected,'stage differs from current working source'
 (out/'source-before.json').write_text(json.dumps({'files':expected,'mismatches':[]},indent=2)+'\n')
 for repo,url in [('requests','https://github.com/psf/requests.git'),('itsdangerous','https://github.com/pallets/itsdangerous.git')]:
  dest=stage/'artifacts/repos'/repo;dest.parent.mkdir(parents=True,exist_ok=True)
  assert command(['git','clone','--bare','--no-hardlinks',str(root/'artifacts/repos'/repo),str(dest)],'clone-'+repo)==0
  assert command(['git','-C',str(dest),'remote','set-url','origin',url],'origin-'+repo)==0
 record['status']='WAITING_FOR_OWNED_IMAGE'
 (out/'progress.json').write_text(json.dumps(record,indent=2)+'\n')
 deadline=time.monotonic()+1800
 while subprocess.run(['docker','image','inspect',image],capture_output=True).returncode!=0:
  if time.monotonic()>deadline:raise RuntimeError('owned image build not ready within setup deadline')
  time.sleep(5)
 assert command(['docker','image','inspect',image],'image')==0
 assert command(['docker','run','-d','--name',db_name,'--memory=6g',db_image],'db-start')==0
 for _ in range(40):
  r=subprocess.run(['docker','exec',db_name,'redis-cli','PING'],capture_output=True)
  if r.returncode==0 and r.stdout.strip()==b'PONG':break
  time.sleep(.1)
 else:raise RuntimeError('owned DB not ready')
 metadata=['docker','run','--rm','--network','container:'+db_name,'-v',str(venv)+':'+str(venv)+':ro',image,str(venv/'bin/python'),'-c',"import importlib.metadata,json,platform,subprocess,sys;print(json.dumps({'python':sys.version,'platform':platform.platform(),'git':subprocess.check_output(['git','--version']).decode().strip(),'node':subprocess.check_output(['node','--version']).decode().strip(),'packages':{d.metadata['Name']:d.version for d in importlib.metadata.distributions()}},sort_keys=True))"]
 assert command(metadata,'environment')==0
 pytest=['docker','run','--rm','--name',runner_name,'--network','container:'+db_name,'--memory=6g','-v',str(stage)+':'+str(stage),'-v',str(venv)+':'+str(venv)+':ro','-w',str(stage),'-e','RW_FALKORDB_HOST=127.0.0.1','-e','RW_FALKORDB_PORT=6379','-e','RW_REALREPO=1','-e','RW_REALREPO_SMOKE=1',image,str(venv/'bin/python'),'-m','pytest','-q','-m','not live','--tb=short','--junitxml=artifacts/current-qa.xml']
 code=command(pytest,'pytest')
 record['pytest_exit_code']=code
 xml=stage/'artifacts/current-qa.xml'
 if xml.exists():
  shutil.copyfile(xml,out/'pytest.xml')
  cases=list(ET.parse(xml).getroot().iter('testcase'))
  record['pytest']={'passed':sum(not any(c.find(x) is not None for x in ['skipped','failure','error']) for c in cases),'failed':sum(c.find('failure') is not None for c in cases),'errors':sum(c.find('error') is not None for c in cases),'skipped':[{'class':c.get('classname'),'name':c.get('name'),'reason':c.find('skipped').get('message')} for c in cases if c.find('skipped') is not None]}
 after={rel:hashlib.sha256((stage/rel).read_bytes()).hexdigest() for rel in expected}
 mismatch=[rel for rel in expected if expected[rel]!=after[rel]]
 record['source_files_checked']=len(expected);record['source_mismatches']=mismatch
 (out/'source-after.json').write_text(json.dumps({'files':after,'mismatches':mismatch},indent=2)+'\n')
 record['status']='PASS' if code==0 and not mismatch else 'FAILED'
except Exception as exc:
 import traceback
 record.update(status='SETUP_OR_DRIVER_ERROR',error_type=type(exc).__name__)
 (out/'driver-error.txt').write_text(traceback.format_exc())
finally:
 for name in [runner_name,db_name]:
  r=subprocess.run(['docker','rm','-f',name],capture_output=True)
  record.setdefault('cleanup',[]).append({'name':name,'remove_exit_code':r.returncode})
 remaining=subprocess.check_output(['docker','ps','-a','--filter','name='+db_name,'--format','{{.Names}}']).decode().splitlines()
 record['remaining_owned_containers']=remaining
 (out/'summary.json').write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps({k:record.get(k) for k in ['status','error_type','pytest','source_files_checked','source_mismatches','remaining_owned_containers']}))
