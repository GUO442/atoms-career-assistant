import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch
from agent_runtime import CareerHarness

class RuntimeTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.calls=[];self.queries=[]
  self.cfg=patch('observability.settings',return_value={'host':'','public':'','secret':'','project':''});self.cfg.start()
  self.ctx={'resume':'真实经历','preferences':'深圳 AI测试','jd':'真实测试岗位JD','joburl':'https://www.zhipin.com/job_detail/abc.html','goal':'分析并定制简历','query':'AI测试','city':'深圳'}
  self.h=CareerHarness(self.tmp.name,self.model,self.query)
 def tearDown(self):self.cfg.stop();self.tmp.cleanup()
 def model(self,instruction,context,analysis=''):
  self.calls.append((instruction,context))
  if 'available_tools' in context:
   tool=context['available_tools'][0]['name'];args={'query':context['profile']['query'],'city':context['profile']['city']} if tool=='boss.search_jobs' else {}
   return json.dumps({'tool':tool,'arguments':args,'summary':'根据任务目标执行'})
  return '基于真实经历的模型结果'
 def query(self,name,args):
  self.queries.append((name,args))
  if name=='status':return {'ok':True,'data':{'logged_in':True,'live':False}}
  if name=='search':return {'ok':True,'data':{'items':[{'job_id':'abc','title':'测试','company':'真实公司','security_id':'sec'}]}}
  if name=='detail':return {'ok':True,'data':{'job_id':'abc','description':'真实JD'}}
 def settle(self,key):
  for _ in range(500):
   if key not in self.h.active:return self.h.get(key)
   time.sleep(.01)
  self.fail('worker did not settle')
 def run_task(self,mode='jd',ctx=None,consent=True):
  key=self.h.create(mode,ctx or self.ctx,consent);self.h.start(key);return key,self.settle(key)
 def test_jd_goal_runs_checkpointed_tools_and_finishes(self):
  key,r=self.run_task();self.assertEqual(r['status'],'completed');self.assertEqual(r['cursor'],5)
  self.assertTrue((Path(self.tmp.name)/r['artifact']).exists());self.assertEqual(len(r['decisions']),5)
  count=len(self.calls);self.h.start(key);self.assertEqual(len(self.calls),count)
  self.assertEqual(r['results']['jd.validate']['source'],'user_import')
 def test_boss_pauses_for_selection_then_uses_real_jd(self):
  key,r=self.run_task('boss');self.assertEqual(r['status'],'waiting_selection');self.assertFalse(any(n=='detail' for n,a in self.queries))
  with self.assertRaises(ValueError):self.h.select(key,'invented')
  self.h.select(key,'abc');self.h.start(key);r=self.settle(key)
  self.assertEqual(r['status'],'completed');self.assertEqual(r['context']['jd'],'真实JD')
  self.assertEqual(sum(n=='search' for n,a in self.queries),1)
 def test_consent_prevents_planner_and_model_calls(self):
  key,r=self.run_task(consent=False);self.assertEqual(r['status'],'waiting_input');self.assertFalse(self.calls)
  self.h.start(key,True);self.assertEqual(self.settle(key)['status'],'completed')
 def test_invalid_model_tool_is_never_executed(self):
  self.h.model=lambda *a:json.dumps({'tool':'shell.execute','arguments':{},'summary':'unsafe'})
  _,r=self.run_task();self.assertEqual(r['status'],'waiting_input');self.assertFalse(self.queries);self.assertIsNone(r['artifact'])
 def test_schema_rejects_extra_arguments(self):
  self.h.model=lambda *a:json.dumps({'tool':'jd.validate','arguments':{'command':'evil'},'summary':'bad args'})
  _,r=self.run_task();self.assertEqual(r['status'],'waiting_input');self.assertNotIn('jd.validate',r['results'])
 def test_connection_failure_stops_without_retry(self):
  self.h.query=lambda *a:{'ok':False,'error':{'code':'AUTH_REQUIRED','message':'请登录'}}
  _,r=self.run_task('boss');self.assertEqual(r['status'],'waiting_connection');self.assertEqual(r['attempts']['boss.verify_session'],1);self.assertFalse(r['jobs'])
 def test_unmatched_jd_stops(self):
  original=self.h.query
  self.h.query=lambda n,a:{'ok':True,'data':{'job_id':'wrong','description':'JD'}} if n=='detail' else original(n,a)
  key,_=self.run_task('boss');self.h.select(key,'abc');self.h.start(key);r=self.settle(key)
  self.assertEqual(r['status'],'waiting_connection');self.assertNotIn('resume.match',r['results'])
 def test_update_invalidates_results(self):
  key,_=self.run_task(consent=False);self.h.update(key,{'preferences':'上海'});r=self.h.get(key)
  self.assertEqual(r['results'],{});self.assertFalse(r['steps']);self.assertEqual(r['context']['preferences'],'上海')
 def test_cancel_discards_pending_model_output(self):
  entered=threading.Event();release=threading.Event();original=self.h.model
  def slow(*a):entered.set();release.wait(2);return original(*a)
  self.h.model=slow;key=self.h.create('jd',self.ctx,True);self.h.start(key);self.assertTrue(entered.wait(2))
  self.h.cancel(key);release.set();r=self.settle(key);self.assertEqual(r['status'],'cancelled');self.assertEqual(r['cursor'],1);self.assertIsNone(r['artifact'])
 def test_restart_and_resume_reuses_successful_checks(self):
  key,r=self.run_task(consent=False);r['status']='running';r['inflight']={'tool':'jd.validate'};self.h.put(r)
  self.h=CareerHarness(self.tmp.name,self.model,self.query);self.assertEqual(self.h.get(key)['status'],'interrupted')
  self.h.start(key,True);r=self.settle(key);self.assertEqual(r['status'],'completed')
  self.assertEqual(r['plan'].count('profile.validate'),1)
 def test_analysis_goal_does_not_tailor(self):
  _,r=self.run_task(ctx={**self.ctx,'deliverable':'analysis'});self.assertEqual(r['status'],'completed');self.assertNotIn('resume.tailor',r['results'])
 def test_invalid_source_never_matches(self):
  _,r=self.run_task(ctx={**self.ctx,'joburl':'https://evil.example/job'});self.assertEqual(r['status'],'waiting_input');self.assertNotIn('resume.match',r['results'])
 def test_budget_enforced(self):
  key=self.h.create('jd',self.ctx,True);r=self.h.get(key);r['max_steps']=1;self.h.put(r);self.h.start(key)
  self.assertEqual(self.settle(key)['status'],'budget_exceeded')
 def test_model_can_request_clarification(self):
  self.h.model=lambda *a:json.dumps({'tool':'human.request_input','arguments':{'message':'请说明目标岗位'},'summary':'目标不明确'})
  _,r=self.run_task();self.assertEqual(r['status'],'waiting_input');self.assertEqual(r['pending'],'请说明目标岗位')
