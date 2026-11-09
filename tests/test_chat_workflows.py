import json
import tempfile
import unittest
from unittest.mock import patch
from agent_runtime import CareerHarness
from chat_workflows import ChatWorkflows, recent_messages

class ChatWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory()
  self.h=CareerHarness(self.tmp.name,lambda *a:'unused')
  self.bridge=ChatWorkflows(self.h)
  self.data={'conversation_id':'a'*32,'consent':True,'resume':'真实经历','preferences':'深圳 AI测试',
             'messages':[{'role':'user','content':'启动Harness工作流，分析已录入JD'}]}
  self.start=patch.object(self.h,'start');self.started=self.start.start()
 def tearDown(self):self.start.stop();self.tmp.cleanup()
 def route(self,action,args=None,data=None):
  return self.bridge.execute(data or self.data,{'action':action,'arguments':args or {}})
 def create(self):
  r=self.route('create',{'mode':'jd','context':{'goal':'分析岗位','deliverable':'analysis'}})
  return r['tool_results'][0]['run']['id']
 def test_create_links_persisted_real_run_and_uses_profile(self):
  key=self.create();r=self.h.get(key)
  self.assertEqual(r['context']['resume'],'真实经历');self.assertTrue(r['consent'])
  self.assertEqual(r['context']['deliverable'],'analysis');self.started.assert_called_once_with(key)
  self.assertEqual(ChatWorkflows(self.h).linked('a'*32)[0]['id'],key)
 def test_cannot_override_resume_or_execute_unregistered_action(self):
  result=self.route('create',{'mode':'jd','context':{'resume':'伪造经历'}})
  self.assertIn('error',result['tool_results'][0]);self.assertEqual(self.h.listing(),[])
  self.assertIn('error',self.route('shell',{})['tool_results'][0])
 def test_other_conversation_cannot_resume_run(self):
  key=self.create();other={**self.data,'conversation_id':'b'*32}
  result=self.route('resume',{'id':key},other)
  self.assertIn('error',result['tool_results'][0]);self.assertEqual(self.started.call_count,1)
 def test_short_followup_routes_and_resumes_exact_run(self):
  key=self.create();self.data['messages'].append({'role':'user','content':'继续'})
  result=self.route('resume',{'id':key});self.assertEqual(result['tool_results'][0]['tool'],'harness.resume')
  self.started.assert_called_with(key,True)
 def test_status_reports_persisted_pause_and_candidates(self):
  key=self.create();r=self.h.get(key);r.update(status='waiting_selection',pending='请选择真实岗位',jobs=[{'job_id':'real','company':'测试公司','title':'测试岗位'}]);self.h.put(r)
  result=self.route('status');self.assertIn('等待选岗',result['answer']);self.assertIn('real',result['answer'])
 def test_select_rejects_invented_job_and_accepts_actual_candidate(self):
  key=self.create();r=self.h.get(key);r.update(status='waiting_selection',jobs=[{'job_id':'real'}]);self.h.put(r)
  self.assertIn('error',self.route('select',{'id':key,'job_id':'invented'})['tool_results'][0])
  self.route('select',{'id':key,'job_id':'real'});self.assertEqual(self.h.get(key)['selected_job'],'real')
 def test_cancel_and_update_call_real_harness(self):
  key=self.create();self.route('update',{'id':key,'context':{'city':'上海'}})
  self.assertEqual(self.h.get(key)['context']['city'],'上海')
  self.route('cancel',{'id':key});self.assertEqual(self.h.get(key)['status'],'cancelled')
 def test_recent_messages_are_bounded_preserve_roles_and_latest(self):
  messages=[{'role':'user' if i%2==0 else 'assistant','content':str(i)*100} for i in range(100)]
  result=recent_messages(messages,1000)
  self.assertLessEqual(sum(len(m['content']) for m in result),1000)
  self.assertEqual(result[-1],messages[-1]);self.assertLessEqual(len(result),24)
