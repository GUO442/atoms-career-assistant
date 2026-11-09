import unittest
from datetime import datetime
from zoneinfo import ZoneInfo
from local_chat_tools import resume_list,jobs_list
class ResumeQueryTests(unittest.TestCase):
 def setUp(self):
  self.now=datetime(2026,10,30,1,tzinfo=ZoneInfo('Asia/Shanghai'))
  self.args={'date':'today','basis':'created','kind':'all','reviewed':'all'}
 def test_shanghai_day_boundary_and_unknown_dates(self):
  vs=[{'id':str(i),'name':str(i),'created':created} for i,created in enumerate(['2026-10-29T16:01:00+00:00','2026-10-29T15:59:00+00:00','bad'])]
  r=resume_list(vs,self.args,self.now)['tool_results'][0]
  self.assertEqual([v['id'] for v in r['versions']],['0']);self.assertEqual(r['unknown_dates'],1)
 def test_screening_never_silently_substitutes_creation(self):
  r=resume_list([{'name':'test','created':self.now.isoformat()}],self.args|{'basis':'screened'},self.now)
  self.assertEqual(r['tool_results'][0]['status'],'unsupported_basis');self.assertIn('你是想',r['answer'])
 def test_review_filters_and_review_timestamp(self):
  vs=[{'id':'a','name':'a','kind':'tailored','created':'2026-10-28T01:00:00+00:00','reviewed':True,'sha256':'same','reviewed_sha256':'same','reviewed_at':self.now.isoformat()},
      {'id':'b','name':'b','kind':'tailored','reviewed':True,'sha256':'changed','reviewed_sha256':'old','reviewed_at':self.now.isoformat()}]
  r=resume_list(vs,self.args|{'basis':'reviewed','reviewed':'yes','kind':'tailored'},self.now)
  self.assertEqual(r['tool_results'][0]['count'],1)
  self.assertEqual(r['tool_results'][0]['versions'][0]['id'],'a')
 def test_yesterday_and_empty(self):
  r=resume_list([],self.args|{'date':'yesterday'},self.now)
  self.assertEqual(r['tool_results'][0]['date'],'2026-10-29');self.assertIn('暂无已保存简历',r['answer'])
 def test_jobs_current_screening_and_dated_screening(self):
  args={'date':'today','basis':'screened','screening':'recommend'}
  self.assertEqual(jobs_list([],args,self.now)['tool_results'][0]['status'],'unsupported_basis')
  r=jobs_list([{'job_id':'a','screening':'recommend'},{'job_id':'b','screening':'reject'},{'job_id':'c','screening':'unassessed'}],args|{'date':'all'},self.now)
  self.assertEqual(r['tool_results'][0]['count'],1)
  all_results=jobs_list([{'job_id':'a','screening':'recommend'},{'job_id':'b','screening':'unassessed'}],args|{'date':'all','screening':'all'},self.now)
  self.assertEqual(all_results['tool_results'][0]['count'],1)
