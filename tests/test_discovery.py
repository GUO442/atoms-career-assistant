import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from discovery import Discovery
class SourceTests(unittest.TestCase):
 def test_sources_and_match(self):
  with tempfile.TemporaryDirectory() as tmp:
   def query(name,args):
    return {'ok':True,'data':[{'job_id':'abc','security_id':'real-id','company':'企业','title':'AI测试','salary':'30-40K'}] if name=='search' else {'job_id':'abc','description':'真实JD'}}
   d=Discovery(tmp,query,lambda *args:'{"decision":"recommend","analysis":"真实证据"}')
   r=d.search('AI测试','深圳');self.assertEqual(r['jobs'][0]['url'],'https://www.zhipin.com/job_detail/abc.html')
   j=d.detail('abc','真实简历','深圳',True);self.assertEqual(j['jd'],'真实JD');self.assertEqual(j['decision'],'recommend')
 def test_risk_does_not_fabricate_results(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Discovery(tmp,lambda *args:{'ok':False,'error':{'code':'ENVIRONMENT_RISK','message':'环境异常'}},None)
   with self.assertRaises(ValueError):d.search('AI测试','深圳')
   self.assertEqual(d.load()['jobs'],[]);self.assertEqual(d.load()['status'],'blocked')
if __name__=='__main__':unittest.main()

class DatabaseTests(unittest.TestCase):
 def test_migration_restart_and_history(self):
  import json
  with tempfile.TemporaryDirectory() as tmp:
   legacy={'jobs':[{'job_id':'old','title':'旧岗位','jd':'完整JD','match':'符合要求','decision':'recommend','status':'matched'}]}
   Path(tmp,'discovery.json').write_text(json.dumps(legacy))
   d=Discovery(tmp,None,None)
   self.assertEqual(d.history()['total'],1)
   d.put({'jobs':[{'job_id':'new','title':'Java开发工程师'}]},refresh=True)
   restarted=Discovery(tmp,None,None)
   self.assertEqual(restarted.history()['total'],2)
   self.assertEqual(restarted.load()['jobs'][0]['job_id'],'new')
   self.assertEqual(next(j for j in restarted.history()['jobs'] if j['job_id']=='old')['decision'],'recommend')
 def test_repeat_query_preserves_match_and_updates_metadata(self):
  with tempfile.TemporaryDirectory() as tmp:
   def query(name,args):return {'ok':True,'data':{'items':[{'job_id':'abc','title':'AI测试工程师','security_id':'new-sec','lid':'new-lid'}]}}
   d=Discovery(tmp,query,None)
   first=d.recommend('latest');self.assertEqual(first['new_count'],1)
   d.put({'jobs':[{**first['jobs'][0],'match':'符合','decision':'recommend','jd':'真实JD','status':'matched'}]})
   second=d.recommend('latest')
   self.assertEqual(second['new_count'],0);self.assertEqual(second['seen_count'],1)
   self.assertEqual(second['jobs'],[])
   saved=d.history()['jobs'][0]
   self.assertEqual(saved['decision'],'recommend');self.assertEqual(saved['security_id'],'new-sec')
   self.assertEqual(d.history()['total'],1)
 def test_search_reuses_history_and_failed_query_retains_it(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Discovery(tmp,lambda *a:{'ok':True,'data':{'items':[{'job_id':'abc','title':'测试'}]}},None)
   self.assertEqual(d.search('测试','深圳')['new_count'],1)
   self.assertEqual(d.search('测试','深圳')['seen_count'],1)
   d.query=lambda *a:{'ok':False,'error':{'message':'登录过期'}}
   with self.assertRaises(ValueError):d.search('测试','深圳')
   self.assertEqual(d.history()['total'],1)

class DedupTests(unittest.TestCase):
 def test_dedup_across_restart_and_search_recommend(self):
  with tempfile.TemporaryDirectory() as tmp:
   query=lambda *a:{'ok':True,'data':{'items':[{'job_id':'old','title':'旧岗位'},{'job_id':'new','title':'Java开发工程师'},{'job_id':'new','title':'重复条目'}]}}
   d=Discovery(tmp,query,None)
   d.put({'jobs':[{'job_id':'old','decision':'recommend','match':'已筛选'}]})
   result=d.recommend('latest')
   self.assertEqual([j['job_id'] for j in result['jobs']],['new'])
   self.assertEqual(result['jobs'][0]['title'],'Java开发工程师')
   self.assertEqual(result['duplicate_count'],1)
   self.assertEqual(result['received_count'],2)
   restarted=Discovery(tmp,query,None)
   result=restarted.search('测试','深圳')
   self.assertEqual(result['jobs'],[])
   self.assertEqual(result['duplicate_count'],2)
   self.assertEqual(restarted.history()['total'],2)
   self.assertEqual(next(j for j in restarted.history()['jobs'] if j['job_id']=='old')['match'],'已筛选')
 def test_failed_transaction_does_not_mark_partial_results_seen(self):
  with tempfile.TemporaryDirectory() as tmp:
   d=Discovery(tmp,None,None)
   with self.assertRaises(ValueError):d.put({'jobs':[{'job_id':'good'},{'job_id':'bad!'}]},refresh=True)
   self.assertEqual(d.history()['total'],0)
   result={'jobs':[{'job_id':'good'}]};d.put(result,refresh=True)
   self.assertEqual(result['new_count'],1)

class JobFilterTests(unittest.TestCase):
 def test_strict_role_rules(self):
  from discovery import classify_job
  for title in ['Agent开发工程师','Java开发工程师','大模型测试工程师','软件测试工程师','Python后端工程师','AI产品销售','AI产品经理','AI专家']:
   self.assertEqual(classify_job({'title':title})[0],'included',title)
  for title in ['算法实习生','AI开发实习生','AI Intern','客服','测试','机械工程师']:
   self.assertEqual(classify_job({'title':title})[0],'excluded',title)
  self.assertEqual(classify_job({'title':'软件开发工程师','jd':'有实习经历优先'})[0],'included')
  self.assertEqual(classify_job({'title':'软件开发工程师','jd':'岗位性质：实习'})[0],'excluded')
 def test_filtered_jobs_persist_but_never_return_as_candidates(self):
  with tempfile.TemporaryDirectory() as tmp:
   rows=[{'job_id':'good','title':'Agent开发工程师'},{'job_id':'intern','title':'AI开发实习生'},{'job_id':'unknown','title':'AI专家'}]
   d=Discovery(tmp,lambda *a:{'ok':True,'data':{'items':rows}},None)
   result=d.recommend('latest')
   self.assertEqual([j['job_id'] for j in result['jobs']],['good','unknown'])
   self.assertEqual(result['filtered_count'],1)
   self.assertEqual(d.history()['total'],3)
   self.assertTrue(all(j['filter_reason'] for j in d.history()['jobs']))
   self.assertEqual(d.recommend('latest')['jobs'],[])
 def test_detail_discovers_internship_before_model_matching(self):
  from unittest.mock import Mock
  with tempfile.TemporaryDirectory() as tmp:
   model=Mock()
   d=Discovery(tmp,lambda *a:{'ok':True,'data':{'job_id':'abc','description':'岗位性质：实习'}},model)
   d.put({'jobs':[{'job_id':'abc','title':'AI开发工程师','security_id':'sec','lid':'lid'}]})
   with self.assertRaisesRegex(ValueError,'实习岗位'):d.detail('abc','真实简历','',True)
   model.assert_not_called()
   self.assertEqual(d.load()['jobs'],[])
   self.assertEqual(d.history()['jobs'][0]['eligibility'],'excluded')
