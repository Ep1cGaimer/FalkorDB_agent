import dataclasses,json,os,time,traceback
from pathlib import Path
from confirmatory.corpus_export import canonical
from confirmatory.plaintext_tools import PlaintextTools
from confirmatory.graph_tools import GraphTools,config_for_export
from confirmatory.citation_guard import CitationGuard,SOURCE_FIELDS
from confirmatory.tool_budget import ToolSession
from rw.repo.index import index_repository
os.environ['RW_FALKORDB_PORT']='51733'
out=Path('artifacts/model-development/real-reference-probes-001');out.mkdir(exist_ok=False)
record={'classification':'DETERMINISTIC_DEVELOPMENT_REAL_GRAPH_REFERENCE_CHECK_NOT_ANSWER_QUALITY','acceptance_validated':False,'repositories':[]}
for name,graph,symbol in [('requests','rw_goal_citation_pilot_001','request'),('itsdangerous','rw_goal_citation_itsdangerous_001','URLSafeTimedSerializer')]:
 item={'repository':name}; trace=[]; started=time.monotonic()
 try:
  raw=PlaintextTools(Path('artifacts/corpus-development')/(name+'-full-'+('002' if name=='requests' else '001')))
  if name=='itsdangerous':item['import']=dataclasses.asdict(index_repository(config_for_export(raw,Path('artifacts/repos')/name),graph))
  arm=GraphTools(raw,graph,trace=trace);item['attestation']=arm.prepare();sha=raw.spec['roots'][0]
  caps,_=arm.capabilities()
  with ToolSession(caps) as session:
   found=session.call('symbols',{'revision':sha,'name':symbol,'limit':20})
   assert found['status']=='OK'
   chosen=next(x for x in found['result']['items'] if x['qualname'].endswith('.Session.request' if name=='requests' else '.URLSafeTimedSerializer'))
   dependencies=session.call('dependencies',{'revision':sha,'symbol':chosen['qualname'],'hops':2,'limit':10})
   assert dependencies['status']=='OK' and any(x['hops']==2 and not x['external'] for x in dependencies['result']['items'])
   refs=[];pending=[e['response'].get('result') for e in session.trace]
   while pending:
    value=pending.pop()
    if isinstance(value,list):pending.extend(value)
    elif isinstance(value,dict):
     if SOURCE_FIELDS<=set(value) or value.get('proof_type')=='file_membership':refs.append(value)
     else:pending.extend(value.values())
   item['reference_validation']=CitationGuard(raw).verify(refs,session.trace)
   assert refs and item['reference_validation']['valid'],item['reference_validation']
   (out/(name+'-tool-trace.json')).write_bytes(canonical(session.trace))
   item['tool_usage']=session.budget.snapshot()
  item.update(status='PASS',hops=sorted({x['hops'] for x in dependencies['result']['items']}))
 except Exception as exc:
  item.update(status='ERROR',failure=type(exc).__name__)
  (out/(name+'-error.txt')).write_text(traceback.format_exc())
 finally:
  item['seconds']=time.monotonic()-started;record['repositories'].append(item)
  (out/(name+'-graph-trace.json')).write_bytes(canonical(trace))
  (out/'summary.json').write_bytes(canonical(record))
print(json.dumps([{k:x.get(k) for k in ['repository','status','reference_validation','seconds']} for x in record['repositories']]))
