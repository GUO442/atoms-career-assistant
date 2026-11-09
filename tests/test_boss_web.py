import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import boss_web
from boss_tools import execute
from discovery import Discovery
from boss_chat import run

class WebTests(unittest.TestCase):
 def setUp(self):
  self.session=patch("boss_web.ensure_session",return_value={"logged_in":True});self.session.start();self.addCleanup(self.session.stop)
 def test_login_is_checked_before_any_job_request(self):
  self.session.stop()
  with patch('boss_web.request',side_effect=boss_web.WebError('AUTH_REQUIRED','请先登录')) as req:
   result=boss_web.call('search',{'query':'AI','city':'深圳'})
   self.assertEqual(result['error']['code'],'AUTH_REQUIRED');self.assertEqual(req.call_count,1)
   self.assertEqual(req.call_args.args[0],'/wapi/zpuser/wap/getUserInfo.json')
 def test_search_uses_observed_post_and_preserves_detail_context(self):
  with patch('boss_web.request',return_value={'lid':'list-lid','hasMore':True,'jobList':[{'encryptJobId':'abc','securityId':'sec','jobName':'AI测试','brandName':'企业'}]}) as req:
   result=execute('search',{'query':'AI测试','city':'深圳'})
   self.assertTrue(result['ok']);self.assertTrue(result['live'])
   path,method,params=req.call_args.args
   self.assertEqual(method,'POST');self.assertEqual(path,'/wapi/zpgeek/search/joblist.json');self.assertEqual(params['city'],'101280600');self.assertEqual(params['pageSize'],'10')
   self.assertEqual(result['data']['items'][0]['lid'],'list-lid');self.assertEqual(result['data']['items'][0]['security_id'],'sec')
 def test_detail_uses_security_and_lid_and_validates_identity(self):
  with patch('boss_web.request',return_value={'jobInfo':{'encryptId':'abc','postDescription':'真实JD'}}) as req:
   self.assertTrue(boss_web.call('detail',{'job_id':'abc','security_id':'sec','lid':'lid'})['ok'])
   path,method,params=req.call_args.args
   self.assertEqual(method,'GET');self.assertEqual(params['securityId'],'sec');self.assertEqual(params['lid'],'lid');self.assertIn('_',params)
  with patch('boss_web.request',return_value={'jobInfo':{'encryptId':'other','postDescription':'其他岗位'}}):
   r=boss_web.call('detail',{'job_id':'abc','security_id':'sec','lid':'lid'})
   self.assertFalse(r['ok']);self.assertEqual(r['error']['code'],'JOB_MISMATCH')
 def test_auth_risk_and_html_stop_without_retry_or_raw_response(self):
  for response in ({'http_status':200,'body':{'code':37,'message':'secret-cookie'}},{'http_status':403},{'http_status':200,'invalid_json':True}):
   with self.subTest(response=response),patch('boss_web.evaluate',return_value=response) as evaluate:
    r=boss_web.call('search',{'query':'AI','city':'上海'})
    self.assertFalse(r['ok']);self.assertEqual(evaluate.call_count,1);self.assertNotIn('secret-cookie',json.dumps(r))
 def test_invalid_inputs_never_reach_transport(self):
  for args in ({'query':'AI','city':'未知'},{'query':'AI','city':'深圳','page':True},{'query':'AI','city':'深圳','url':'https://other.test'}):
   with patch('boss_web.request') as req:
    self.assertFalse(boss_web.call('search',args)['ok']);req.assert_not_called()
  with patch('boss_web.request') as req:
   self.assertFalse(boss_web.call('detail',{'job_id':'abc','security_id':'sec'})['ok']);req.assert_not_called()
 def test_schema_change_is_not_empty_success(self):
  with patch('boss_web.request',return_value={}):self.assertEqual(boss_web.call('search',{'query':'AI','city':'深圳'})['error']['code'],'INVALID_RESPONSE')
  with patch('boss_web.request',return_value={'jobList':[]}):self.assertEqual(boss_web.call('search',{'query':'AI','city':'深圳'})['data']['items'],[])
 def test_browser_failure_is_explicit(self):
  with patch('boss_web.targets',side_effect=boss_web.WebError('BROWSER_NOT_READY','请先登录')):
   self.assertEqual(boss_web.call('search',{'query':'AI','city':'深圳'})['error']['code'],'BROWSER_NOT_READY')

 def test_recommend_types_preserve_detail_fields(self):
  for kind,sort_type in [('featured','1'),('latest','2')]:
   with self.subTest(kind=kind),patch('boss_web.request',side_effect=[{'expectList':[{'encryptId':'expect-real','positionName':'测试'}]},{'jobList':[{'encryptJobId':'abc','securityId':'sec','lid':'lid','jobName':'测试'}],'totalCount':15}]) as req,patch('boss_web.evaluate',return_value={'pk':'observed-page-key'}):
    r=execute('recommend',{'kind':kind})
    self.assertTrue(r['ok']);self.assertTrue(r['live']);self.assertEqual(r['data']['items'][0]['lid'],'lid');self.assertTrue(r['data']['default_expectation'])
    path,method,params=req.call_args.args
    self.assertEqual(path,'/wapi/zpgeek/recommend/job/list.json');self.assertEqual(method,'GET');self.assertEqual(params['sortType'],sort_type);self.assertEqual(params['expectId'],'expect-real');self.assertEqual(params['pk'],'observed-page-key')
 def test_recommend_rejects_invalid_params_and_unknown_expectations(self):
  for args in ({'kind':'invented'},{'page':True},{'expect_id':''},{'url':'https://other.test'}):
   with patch('boss_web.request') as req:
    self.assertFalse(execute('recommend',args)['ok']);req.assert_not_called()
  with patch('boss_web.request',return_value={'expectList':[{'encryptId':'real'}]}) as req:
   self.assertEqual(execute('recommend',{'expect_id':'invented'})['error']['code'],'INVALID_EXPECTATION');self.assertEqual(req.call_count,1)
 def test_empty_expectations_and_auth_failure_do_not_call_job_list(self):
  with patch('boss_web.request',return_value={'expectList':[]}) as req:
   self.assertEqual(execute('recommend',{})['error']['code'],'NO_EXPECTATIONS');self.assertEqual(req.call_count,1)
  with patch('boss_web.ensure_session',side_effect=boss_web.WebError('AUTH_REQUIRED','请手动登录')),patch('boss_web.request') as req,patch('boss_web.open_login') as login:
   self.assertEqual(execute('recommend',{})['error']['code'],'AUTH_REQUIRED');req.assert_not_called();login.assert_not_called()

