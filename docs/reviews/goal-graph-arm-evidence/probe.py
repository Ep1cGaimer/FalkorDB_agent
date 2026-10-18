import dataclasses,hashlib,json,os,subprocess,time,traceback,uuid
from pathlib import Path
from rw import graph as G
from rw.repo.index import index_repository
from confirmatory.corpus_export import canonical
from confirmatory.plaintext_tools import PlaintextTools
from confirmatory.graph_tools import GraphTools,config_for_export
from confirmatory.tool_budget import ToolSession

out=Path('artifacts/graph-development/requests-001')
out.mkdir(exist_ok=False,parents=True)
name='rw-graph-arm-'+uuid.uuid4().hex[:10]
image='falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6'
record={'classification':'DEVELOPMENT_GRAPH_CORPUS_DIAGNOSTIC','acceptance_validated':False,'heldout':False,'container':name,'image':image,'checks':[]}
trace=[]
try:
 subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1::6379',image],check=True,capture_output=True)
 info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
 port=info['NetworkSettings']['Ports']['6379/tcp'][0]['HostPort']
 os.environ.update(RW_FALKORDB_HOST='127.0.0.1',RW_FALKORDB_PORT=port)
 record['host_port']=port
 db=G.connect(socket_timeout=2)
 for _ in range(40):
  try:
   if db.connection.ping():break
  except Exception:time.sleep(.1)
 else:raise RuntimeError('owned DB unavailable')
 raw=PlaintextTools(Path('artifacts/corpus-development/requests-full-002'))
 cfg=config_for_export(raw,Path('artifacts/repos/requests').resolve())
 record['config']=cfg.model_dump(mode='json')
 started=time.monotonic()
 report=index_repository(cfg,graph_name='development_requests',db=db)
 record['import_elapsed_seconds']=time.monotonic()-started
 record['import']=dataclasses.asdict(report)
 (out/'import.json').write_bytes(canonical(record['import']))
 arm=GraphTools(raw,'development_requests',db=db,trace=trace)
 started=time.monotonic()
 record['attestation']=arm.prepare()
 record['attestation_seconds']=time.monotonic()-started
 record['checks'].append('exact full historical commit/file/parent corpus attestation')
 sha=raw.spec['roots'][0]
 caps,_=arm.capabilities()
 with ToolSession(caps) as session:
  found=session.call('symbols',{'revision':sha,'name':'request','limit':20})
  assert found['status']=='OK',found
  matches=[x for x in found['result']['items'] if x['qualname'].endswith('.Session.request')]
  assert len(matches)==1
  symbol=matches[0]
  cite=symbol['citation']
  span=session.call('read_file',{'revision':sha,'path':cite['path'],'start':cite['start_line'],'end':min(cite['start_line']+25,cite['end_line'])})
  assert span['status']=='OK' and 'def request' in span['result']['content']
  assert span['result']['citation']['content_hash']==cite['content_hash']
  relationships=session.call('dependencies',{'revision':sha,'symbol':symbol['qualname'],'hops':2,'limit':10})
  assert relationships['status']=='OK' and relationships['result']['items']
  record['checks'].extend(['actual graph symbol lookup','common raw-source span/hash equality','two-hop graph relationship retrieval'])
  record['question_tool_usage']=session.budget.snapshot()
  (out/'tool-trace.json').write_bytes(canonical(session.trace))
 # Make a real owned service outage; the in-memory raw export remains readable.
 subprocess.run(['docker','stop',name],check=True,capture_output=True)
 with ToolSession(caps) as outage:
  result=outage.call('read_file',{'revision':sha,'path':cite['path'],'start':cite['start_line'],'end':cite['start_line']})
  assert result['status']=='UNAVAILABLE' and result['result'] is None,result
  record['outage_response']=result
 record['checks'].append('actual owned DB shutdown prevents raw-source graph-arm fallback')
 record['status']='PASS'
except Exception as exc:
 record.update(status='ERROR',error_type=type(exc).__name__)
 (out/'failure.txt').write_text(traceback.format_exc())
finally:
 (out/'graph-trace.json').write_bytes(canonical(trace))
 result=subprocess.run(['docker','rm','-f',name],capture_output=True)
 record['cleanup_exit_code']=result.returncode
 record['trace_events']=len(trace)
 record['trace_sha256']=hashlib.sha256((out/'graph-trace.json').read_bytes()).hexdigest()
 (out/'summary.json').write_bytes(canonical(record))
 print(json.dumps({k:record.get(k) for k in ['status','error_type','checks','trace_events','import_elapsed_seconds','attestation_seconds','cleanup_exit_code']}))
