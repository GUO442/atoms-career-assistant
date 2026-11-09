import unittest,tempfile
from discovery import classify_job,Discovery
from boss_web import normalize_jobs
from chat_opportunities import assessment_key,sanitized_message

class HardFilterTests(unittest.TestCase):
 def test_exclusions(self):
  for fields in ({'jobStatus':'closed'},{'isClosed':True},{'jd':'该职位已关闭'},{'salary':'300-500元/天'},{'salary':'日结400元'},{'salaryUnit':'day'},{'jd':'薪资按天计薪'}):
   with self.subTest(fields=fields):self.assertEqual(classify_job({'title':'AI测试开发',**fields})[0],'excluded')
 def test_not_false_positive(self):
  for fields in ({'jobStatus':0},{'jobStatus':1},{'jd':'负责日结算系统自动化测试'},{'salary':'30-40K','jd':'非日结，月薪制'},{'isClosed':False}):
   with self.subTest(fields=fields):self.assertEqual(classify_job({'title':'AI测试开发',**fields})[0],'included')
 def test_normalization_and_cache(self):
  j=normalize_jobs({'jobList':[{'encryptJobId':'abc','jobName':'AI测试','jobStatusDesc':'已关闭','salaryDesc':'300元/天'}]})[0]
  self.assertEqual(j['jobStatusDesc'],'已关闭')
  self.assertNotEqual(assessment_key(j,'',None),assessment_key({**j,'jobStatusDesc':'招聘中'},'',None))
  m=sanitized_message({'body':{'jobDesc':{'title':'AI测试','isClosed':True}},'from':{}},'1','2')
  self.assertTrue(m['job']['isClosed'])
 def test_search_and_fresh_import_preserve_status(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Discovery(tmp,lambda *_:{'ok':True,'data':[{'job_id':'abc','title':'AI测试','jobStatusDesc':'已关闭'}]},None)
   self.assertEqual(d.search('AI测试','深圳')['jobs'],[])
   self.assertEqual(d.history()['jobs'][0]['filter_reason'],'岗位已关闭')
   d.import_jobs([{'job_id':'abc','jobStatusDesc':'招聘中','salary':'300元/天'}])
   # Existing snapshots keep salary; explicit fresh status fields update.
   self.assertEqual(d.history()['jobs'][0]['jobStatusDesc'],'招聘中')
