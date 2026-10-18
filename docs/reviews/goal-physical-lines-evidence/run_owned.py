import json,os,subprocess,sys,uuid
from pathlib import Path
out=Path('artifacts/goal-physical-lines')
name='rw-physical-lines-'+uuid.uuid4().hex[:10]
image='falkordb/falkordb@sha256:107455e862a824e45e8e9f5a7fbfdf5e00a08b14e13eae2577c72fd9e3f59ba6'
record={'name':name,'image':image,'attempt':sys.argv[1]}
try:
 subprocess.run(['docker','run','-d','--name',name,'-p','127.0.0.1::6379',image],check=True,capture_output=True)
 info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
 port=info['NetworkSettings']['Ports']['6379/tcp'][0]['HostPort']
 record['host_port']=port
 import redis
 client=redis.Redis(host='127.0.0.1',port=int(port),socket_timeout=2)
 import time
 for n in range(40):
  try:
   if client.ping():break
  except redis.ConnectionError:time.sleep(.1)
 else:raise RuntimeError('owned DB unavailable')
 env={**os.environ,'RW_FALKORDB_HOST':'127.0.0.1','RW_FALKORDB_PORT':port}
 command=[sys.executable,'-m','pytest','-q',*(sys.argv[2:] or ['tests/repo/test_physical_source_lines.py']),'--tb=short','--junitxml='+str(out/(sys.argv[1]+'.xml'))]
 record['command']=command
 with (out/(sys.argv[1]+'.log')).open('w') as log:
  result=subprocess.run(command,env=env,stdout=log,stderr=subprocess.STDOUT)
 record['exit_code']=result.returncode
finally:
 result=subprocess.run(['docker','rm','-f',name],capture_output=True)
 record['cleanup_exit_code']=result.returncode
 (out/(sys.argv[1]+'.json')).write_text(json.dumps(record,indent=2)+'\n')
 print(json.dumps(record))