class PcRecommendTests(unittest.TestCase):
 def test_pc_page_uses_its_own_conditions_and_interface(self):
  with patch('boss_web.ensure_session'),patch('boss_web.request',side_effect=[{'mixExpect':{'encryptExpectId':'mix-real','location':101280600,'locationName':'深圳','mixExpectType':1}},{'jobList':[{'encryptJobId':'abc','jobName':'AI测试工程师','securityId':'sec','lid':'lid'}]}]) as req:
   r=boss_web.call('recommend',{'kind':'recommended'})
   self.assertTrue(r['ok'])
   self.assertEqual(r['data']['items'][0]['security_id'],'sec')
   path,method,params=req.call_args.args
   self.assertEqual(path,'/wapi/zpgeek/pc/recommend/job/list.json')
   self.assertEqual(params['encryptExpectId'],'mix-real')
   self.assertEqual(params['city'],'101280600')
   self.assertEqual(params['pageSize'],'15')
 def test_missing_mix_stops_before_job_query(self):
  with patch('boss_web.ensure_session'),patch('boss_web.request',return_value={}) as req:
   r=boss_web.call('recommend',{'kind':'recommended'})
   self.assertFalse(r['ok']);self.assertEqual(req.call_count,1)

class ChatTests(unittest.TestCase):
 def test_latest_recommendations_can_be_read_by_chat_then_detailed(self):
  with tempfile.TemporaryDirectory() as tmp:
   calls=[]
   def query(name,args):
    calls.append((name,args))
    return {'ok':True,'data':{'items':[{'job_id':'abc','security_id':'sec','lid':'lid','title':'软件测试工程师'}],'default_expectation':True} if name=='recommend' else {'job_id':'abc','description':'完整JD'}}
   discovery=Discovery(tmp,query,None)
   decisions=iter([{'tool':'recommend','arguments':{'kind':'latest'}},{'tool':'detail','arguments':{'job_id':'abc'}},{'tool':'done','arguments':{}}])
   r=run({'messages':[{'role':'user','content':'看看最新职位并读取JD'}]},lambda *a:json.dumps(next(decisions)),discovery,query)
   self.assertEqual([n for n,a in calls],['recommend','detail']);self.assertEqual(r[1]['job']['jd'],'完整JD')
 def test_chat_search_then_jd_without_resume(self):
  with tempfile.TemporaryDirectory() as tmp:
   query_calls=[]
   def query(name,args):
    query_calls.append((name,args))
    return {'ok':True,'data':{'items':[{'job_id':'abc','security_id':'sec','lid':'lid','title':'AI测试','company':'企业'}]} if name=='search' else {'job_id':'abc','description':'真实JD'}}
   discovery=Discovery(tmp,query,None)
   decisions=iter([{'tool':'search','arguments':{'query':'AI测试','city':'深圳'}},{'tool':'detail','arguments':{'job_id':'abc'}},{'tool':'done','arguments':{}}])
   result=run({'messages':[{'role':'user','content':'帮我找深圳AI测试岗位，读取JD'}]},lambda *a:json.dumps(next(decisions)),discovery,query)
   self.assertEqual([n for n,a in query_calls],['search','detail']);self.assertEqual(query_calls[1][1]['lid'],'lid');self.assertEqual(result[1]['job']['jd'],'真实JD')
   self.assertNotIn('security_id',json.dumps(result));self.assertEqual(discovery.load()['jobs'][0]['jd'],'真实JD')
 def test_failure_stops_dispatch_and_does_not_return_previous_jobs_as_current(self):
  with tempfile.TemporaryDirectory() as tmp:
   discovery=Discovery(tmp,lambda *a:{'ok':False,'error':{'code':'AUTH_REQUIRED','message':'请登录'}},None)
   discovery.put({'jobs':[{'job_id':'old','title':'旧岗位'}]})
   calls=[]
   def model(*args):calls.append(args);return json.dumps({'tool':'search','arguments':{'query':'AI测试','city':'深圳'}})
   r=run({'messages':[{'role':'user','content':'BOSS搜索岗位'}]},model,discovery,None)
   self.assertEqual(len(calls),1);self.assertIn('error',r[0]);self.assertNotIn('旧岗位',json.dumps(r,ensure_ascii=False))
 def test_invented_job_and_write_tools_never_execute(self):
  with tempfile.TemporaryDirectory() as tmp:
   discovery=Discovery(tmp,None,None)
   for plan in ({'tool':'detail','arguments':{'job_id':'invented'}},{'tool':'send-resume','arguments':{}}):
    with patch.object(discovery,'read_detail') as read:
     result=run({'messages':[{'role':'user','content':'@boss-web-tools 查岗位'}]},lambda *a:json.dumps(plan),discovery,None)
     read.assert_not_called();self.assertIn('error',result[0])
if __name__=='__main__':unittest.main()
