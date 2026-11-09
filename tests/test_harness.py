import sys, tempfile, time, unittest, threading
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from harness import Harness
class HarnessTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.calls=[]
  def model(*a):self.calls.append(a);return '测试模型结果'
  self.h=Harness(self.tmp.name,model)
  self.ctx={'resume':'真实经历','preferences':'上海，测试','jd':'测试岗位要求','joburl':'https://www.zhipin.com/job_detail/test.html','jobtitle':'示例岗位'}
 def tearDown(self):self.tmp.cleanup()
 def settle(self,key):
  for _ in range(300):
   if key not in self.h.active:return self.h.get(key)
   time.sleep(.01)
  self.fail('worker did not finish')
 def test_browser_disconnected_cannot_complete(self):
  key=self.h.create('boss',self.ctx,True);self.h.start(key);r=self.settle(key)
  self.assertEqual(r['status'],'waiting_browser');self.assertEqual(r['cursor'],0);self.assertFalse(self.calls)
  with self.assertRaises(ValueError):self.h.start(key)
 def test_complete_idempotent_with_provenance(self):
  key=self.h.create('jd',self.ctx,True);self.h.start(key);r=self.settle(key)
  self.assertEqual(r['status'],'completed');self.assertEqual(len(self.calls),2)
  self.assertEqual(r['results']['jd.validate']['source'],'user_import')
  self.assertTrue((Path(self.tmp.name)/r['artifact']).exists());self.h.start(key);self.assertEqual(len(self.calls),2)
  restored=Harness(self.tmp.name,lambda *a: 'unused');self.assertEqual(restored.get(key)['status'],'completed')
 def test_consent_resume_at_checkpoint(self):
  key=self.h.create('jd',self.ctx);self.h.start(key);r=self.settle(key)
  self.assertEqual(r['status'],'waiting_input');self.assertEqual(r['cursor'],2);self.assertFalse(self.calls)
  self.h.start(key,True);self.assertEqual(self.settle(key)['status'],'completed')
 def test_update_invalidates_results(self):
  key=self.h.create('jd',{**self.ctx,'jd':''},True);self.h.start(key);self.settle(key)
  self.h.update(key,self.ctx);r=self.h.get(key);self.assertEqual(r['cursor'],0);self.assertEqual(r['results'],{})
 def test_restart_marks_running_interrupted(self):
  key=self.h.create('jd',self.ctx);r=self.h.get(key);r['status']='running';self.h.put(r)
  h=Harness(self.tmp.name,lambda *a:'unused');self.assertEqual(h.get(key)['status'],'interrupted')
 def test_cancel_discards_model_result(self):
  entered=threading.Event();release=threading.Event()
  def model(*a):entered.set();release.wait(2);return 'must discard'
  self.h.model=model;key=self.h.create('jd',self.ctx,True);self.h.start(key);self.assertTrue(entered.wait(2));self.h.cancel(key);release.set();r=self.settle(key)
  self.assertEqual(r['status'],'cancelled');self.assertNotIn('resume.match',r['results']);self.assertIsNone(r['artifact'])
 def test_invalid_source_never_calls_model(self):
  key=self.h.create('jd',{**self.ctx,'joburl':'https://evil.example/a'},True);self.h.start(key)
  self.assertEqual(self.settle(key)['status'],'waiting_input');self.assertFalse(self.calls)
if __name__=='__main__':unittest.main()
