import json,os,socket,subprocess,sys,tempfile,time,unittest
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
class PipelineHTTPTests(unittest.TestCase):
 def test_registered_http_skill_harness_and_controls(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as temp:
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
   script='''import server,io,json
from docx import Document
doc=Document();doc.add_paragraph('真实经历');out=io.BytesIO();doc.save(out)
server.LIBRARY.add('base.docx',out.getvalue())
server.DATA.write_text(json.dumps({'preferences':'AI岗位，至少30K'}))
server.BATCHES.start_scheduler=lambda:None
server.main()
'''
   with open(Path(temp)/'log','w') as log:
    proc=subprocess.Popen([sys.executable,'-c',script],cwd=root,env={**os.environ,'CAREER_HOME':temp,'CAREER_PORT':str(port)},stdout=log,stderr=log)
    try:
     base=f'http://127.0.0.1:{port}'
     for _ in range(100):
      try:token=json.load(urlopen(base+'/api/state',timeout=1))['token'];break
      except Exception:time.sleep(.05)
     def req(path,body=None):
      return json.load(urlopen(Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers={'X-App-Token':token,'Content-Type':'application/json'}),timeout=5))
     with self.assertRaises(HTTPError):req('/api/pipeline',{'action':'create','target_count':100,'authorized':False,'consent':True})
     r=req('/api/pipeline',{'action':'create','target_count':100,'authorized':True,'consent':True});key=r['id']
     self.assertEqual(req('/api/harness')['runs'][0]['id'],key)
     self.assertEqual(req('/api/pipeline',{'action':'status'})['runs'][0]['target_count'],100)
     req('/api/harness',{'action':'pause','id':key});self.assertEqual(req('/api/pipeline',{'action':'status'})['runs'][0]['status'],'paused')
     req('/api/pipeline',{'action':'resume','id':key});self.assertEqual(req('/api/pipeline',{'action':'status'})['runs'][0]['status'],'scheduled')
     req('/api/harness',{'action':'cancel','id':key});self.assertEqual(req('/api/pipeline',{'action':'status'})['runs'][0]['status'],'cancelled')
     self.assertEqual(req('/api/library')['applications'],[])
    finally:proc.terminate();proc.wait(timeout=5)
