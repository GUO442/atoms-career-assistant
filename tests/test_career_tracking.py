import io,json,tempfile,time,unittest
from unittest.mock import patch
from pathlib import Path
from career_tracking import Tracker
from resume_library import Library
from boss_message_monitor import MessageMonitor
class TrackingTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup);self.t=Tracker(Path(self.tmp.name)/'tracking');self.lib=Library(Path(self.tmp.name)/'resumes')
  self.t.register({'job_id':'real-job','title':'AI测试','url':'https://www.zhipin.com/job_detail/real-job.html','recruiter_id':'hr1'})
 def enable(self):self.t.configure({'enabled':True,'reply_mode':'greetings','allowed_jobs':['real-job']},self.lib)
 def test_dimensions_and_idempotency(self):
  now=time.time();self.t.event('real-job','greet','sent','g1',{'source':'browser_chat'},now)
  self.t.incoming('real-job','hr1','m1','你好啊，可以聊一聊~',now+1)
  j=self.t.listing()['jobs'][0];self.assertEqual((j['greet'],j['reply'],j['resume']),('sent','replied','not_sent'))
  self.assertFalse(self.t.incoming('real-job','hr1','m1','你好啊，可以聊一聊~',now+1));self.assertEqual(len(self.t.listing()['actions']),1)
 def test_wrong_recruiter_and_untracked_job_are_ignored(self):
  self.assertFalse(self.t.incoming('real-job','other','m1','你好',time.time()));self.assertFalse(self.t.incoming('invented','hr1','m1','你好',time.time()));self.assertFalse(self.t.listing()['actions'])
 def test_old_messages_never_trigger_new_automation(self):
  self.enable();self.t.incoming('real-job','hr1','old','你好',time.time()-3600)
  self.assertEqual(self.t.listing()['actions'][0]['status'],'needs_attention')
 def test_requests_create_drafts_not_unreviewed_attachment_sends(self):
  self.enable();self.t.incoming('real-job','hr1','m1','方便发一份简历过来吗？',time.time())
  a=self.t.listing()['actions'][0];self.assertEqual((a['kind'],a['status']),('tailor_resume','queued'));self.assertEqual(self.t.listing()['jobs'][0]['resume'],'waiting')
 def test_only_greetings_are_automatic(self):
  self.enable();self.t.incoming('real-job','hr1','m1','你好啊，可以聊一聊~',time.time());self.assertEqual(self.t.listing()['actions'][0]['kind'],'reply_text')
  self.t.incoming('real-job','hr1','m2','你的期望薪资和到岗时间？',time.time());a=self.t.listing()['actions'][0];self.assertEqual((a['kind'],a['status']),('notify','needs_attention'))
 def test_interview_invitation_is_not_completed_interview(self):
  self.t.incoming('real-job','hr1','m1','邀请你参加面试，请问方便吗？',time.time())
  self.assertEqual(self.t.listing()['jobs'][0]['interview'],'invited')
 def test_late_passive_evidence_cannot_undo_delivery(self):
  self.t.event('real-job','resume','sent','sent',{'source':'browser_chat'},time.time())
  self.t.event('real-job','resume','waiting','later',{'source':'network_message'},time.time()+1)
  self.assertEqual(self.t.listing()['jobs'][0]['resume'],'sent')
 def test_unverified_and_uncertain_sends_never_replay(self):
  self.enable();self.t.incoming('real-job','hr1','m1','你好',time.time())
  self.t.dispatch(None,self.lib);self.assertEqual(self.t.listing()['actions'][0]['status'],'blocked_interface')
  calls=[]
  class Adapter:
   verified=True;supported_kinds={'reply_text'}
   def __call__(self,a):calls.append(a);return {'verified_sent':False}
  self.t.incoming('real-job','hr1','m2','您好',time.time());self.t.dispatch(Adapter(),self.lib);self.t.dispatch(Adapter(),self.lib)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0]['recruiter_id'],'hr1')
 def test_crash_recovery_marks_inflight_unknown(self):
  self.enable();self.t.incoming('real-job','hr1','m1','你好',time.time())
  with self.t.connect() as c:c.execute('UPDATE actions SET status="running"')
  recovered=Tracker(self.t.root);self.assertEqual(recovered.listing()['actions'][0]['status'],'unknown')
 def test_approval_requires_exact_reviewed_per_job_version(self):
  from docx import Document
  d=Document();d.add_paragraph('真实简历');b=io.BytesIO();d.save(b)
  v=self.lib.add('岗位.docx',b.getvalue(),{'url':'https://www.zhipin.com/job_detail/real-job.html'},'tailored');self.t.attach_draft('real-job',v['id'])
  with self.assertRaises(ValueError):self.t.approve_draft('real-job',v['id'],self.lib)
  self.lib.action('review',v['id'],True);self.t.approve_draft('real-job',v['id'],self.lib)
  self.t.approve_draft('real-job',v['id'],self.lib);self.assertEqual(len(self.t.listing()['actions']),1)
 def test_changed_reviewed_document_cannot_be_approved(self):
  from docx import Document
  d=Document();d.add_paragraph('原始真实内容');buf=io.BytesIO();d.save(buf)
  v=self.lib.add('岗位.docx',buf.getvalue(),{'url':'https://www.zhipin.com/job_detail/real-job.html'},'tailored');self.t.attach_draft('real-job',v['id']);self.lib.action('review',v['id'],True)
  (self.lib.root/(v['id']+'.docx')).write_bytes(b'changed after review')
  with self.assertRaises(ValueError):self.t.approve_draft('real-job',v['id'],self.lib)
  self.assertFalse(self.t.listing()['actions'])
 def test_unverified_attachment_sender_does_not_mark_job_delivered(self):
  self.enable()
  from docx import Document
  d=Document();d.add_paragraph('真实内容');buf=io.BytesIO();d.save(buf)
  v=self.lib.add('岗位.docx',buf.getvalue(),{'url':'https://www.zhipin.com/job_detail/real-job.html'},'tailored');self.t.attach_draft('real-job',v['id']);self.lib.action('review',v['id'],True);self.t.approve_draft('real-job',v['id'],self.lib)
  class TextOnly:
   verified=True;supported_kinds={'reply_text'}
   def __call__(self,a):raise AssertionError('must not send attachment')
  self.t.dispatch(TextOnly(),self.lib)
  self.assertEqual(self.t.listing()['actions'][0]['status'],'blocked_interface');self.assertNotEqual(self.t.listing()['jobs'][0]['resume'],'sent')
 def test_monitor_maps_real_direction_and_does_not_treat_system_card_as_greeting(self):
  m=MessageMonitor(self.t);m.self_uid='self'
  contact={'encryptJobId':'real-job','uid':'hr1','name':'招聘者','lastMessageInfo':{'msgId':1},'lastTS':123}
  history=[{'from':{'uid':'0'},'mid':1,'time':int(time.time()*1000),'body':{'type':1}},{'from':{'uid':'hr1'},'mid':2,'time':int(time.time()*1000),'body':{'text':'你好'}}]
  with patch.object(m,'snapshot',return_value=[contact]),patch.object(m,'history',return_value=(history,False)):
   m.sync();m.sync()
  j=self.t.listing()['jobs'][0];self.assertEqual(j['greet'],'not_sent');self.assertEqual(j['reply'],'replied');self.assertEqual(len(self.t.listing()['actions']),1)
if __name__=='__main__':unittest.main()
