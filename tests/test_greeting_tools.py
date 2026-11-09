import io,json,tempfile,unittest,zipfile
from pathlib import Path
from greeting_tools import Greetings


def word(text):
 out=io.BytesIO()
 with zipfile.ZipFile(out,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
 return out.getvalue()

class Adapter:
 verified=True
 supported_kinds={'reply_text'}
 def __init__(self,success=True):self.calls=[];self.success=success
 def __call__(self,a):
  self.calls.append(a)
  return {'verified_sent':self.success,'receipt':{'message_id':'real-test-id'}}

class GreetingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
  self.adapter=Adapter();self.g=Greetings(self.tmp.name,self.adapter)
  self.original=self.g.library.add('original.docx',word('负责银行Agent多轮对话测试，搭建Python自动化框架。'))
  self.job={'job_id':'test','platform':'boss','company':'测试公司','title':'AI测试','jd':'负责Agent评测体系建设及Python开发','screening':'recommend','greet':'not_sent','recruiter_id':'hr1'}
  self.g.listing=lambda:[dict(self.job)]
 def plan(self):
  return self.g.plan([{'job_id':'test','text':'看到贵司建设Agent评测体系，我负责过银行Agent多轮对话测试和Python自动化框架，希望交流岗位契合点。','evidence':[{'source':'jd','quote':'Agent评测体系建设'},{'source':'resume','quote':'负责银行Agent多轮对话测试'}]}],self.original['id'])['plan']
 def test_first_contact_without_recruiter_field_reaches_adapter(self):
  self.job.pop('recruiter_id');self.adapter.supports_first_contact=True
  plan=self.plan()
  # Receipt succeeds but tracker update needs registration; reaching adapter is the regression guard.
  self.g.send(plan['id'],True,1,False)
  self.assertEqual(len(self.adapter.calls),1)
  self.assertIsNone(self.adapter.calls[0]['recruiter_id'])
 def test_explicit_pre_send_block_is_not_unknown(self):
  class Blocked(Adapter):
   def __call__(self,a):return {'verified_sent':False,'status':'blocked','reason':'未启动浏览器'}
  self.g.adapter=Blocked()
  result=self.g.send(self.plan()['id'],True,1,True)
  self.assertEqual(result['results'][0]['status'],'blocked')
 def test_no_send_during_plan_and_context(self):
  self.plan();self.assertEqual(self.adapter.calls,[])
  self.assertFalse(self.g.context(['test'])['sent'])
 def test_fabricated_evidence_rejected(self):
  with self.assertRaises(ValueError):self.g.plan([{'job_id':'test','text':'这个消息足够长，但是它引用了不存在的工作经验，不应当被计划工具保存。','evidence':[{'source':'jd','quote':'Agent'},{'source':'resume','quote':'SWE-bench专家'}]}],self.original['id'])
 def test_first_contact_blocks_without_default_greeting(self):
  self.job.pop('recruiter_id');p=self.plan();r=self.g.send(p['id'],True,1)
  self.assertEqual(r['results'][0]['status'],'blocked_first_contact');self.assertEqual(self.adapter.calls,[])
  self.assertEqual(self.g.status(p['id'])['plan']['last_execution']['results'],r['results'])
 def test_existing_default_skip_and_explicit_scope(self):
  p=self.plan();self.assertEqual(self.g.send(p['id'],True,1)['results'][0]['status'],'skipped_existing')
  with self.assertRaises(ValueError):self.g.send(p['id'],False,1,True)
  with self.assertRaises(ValueError):self.g.send(p['id'],True,2,True)
  self.assertEqual(self.adapter.calls,[])
 def test_uncertain_send_is_not_replayed(self):
  self.adapter.success=False;p=self.plan()
  self.assertEqual(self.g.send(p['id'],True,1,True)['results'][0]['status'],'unknown')
  self.assertEqual(self.g.send(p['id'],True,1,True)['results'][0]['status'],'skipped_recorded')
  self.assertEqual(len(self.adapter.calls),1)
 def test_changed_jd_and_recruiter_block(self):
  p=self.plan();self.job['jd']='新JD'
  self.assertEqual(self.g.send(p['id'],True,1,True)['results'][0]['status'],'blocked_changed_job')
  self.job['jd']='负责Agent评测体系建设及Python开发';self.job['recruiter_id']='another'
  self.assertEqual(self.g.send(p['id'],True,1,True)['results'][0]['status'],'blocked_changed_recruiter')
 def test_changed_resume_file_blocks(self):
  p=self.plan();(self.g.library.root/(self.original['id']+'.docx')).write_bytes(b'changed')
  with self.assertRaises(ValueError):self.g.send(p['id'],True,1,True)
 def test_verified_send_updates_tracker_and_deduplicates_across_plans(self):
  from career_tracking import Tracker
  t=Tracker(Path(self.tmp.name)/'data/tracking');t.register(self.job)
  p=self.plan();self.assertEqual(self.g.send(p['id'],True,1,True)['results'][0]['status'],'sent')
  self.assertEqual(t.listing()['jobs'][0]['greet'],'sent')
  p2=self.plan();self.assertEqual(self.g.send(p2['id'],True,1,True)['results'][0]['status'],'skipped_recorded')
  self.assertEqual(len(self.adapter.calls),1)

if __name__=='__main__':unittest.main()
