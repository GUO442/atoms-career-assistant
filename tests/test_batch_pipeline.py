import json,tempfile,time,threading,unittest
from pathlib import Path
from unittest.mock import patch
from agent_runtime import CareerHarness
from batch_pipeline import BatchPipeline,HarnessWithBatches
from discovery import Discovery
from career_tracking import Tracker
from chat_intents import validate,IntentError

class Library:
 def __init__(self):
  self.lock=threading.RLock();self.data={'versions':[{'id':'original','kind':'original','sha256':'original-hash','text':'真实Agent自动化经历'}],'applications':[]}
 def load(self):return self.data
 def get(self,key):return next(v for v in self.data['versions'] if v['id']==key)

class Tools:
 def __init__(self,lib,tracker,total=1):self.lib=lib;self.tracker=tracker;self.total=total;self.pages=[];self.sent=[];self.greeted=[];self.incoming={};self.failpage=None
 def recommend(self,page):
  self.pages.append(page)
  if page==self.failpage:raise ValueError('需要登录')
  return {'items':[{'job_id':f'job{i}','title':'AI Agent测试开发','company':'真实公司','salary':'30-40K','city':'深圳','security_id':'opaque','lid':'opaque','url':f'https://www.zhipin.com/job_detail/job{i}.html','source':'boss_web_api'} for i in range((page-1)*15,min(page*15,self.total))],'has_more':page*15<self.total}
 def detail(self,j):return {'job_id':j['job_id'],'description':'Agent自动化完整JD','recruiter':'真实HR'}
 def greet(self,j,original):
  self.greeted.append(j['job_id']);self.tracker.register({**j,'recruiter_id':'123','recruiter':'真实HR'})
  self.tracker.event(j['job_id'],'greet','sent','sent:'+j['job_id'],{'source':'browser_chat'})
  return {'verified_sent':True,'receipt':{'message_id':'real'}}
 def tailor(self,j):
  v={'id':'v-'+j['job_id'],'kind':'tailored','job':j,'sha256':'hash','reviewed':False}
  self.lib.data['versions'].append(v);return v
 def replies(self,key,jobs):return self.incoming
 def deliver(self,j,version):self.sent.append((j['job_id'],version));return {'status':'waiting_hr','version_id':version,'message_id':'receipt'}

class BatchTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);(self.root/'data').mkdir();(self.root/'data/workspace.json').write_text(json.dumps({'preferences':'Agent开发，深圳30K以上'}))
  self.lib=Library();self.lib.root=self.root/'data/resumes';self.tracker=Tracker(self.root/'data/tracking');self.d=Discovery(self.root/'data',None,None);self.h=CareerHarness(self.root/'data/harness',None)
  self.tools=Tools(self.lib,self.tracker)
  self.model=lambda *a:'{"decision":"recommend","analysis":"真实匹配证据"}'
  self.p=BatchPipeline(self.h,self.root,self.d,self.tracker,self.lib,self.model,self.tools)
  self.p.start_scheduler=lambda:None
 def tearDown(self):self.tmp.cleanup()
 def create(self,n=1):return self.p.create(n,True,True)
 def test_wait_then_latest_reviewed_delivery(self):
  key=self.create();self.p.tick(key);j=self.p.get(key)['jobs'][0]
  self.assertEqual(j['node'],'wait_reply');self.assertEqual(self.tools.sent,[])
  self.tools.incoming={'job0':{'at':time.time()+.1,'message_id':'hr'}}
  # Older reviewed version cannot replace the newest unreviewed version.
  self.lib.data['versions'][-1].update(reviewed=True,reviewed_sha256='hash')
  self.lib.data['versions'].append({'id':'newest','kind':'tailored','job':{'job_id':'job0'},'sha256':'new','reviewed':False})
  self.p.tick(key);self.assertEqual(self.p.get(key)['jobs'][0]['node'],'review');self.assertFalse(self.tools.sent)
  self.lib.data['versions'][-1].update(reviewed=True,reviewed_sha256='new')
  self.p.tick(key);self.assertEqual(self.tools.sent,[('job0','newest')]);self.assertEqual(self.p.get(key)['status'],'completed')
  self.p.tick(key);self.assertEqual(len(self.tools.sent),1)
 def test_100_pagination_and_bounded_model_concurrency(self):
  self.tools.total=100;active=0;peak=0;lock=threading.Lock()
  def assessment(*args):
   nonlocal active,peak
   with lock:active+=1;peak=max(peak,active)
   time.sleep(.003)
   with lock:active-=1
   return {'decision':'reject','analysis':'证据不匹配'}
  key=self.create(100)
  with patch('matching_policy.assess',side_effect=assessment):self.p.tick(key)
  r=self.p.get(key)
  self.assertEqual(len(r['jobs']),100);self.assertEqual(self.tools.pages,list(range(1,8)));self.assertLessEqual(peak,3);self.assertGreater(peak,1)
  self.assertEqual(r['status'],'completed');self.assertFalse(self.tools.greeted);self.assertEqual(len(self.d.history()['jobs']),100)
 def test_read_failure_resume_does_not_lose_saved_page(self):
  self.tools.total=30;self.tools.failpage=2;key=self.create(30);self.p.tick(key)
  self.assertEqual(len(self.p.get(key)['jobs']),15);self.assertEqual(self.p.get(key)['status'],'waiting_connection')
  self.tools.failpage=None;self.p.control(key,'resume');self.p.tick(key)
  self.assertEqual(len(self.p.get(key)['jobs']),30);self.assertEqual(self.tools.pages,[1,2,2])
 def test_cancel_stops_future_effects(self):
  key=self.create();self.p.control(key,'cancel');self.p.tick(key);self.assertFalse(self.tools.pages);self.assertFalse(self.tools.greeted)
 def test_recovery_unknown_send_not_replayed(self):
  key=self.create();self.p.tick(key);r=self.p.get(key);r['jobs'][0].update(node='deliver',inflight='deliver');r['status']='running';self.p.save(r)
  recovered=BatchPipeline(self.h,self.root,self.d,self.tracker,self.lib,self.model,self.tools)
  self.assertEqual(recovered.get(key)['jobs'][0]['node'],'unknown');recovered.tick(key);self.assertFalse(self.tools.sent)
 def test_decline_never_delivers(self):
  key=self.create();self.p.tick(key)
  self.tools.incoming={'job0':{'at':time.time()+.1,'declined':True}}
  self.p.tick(key);self.assertEqual(self.p.get(key)['jobs'][0]['node'],'reject');self.assertFalse(self.tools.sent)
 def test_no_reply_no_delivery_even_reviewed(self):
  key=self.create();self.p.tick(key);self.lib.data['versions'][-1].update(reviewed=True,reviewed_sha256='hash');self.p.tick(key);self.assertFalse(self.tools.sent);self.assertEqual(len(self.tools.greeted),1)
 def test_authorization_and_duplicate_batch(self):
  with self.assertRaises(ValueError):self.p.create(100,False,True)
  with self.assertRaises(ValueError):self.p.create(100,True,False)
  self.create()
  with self.assertRaises(ValueError):self.create()
 def test_one_detail_failure_continues_other_jobs(self):
  self.tools.total=3;original=self.tools.detail
  def detail(j):
   if j['job_id']=='job0':raise ValueError('单岗业务失败')
   return original(j)
  self.tools.detail=detail
  key=self.create(3);self.p.tick(key);rows=self.p.get(key)['jobs']
  self.assertEqual(rows[0]['node'],'blocked')
  self.assertEqual(rows[0]['retry_node'],'read_jd')
  self.assertTrue(all(j.get('jd') for j in rows[1:]))
  self.assertEqual(len(self.tools.greeted),2)
 def test_independent_followup_does_not_send_or_advance(self):
  key=self.create();self.p.tick(key);self.p.control(key,'pause')
  before=len(self.tools.greeted)
  self.p.run_agent(key,'followup','job0',False)
  for _ in range(100):
   if key not in self.p.active:break
   time.sleep(.01)
  self.assertEqual(self.p.get(key)['status'],'paused')
  self.assertEqual(len(self.tools.greeted),before);self.assertFalse(self.tools.sent)
  self.assertTrue(any(t['agent']=='followup' for t in self.p.agents.status(key)['tasks']))
 def test_interview_agent_persists_invitation_without_confirmation(self):
  key=self.create();self.p.tick(key);j=self.p.get(key)['jobs'][0]
  self.p.record_interview(key,j,{'text':'邀请您明天参加面试','at':time.time(),'message_id':'interview1'})
  self.assertEqual(self.tracker.listing()['jobs'][0]['interview'],'invited')
  self.assertFalse(self.p.get(key)['jobs'][0]['interview']['confirmed'])
 def test_start_tailor_independent_of_greeting(self):
  key=self.create();r=self.p.get(key)
  r.update(status='paused',collection_done=True,jobs=[{'job_id':'job0','title':'AI测试','company':'公司','jd':'真实JD','decision':'recommend','node':'greet'}]);self.p.save(r)
  result=self.p.start_agent(key,'tailor',False)
  self.assertEqual(result['status'],'running')
  for _ in range(100):
   if not self.p.agent_workers:break
   time.sleep(.01)
  self.assertEqual(self.tools.greeted,[])
  self.assertEqual(self.p.get(key)['jobs'][0]['version_id'],'v-job0')
  self.assertEqual(self.p.get(key)['status'],'paused')
 def test_start_sending_requires_authorization(self):
  key=self.create()
  with self.assertRaises(ValueError):self.p.start_agent(key,'greet',False)
  with self.assertRaises(ValueError):self.p.start_agent(key,'deliver',False)
 def test_old_task_start_is_rejected_without_mutation(self):
  legacy={'id':'legacy','mode':'boss','status':'waiting_browser','context':{},'events':[],'cursor':0}
  self.h.put(legacy)
  with self.assertRaisesRegex(ValueError,'旧版任务'):self.p.start_agent('legacy','match',False)
  self.assertEqual(self.h.get('legacy'),legacy)
  self.assertFalse(self.p.agent_workers)
 def test_read_only_batch_never_greets_or_tailors(self):
  key=self.p.create(1,False,True,screening_only=True);self.p.tick(key)
  r=self.p.get(key)
  self.assertEqual(r['status'],'completed');self.assertEqual(r['jobs'][0]['node'],'screened')
  self.assertFalse(self.tools.greeted);self.assertFalse(self.tools.sent)
  self.assertEqual(len(self.lib.load()['versions']),1)
 def test_screen_request_does_not_create_another_squad(self):
  key=self.create();before=len(self.p.records())
  request=self.p.screen_existing(key,1)
  for _ in range(300):
   row=self.p.work_requests(key)[0]
   if row['status'] not in ('queued','running'):break
   time.sleep(.01)
  self.assertEqual(len(self.p.records()),before)
  self.assertEqual(request['squad_id'],key)
  self.assertFalse(self.tools.greeted);self.assertFalse(self.tools.sent)
 def test_scheduled_agent_cycle_runs_every_ten_minutes(self):
  import batch_pipeline as bp
  self.assertEqual(bp.TICK_SECONDS,600)
  key=self.create();self.assertEqual(self.p.get(key)['poll_seconds'],600)
  self.p.tick(key);remaining=self.p.get(key)['next_check']-time.time()
  self.assertGreater(remaining,590);self.assertLessEqual(remaining,600)
  # 调度线程记录状态，异常不退出
  self.p.write_state(error='boom')
  state=json.loads((self.root/'data/scheduler-state.json').read_text())
  self.assertEqual(state['interval_seconds'],600);self.assertEqual(state['last_error'],'boom');self.assertTrue(state['scheduler_alive'])
 def test_schema(self):
  validate({'tool':'pipeline','arguments':{'action':'create','target_count':100,'authorized':True,'consent':True}})
  validate({'tool':'pipeline','arguments':{'action':'create','target_count':101,'authorized':True,'consent':True}})  # 无上限：101 现在合法
  for args in ({'action':'create','target_count':0,'authorized':True,'consent':True},{'action':'create','target_count':1,'authorized':False,'consent':True},{'action':'cancel','id':'madeup'}):
   with self.assertRaises(IntentError):validate({'tool':'pipeline','arguments':args})
 def test_batch_shown_in_harness_without_transport_ids(self):
  key=self.create();self.p.tick(key);facade=HarnessWithBatches(self.h,self.p);r=facade.listing()[0];self.assertNotIn('security_id',r['jobs'][0]);self.assertIn('progress',r)
  facade.cancel(key);self.assertEqual(self.p.get(key)['status'],'cancelled')
