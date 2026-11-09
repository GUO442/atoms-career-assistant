import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from job_status import query,validate_args,FILTER_OPTIONS
from job_management import dashboard as _dashboard
def dashboard(*args,**kwargs):return _dashboard(*args,**kwargs,include_all=True)
class StatusTests(unittest.TestCase):
 def setUp(self):
  self.args={'query':'','filters':{},'date':'all','date_basis':'collected','include_history':False}
  self.now=datetime(2026,10,30,1,tzinfo=ZoneInfo('Asia/Shanghai'))
  self.versions=[{'id':'v','name':'A定制','kind':'tailored','job':{'job_id':'a'},'sha256':'x','reviewed':True,'reviewed_sha256':'x','created':'2026-10-29T16:30:00+00:00','reviewed_at':'2026-10-29T16:40:00+00:00'}]
  self.jobs=dashboard({'jobs':[{'job_id':'a','title':'AI测试','company':'腾讯','decision':'caution','jd':'JD','match':'分析'},{'job_id':'b','title':'开发','company':'测试公司'}]}, {'jobs':[{'job_id':'a','greet':'sent','reply':'no_reply','resume':'not_sent','interview':'scheduled','outcome':'open','dimension_times':{'greet':self.now.timestamp()}}]}, {'versions':self.versions})['jobs']
 def run_query(self,filters=None,**kwargs):
  return query(self.jobs,self.versions,[],self.args|{'filters':filters or {}}|kwargs,now=self.now)['tool_results'][0]
 def test_combined_greeting_reply_and_customization(self):
  r=self.run_query({'greet':'sent','reply':'no_reply','customized':'yes','resume':'not_sent'})
  self.assertEqual(r['count'],1);self.assertEqual(r['jobs'][0]['resume_versions'][0]['id'],'v')
  self.assertEqual(r['jobs'][0]['states']['resume_acceptance'],'unknown')
 def test_unrecorded_is_unknown_not_no_interview_or_rejection(self):
  r=self.run_query({'interview':'unknown'});self.assertEqual(r['count'],1);self.assertEqual(r['jobs'][0]['job_id'],'b')
  self.assertEqual(self.run_query({'interview':'none'})['count'],0)
 def test_company_query_and_or_values(self):
  self.assertEqual(self.run_query({'interview':['scheduled','completed']},query='腾讯')['count'],1)
  self.assertEqual(self.run_query(query='不存在')['count'],0)
  self.assertEqual(self.run_query(query='腾讯 AI测试')['count'],1)
 def test_action_kind_and_status_must_match_same_action(self):
  actions=[{'id':'1','job_id':'a','kind':'tailor_resume','status':'awaiting_review'},{'id':'2','job_id':'a','kind':'send_resume','status':'queued'}]
  args=self.args|{'filters':{'action_kind':'send_resume','action_status':'awaiting_review'}}
  self.assertEqual(query(self.jobs,self.versions,actions,args)['tool_results'][0]['count'],0)
  args['filters']['action_status']='queued';self.assertEqual(query(self.jobs,self.versions,actions,args)['tool_results'][0]['count'],1)
 def test_current_dimension_time_and_missing_time(self):
  r=self.run_query({'greet':'sent'},date='today',date_basis='greet');self.assertEqual(r['count'],1)
  r=self.run_query(date='today',date_basis='interview');self.assertEqual(r['count'],0);self.assertEqual(r['unknown_dates'],2)
 def test_customization_and_review_time_use_related_version(self):
  for basis in ('customized','reviewed'):
   self.assertEqual(self.run_query(date='today',date_basis=basis)['count'],1)
  self.versions[0]['reviewed_sha256']='changed'
  self.assertEqual(self.run_query(date='today',date_basis='reviewed')['count'],0)
 def test_history_redacts_private_payload(self):
  history=lambda key:[{'kind':'greet','value':'sent','at':1,'evidence':{'source':'manual','token':'secret','summary':'private chat'}}]
  r=query(self.jobs,self.versions,[],self.args|{'include_history':True},history)['tool_results'][0]
  self.assertNotIn('secret',str(r));self.assertNotIn('private chat',str(r));self.assertEqual(r['jobs'][0]['history'][0]['source'],'manual')
 def test_cross_platform_same_id_does_not_share_resume_or_actions(self):
  jobs=dashboard({'jobs':[{'job_id':'a','platform':'boss'},{'job_id':'a','platform':'51job'}]}, {}, {'versions':self.versions})['jobs']
  r=query(jobs,self.versions,[],self.args|{'filters':{'customized':'yes'}})['tool_results'][0]
  self.assertEqual(r['count'],1);self.assertEqual(r['jobs'][0]['platform'],'boss')
 def test_illegal_states_and_actions_rejected(self):
  for f in [{'resume_acceptance':'passed'},{'interview':'sent'},{'customized':True},{'greet':[]},{'execute':'send'}]:
   with self.assertRaises(ValueError):validate_args(self.args|{'filters':f})
  with self.assertRaises(ValueError):validate_args(self.args|{'date_basis':'updated_at'})
 def test_every_stored_dimension_is_queryable(self):
  from career_tracking import STATES
  self.assertTrue(set(STATES)<=set(FILTER_OPTIONS))
