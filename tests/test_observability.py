import json, tempfile, threading, unittest
from pathlib import Path
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch
from observability import TraceStore, span, event, model_process, traced, capture

class ObservabilityTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=TraceStore(Path(self.tmp.name)/'traces.db')
  self.config=patch('observability.settings',return_value={'host':'','public':'','secret':'','project':''});self.config.start()
 def tearDown(self):self.config.stop();self.tmp.cleanup()
 def test_nested_spans_and_payload_capture(self):
  with self.store.trace('assistant') as key:
   with span('tool'):
    with patch('subprocess.run') as run:
     run.return_value.returncode=0;run.return_value.stdout='private answer'
     model_process(['fake'],input='private resume and credentials')
  r=self.store.get(key);self.assertEqual(r['status'],'completed');self.assertEqual(len(r['spans']),6)
  generation=next(s for s in r['spans'] if s['kind']=='generation');tool=next(s for s in r['spans'] if s['name']=='tool')
  self.assertEqual(generation['parent'],tool['id']);self.assertEqual(generation['input'],'private resume and credentials');self.assertEqual(generation['output'],'private answer');self.assertEqual(r['export'],'not_configured')
 def test_failures_and_restart(self):
  with self.assertRaises(RuntimeError):
   with self.store.trace('failed') as key:
    with span('bad tool'):raise RuntimeError('secret error text')
  r=self.store.get(key);self.assertEqual(r['status'],'failed');self.assertTrue(all(s['status']=='error' for s in r['spans'] if not s['name'].startswith('开始：')));self.assertIn('secret error text',json.dumps(r))
  interrupted=self.store.create('interrupted');restored=TraceStore(self.store.path);self.assertEqual(restored.get(interrupted)['status'],'interrupted')
 def test_concurrent_context_isolation(self):
  barrier=threading.Barrier(2);keys=[]
  def worker(name):
   with self.store.trace(name) as key:
    keys.append(key);barrier.wait();event(name)
  workers=[threading.Thread(target=worker,args=(n,)) for n in ['a','b']]
  for t in workers:t.start()
  for t in workers:t.join()
  for key in keys:
   r=self.store.get(key);self.assertEqual([e['message'] for e in r['events'] if e['message'] in ['a','b']],[r['name']])
 def test_otlp_delivery_and_failure_are_durable(self):
  bodies=[]
  class Sink(BaseHTTPRequestHandler):
   def do_POST(self):
    bodies.append((self.path,self.headers,json.loads(self.rfile.read(int(self.headers['Content-Length'])))))
    self.send_response(200);self.end_headers();self.wfile.write(b'{}')
   def log_message(self,*a):pass
  server=ThreadingHTTPServer(('127.0.0.1',0),Sink);thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
  with self.store.trace('export') as key:pass
  cfg={'host':f'http://127.0.0.1:{server.server_port}','public':'test-pk','secret':'test-sk','project':'project'}
  try:
   with patch('observability.settings',return_value=cfg):self.store.export(key);self.assertIn('/project/project/traces/',self.store.public(key)['langfuse_url'])
   self.assertEqual(self.store.get(key)['export'],'sent');self.assertEqual(bodies[0][0],'/api/public/otel/v1/traces');self.assertEqual(bodies[0][1]['x-langfuse-ingestion-version'],'4')
   self.assertEqual(bodies[0][2]['resourceSpans'][0]['scopeSpans'][0]['spans'][0]['traceId'],key)
   with patch('observability.settings',return_value=cfg):self.store.export(key)
   self.assertEqual(len(bodies),1)  # Never resend successful spans (avoids duplicate analytics).
   self.store.update(key,lambda r:r.update(delivered_spans=[]))
   with patch('observability.settings',return_value=cfg),patch('observability.urlopen',side_effect=TimeoutError):self.store.export(key)
   self.assertEqual(self.store.get(key)['export'],'failed')
  finally:server.shutdown();server.server_close()
 def test_codex_json_usage_and_final_answer(self):
  stream=[{'type':'item.completed','item':{'type':'agent_message','text':'answer'}},{'type':'turn.completed','usage':{'input_tokens':100,'cached_input_tokens':40,'output_tokens':12}}]
  with self.store.trace('json') as key:
   with patch('subprocess.run') as run:
    run.return_value.returncode=0;run.return_value.stdout='\n'.join(json.dumps(x) for x in stream);run.return_value.stderr=''
    result=model_process(['codex','exec','-'],input='question')
    self.assertEqual(result.stdout,'answer');self.assertIn('--json',run.call_args.args[0])
  generation=next(s for s in self.store.get(key)['spans'] if s['kind']=='generation')
  self.assertEqual(generation['usage'],{'input':60,'input_cache_read':40,'output':12})
 def test_redaction_and_tool_payload(self):
  @traced('query')
  def query(name,args):return {'ok':False,'error':{'message':'denied'},'password':'hide-this'}
  with self.store.trace('tool') as key:query('search',{'query':'Python','access_token':'hide-token'})
  tool=next(s for s in self.store.get(key)['spans'] if s['name']=='query')
  self.assertEqual(tool['input']['args']['query'],'Python');self.assertEqual(tool['status'],'error')
  self.assertNotIn('hide-',json.dumps(tool));self.assertEqual(tool['output']['password'],'[REDACTED]')
  self.assertNotIn('abc12345678',capture('api_key="abc12345678"'))
 def test_running_span_exported_before_completion(self):
  cfg={'host':'http://localhost:3000','public':'pk','secret':'sk','project':'p'};snapshots=[]
  def export(key):snapshots.append(self.store.get(key))
  with patch('observability.settings',return_value=cfg),patch.object(self.store,'export',side_effect=export):
   with self.store.trace('live') as key:
    with span('model','generation',input='hello'):
     self.store.flush()
     self.assertTrue(any(s['status']=='running' and s.get('input')=='hello' for r in snapshots for s in r['spans']))
   self.store.flush()
  self.assertTrue(any(all(s['status']!='running' for s in r['spans']) for r in snapshots))
 def test_json_failure_does_not_become_answer(self):
  with self.assertRaises(RuntimeError):
   with self.store.trace('bad json') as key:
    with patch('subprocess.run') as run:
     run.return_value.returncode=0;run.return_value.stdout='{"type":"turn.failed","error":{"message":"network down"}}';run.return_value.stderr=''
     model_process(['codex','exec','-'],input='hello')
  generation=next(s for s in self.store.get(key)['spans'] if s['kind']=='generation')
  self.assertEqual(generation['status'],'error');self.assertIn('network down',generation['error'])
 def test_incremental_wire_delivery_has_unique_completed_spans(self):
  import io
  bodies=[]
  def receive(req,**kw):
   bodies.extend(json.loads(req.data)['resourceSpans'][0]['scopeSpans'][0]['spans'])
   return io.BytesIO(b'{}')
  cfg={'host':'http://localhost:3000','public':'pk','secret':'sk','project':'p'}
  with patch('observability.settings',return_value=cfg),patch('observability.urlopen',side_effect=receive):
   with self.store.trace('incremental') as key:
    with span('model','generation',input='question') as observation:
     self.store.flush()
     self.assertTrue(any(s['name']=='开始：model' for s in bodies))
     self.assertFalse(any(s['name']=='model' for s in bodies))
     observation['output']='answer'
   self.store.flush()
  self.assertEqual(len(bodies),len({s['spanId'] for s in bodies}))
  self.assertTrue(any(s['name']=='model' for s in bodies))
  self.assertEqual(self.store.get(key)['export'],'sent')
 def test_invalid_and_duplicate_ids(self):
  with self.assertRaises(ValueError):self.store.create('bad','../x')
  key=self.store.create('one')
  with self.assertRaises(ValueError):self.store.create('two',key)
if __name__=='__main__':unittest.main()
