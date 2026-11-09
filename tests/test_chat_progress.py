import concurrent.futures,json,os,socket,subprocess,sys,tempfile,time,unittest,uuid
from pathlib import Path
from urllib.request import Request,urlopen
from urllib.error import HTTPError
from chat_progress import snapshot

class ProgressTests(unittest.TestCase):
 def test_snapshot_only_exposes_one_public_line(self):
  result=snapshot({'id':'a','status':'running','started':time.time()-4,'events':[{'message':'开始：boss.read_jd'}],'spans':[{'input':'private data'}]})
  self.assertEqual(result['message'],'正在调用 boss.read_jd');self.assertNotIn('private',json.dumps(result));self.assertGreaterEqual(result['elapsed'],4)
 def test_terminal_status(self):
  for state,text in [('completed','已完成'),('failed','执行失败'),('cancelled','已停止')]:
   self.assertEqual(snapshot({'id':'a','status':state,'started':1,'ended':3,'events':[]})['message'],text)
 def test_http_progress_changes_before_chat_completes_and_local_list_bypasses_model(self):
  root=Path(__file__).resolve().parents[1]
  with tempfile.TemporaryDirectory() as temp:
   sock=socket.socket();sock.bind(('127.0.0.1',0));port=sock.getsockname()[1];sock.close()
   script='''import server,time,json
from chat_intents import IntentRouter
from observability import event
def model(*a):
 event('正在调用 test.read · 读取资料');time.sleep(.8)
 event('正在调用 test.analyze · 分析资料');time.sleep(.8)
 return json.dumps({'tool':'chat.respond','arguments':{'answer':'已完成测试'}})
def route(instruction,context):
 if context['messages'][-1]['content']=='你好':return model()
 if context['messages'][-1]['content']=='invalid':return json.dumps({'tool':'shell.execute','arguments':{}})
 return json.dumps({'tool':'resume.list','arguments':{'date':'today','basis':'created','kind':'all','reviewed':'all'}})
server.INTENT_ROUTER=IntentRouter(route)
server.run_model=lambda *a:(_ for _ in ()).throw(AssertionError('unexpected synthesis'))
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
     def get(key,auth=True):
      with urlopen(Request(base+'/api/progress/'+key,headers={'X-App-Token':token} if auth else {}),timeout=3) as r:return json.load(r)
     def post(text,key):
      data={'consent':True,'messages':[{'role':'user','content':text}]}
      with urlopen(Request(base+'/api/chat',data=json.dumps(data).encode(),headers={'X-App-Token':token,'X-Request-ID':key,'Content-Type':'application/json'}),timeout=5) as r:return json.load(r)
     key=uuid.uuid4().hex;seen=set()
     with concurrent.futures.ThreadPoolExecutor() as pool:
      future=pool.submit(post,'你好',key)
      for _ in range(100):
       try:seen.add(get(key)['message'])
       except HTTPError:pass
       if future.done():break
       time.sleep(.04)
      self.assertEqual(future.result()['answer'],'已完成测试')
     self.assertTrue(any('test.read' in x for x in seen));self.assertTrue(any('test.analyze' in x for x in seen))
     self.assertEqual(get(key)['status'],'completed')
     with self.assertRaises(HTTPError) as denied:get(key,False)
     self.assertEqual(denied.exception.code,403)
     self.assertIn('暂无已保存简历',post('我现在有哪些已经筛选出来的简历',uuid.uuid4().hex)['answer'])
     actual=post('今天帮我看一下一共筛选了哪些简历。',uuid.uuid4().hex)
     self.assertEqual(actual['tool_results'][0]['tool'],'resume.list')
     self.assertIn('按北京时间',actual['answer'])
     with self.assertRaises(HTTPError) as invalid:post('invalid',uuid.uuid4().hex)
     self.assertEqual(invalid.exception.code,502)
     self.assertIn('未通过校验',json.load(invalid.exception)['error'])
    finally:proc.terminate();proc.wait(timeout=5)
