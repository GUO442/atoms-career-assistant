import concurrent.futures,json,os,socket,subprocess,sys,tempfile,time,unittest,uuid
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request,urlopen

class ChatStopHTTPTests(unittest.TestCase):
 def test_http_stop_releases_lock_and_early_stop_is_honored(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as temp:
   work=Path(temp);skill=work/'skills/boss-web-tools';skill.mkdir(parents=True);(skill/'SKILL.md').write_text('Fixture skill for HTTP tests.')
   marker=work/'model-started'
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
   bootstrap='''import server,sys,json
from pathlib import Path
from execution_control import managed_run
marker=Path(server.ROOT)/'model-started'
def fake_model(*args,**kwargs):
 assert kwargs['timeout']==40
 delay=0 if marker.exists() else 30
 marker.write_text('started')
 result=managed_run([sys.executable,'-c','import time;time.sleep('+str(delay)+');print("NEXT_OK")'],capture_output=True,text=True,timeout=40)
 result.stdout=json.dumps({"tool":"chat.respond","arguments":{"answer":result.stdout.strip()}})
 return result
server.model_process=fake_model
server.boss_chat.run=lambda *args:[]
server.main()
'''
   log=open(work/'log','w');process=subprocess.Popen([sys.executable,'-c',bootstrap],cwd=root,env={**os.environ,'CAREER_HOME':str(work),'CAREER_PORT':str(port)},stdout=log,stderr=log)
   base=f'http://127.0.0.1:{port}'
   try:
    for _ in range(100):
     try:
      with urlopen(base+'/api/state',timeout=1) as r:token=json.load(r)['token']
      break
     except Exception:
      if process.poll() is not None:self.fail((work/'log').read_text())
      time.sleep(.05)
    else:self.fail('test server failed to start')
    def post(path,data,key=None,authenticated=True):
     headers={'Content-Type':'application/json'}
     if authenticated:headers['X-App-Token']=token
     if key:headers['X-Request-ID']=key
     with urlopen(Request(base+path,data=json.dumps(data).encode(),headers=headers),timeout=8) as r:return json.load(r)
    body={'consent':True,'messages':[{'role':'user','content':'hello'}]}
    key=uuid.uuid4().hex
    with concurrent.futures.ThreadPoolExecutor() as executor:
     pending=executor.submit(post,'/api/chat',body,key)
     for _ in range(100):
      if marker.exists():break
      time.sleep(.03)
     self.assertTrue(marker.exists())
     stopped=post('/api/chat/stop',{'request_id':key});self.assertEqual(stopped['status'],'cancel_requested')
     result=pending.result(timeout=3);self.assertTrue(result['cancelled'])
    self.assertEqual(post('/api/chat',body,uuid.uuid4().hex)['answer'],'NEXT_OK')
    early=uuid.uuid4().hex;post('/api/chat/stop',{'request_id':early})
    self.assertTrue(post('/api/chat',body,early)['cancelled'])
    with self.assertRaises(HTTPError) as unauthorized:post('/api/chat/stop',{'request_id':uuid.uuid4().hex},authenticated=False)
    self.assertEqual(unauthorized.exception.code,403)
    with self.assertRaises(HTTPError) as invalid:post('/api/chat/stop',{'request_id':'../invalid'})
    self.assertEqual(invalid.exception.code,400)
   finally:process.terminate();process.wait(timeout=5);log.close()
