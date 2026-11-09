import io,tempfile,unittest,json,time
from pathlib import Path
from unittest.mock import patch
from docx import Document
from resume_library import Library
from career_tracking import Tracker
from resume_delivery_workflow import DeliveryService,deliver,acknowledge_receipt
from assistant_skills import SkillRuntime
from chat_intents import IntentRouter,validate,IntentError
JOB={'job_id':'abc','url':'https://www.zhipin.com/job_detail/abc.html','title':'测试主管','company':'示例公司','jd':'金融自动化','source':'user','collected_at':'2026-10-30'}
class DeliveryWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.library=Library(self.root/'data/resumes');self.tracker=Tracker(self.root/'data/tracking')
  d=Document();d.add_paragraph('测试');b=io.BytesIO();d.save(b);body=b.getvalue()
  original=self.library.add('base.docx',body);self.v=self.library.add_tailored('tailored.docx',body,JOB,original['id'])
  self.tracker.register(JOB|{'recruiter':'某女士','recruiter_id':'123'})
  self.service=DeliveryService(self.library,self.tracker,self.root)
 def tearDown(self):self.tmp.cleanup()
 def review(self):self.library.action('review',self.v['id'],True)
 def app(self,status='waiting_hr'):
  data=self.library.load();data['applications'].append({'id':'app','version_id':self.v['id'],'resume_name':self.v['name'],'job':JOB,'status':status,'resume_status':'waiting','message_id':'mid','created':'2026-10-30T00:00:00+00:00'});self.library.put(data)
 def test_duplicate_delivery_never_opens_browser_or_uploads(self):
  self.review();self.app('sent')
  with patch('resume_delivery_workflow.upload') as upload:
   result=deliver(self.library,self.tracker,JOB,self.v['id'],True,self.root)
   self.assertEqual(result['status'],'already_recorded');upload.assert_not_called()
  with patch('resume_delivery_workflow.deliver') as send:
   result=self.service.start([JOB],'abc','',True)
   self.assertFalse(result['sent_now']);send.assert_not_called()
 def test_latest_unreviewed_is_not_replaced_by_an_older_reviewed_version(self):
  self.review()
  self.library.add_tailored('new.docx',(self.library.root/(self.v['id']+'.docx')).read_bytes()+b' ',JOB,self.v['source_resume_id'])
  with patch('resume_delivery_workflow.deliver') as send:
   with self.assertRaises(ValueError):self.service.start([JOB],'abc','',True)
   send.assert_not_called()
 def test_unconfirmed_action_and_wrong_job_are_rejected_before_upload(self):
  self.review()
  with patch('resume_delivery_workflow.upload') as upload:
   with self.assertRaises(ValueError):deliver(self.library,self.tracker,JOB,self.v['id'],False,self.root)
   with self.assertRaises(ValueError):deliver(self.library,self.tracker,JOB|{'job_id':'other'},self.v['id'],True,self.root)
   upload.assert_not_called()
 def test_positive_receipt_updates_both_ledgers_and_is_idempotent(self):
  self.app()
  at=1793328422
  self.assertTrue(acknowledge_receipt(self.library,self.tracker,'abc','123','ack','您好，已收到您的简历，我们会尽快查阅审核。',at))
  self.assertEqual(self.library.load()['applications'][0]['status'],'sent')
  self.assertEqual(self.tracker.listing()['jobs'][0]['resume'],'sent')
  self.assertFalse(acknowledge_receipt(self.library,self.tracker,'abc','123','ack','您好，已收到您的简历。',at))
 def test_wrong_recruiter_old_message_and_negative_text_cannot_confirm_receipt(self):
  self.app()
  for uid,text,at in [('wrong','已收到您的简历。',1793328422),('123','已收到您的简历。',1),('123','尚未收到您的简历。',1793328422),('123','请发送您的简历。',1793328422)]:
   self.assertFalse(acknowledge_receipt(self.library,self.tracker,'abc',uid,'ack',text,at))
  self.assertEqual(self.library.load()['applications'][0]['status'],'waiting_hr')
 def test_explicit_skill_load_and_generation_parameters(self):
  root=Path(__file__).resolve().parents[1];runtime=SkillRuntime(root)
  expected={'tool':'resume.deliver','arguments':{'query':'abc','version_id':'','confirmed':True}}
  result,used=runtime.resolve({'tool':'skill.run','arguments':{'id':'boss-job-apply'}},{'messages':[{'role':'user','content':'把这家公司的已审阅简历投递给HR'}]},[],IntentRouter(lambda *a:json.dumps(expected)))
  self.assertEqual(result,expected);self.assertEqual(used[0]['id'],'boss-job-apply')
  with self.assertRaises(IntentError):validate({'tool':'resume.deliver','arguments':{'query':'abc','version_id':'','confirmed':False}})
