import json,os,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
class JobStatusHTTPTests(unittest.TestCase):
 def test_schema_query_authorization_validation_and_read_only(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as temp:
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
   script='''import server
server.TRACKER.register({'job_id':'a','title':'测试','company':'工程样例公司'})
server.TRACKER.event('a','greet','sent','fixture',{'source':'manual'})
server.model_process=lambda *a,**k:(_ for _ in ()).throw(AssertionError('direct tool must not call model'))
server.main()
'''
   with open(Path(temp)/'log','w') as log:
    proc=subprocess.Popen([sys.executable,'-c',script],cwd=root,env={**os.environ,'CAREER_HOME':temp,'CAREER_PORT':str(port)},stdout=log,stderr=log)
    try:
     base=f'http://127.0.0.1:{port}'
     for _ in range(100):
      try:
       with urlopen(base+'/api/state',timeout=1) as r:token=json.load(r)['token']
       break
      except Exception:time.sleep(.05)
     def request(path,data=None,auth=True):
      headers={'Content-Type':'application/json'}
      if auth:headers['X-App-Token']=token
      with urlopen(Request(base+path,data=None if data is None else json.dumps(data).encode(),headers=headers),timeout=4) as r:return json.load(r)
     schema=request('/api/job-status/schema');self.assertIn('greet',schema['filters']);self.assertEqual(schema['effect'],'read_only')
     args={'query':'工程样例','filters':{'greet':'sent','reply':'no_reply'},'date':'all','date_basis':'collected','include_history':True}
     r=request('/api/job-status',args)['tool_results'][0]
     self.assertEqual(r['count'],1);self.assertEqual(r['jobs'][0]['history'][0]['value'],'sent')
     with self.assertRaises(HTTPError) as denied:request('/api/job-status/schema',auth=False)
     self.assertEqual(denied.exception.code,403)
     with self.assertRaises(HTTPError) as bad:request('/api/job-status',args|{'filters':{'resume_acceptance':'passed'}})
     self.assertEqual(bad.exception.code,400)
     again=request('/api/job-status',args)['tool_results'][0]
     self.assertEqual(r['jobs'],again['jobs'])
    finally:proc.terminate();proc.wait(timeout=5)
