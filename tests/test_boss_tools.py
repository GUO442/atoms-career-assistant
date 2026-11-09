import json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from boss_tools import inspect_har,execute
class ToolTests(unittest.TestCase):
 def test_har_redacts_secrets(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'capture.har';p.write_text(json.dumps({'log':{'entries':[{'request':{'method':'POST','url':'https://www.zhipin.com/wapi/test?securityId=private-value','headers':[{'name':'Cookie','value':'secret-cookie'}],'postData':{'params':[{'name':'resumeId','value':'private-resume'}],'text':'secret-payload'}},'response':{'status':200,'content':{'text':'private-response'}}},{'request':{'url':'https://other.example/wapi/test'},'response':{}}]}}))
   r=inspect_har(p);s=json.dumps(r)
   for secret in ('private-value','secret-cookie','private-resume','secret-payload','private-response','other.example'):self.assertNotIn(secret,s)
   self.assertEqual(len(r['requests']),1);self.assertEqual(r['requests'][0]['query_fields'],['securityId'])
 def test_no_unverified_send(self):
  self.assertFalse(execute('send-resume',{})['sent'])
  with self.assertRaises(ValueError):execute('prepare-application',{'version_id':'x'})
 def test_captured_search_is_not_live(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'capture.har';p.write_text(json.dumps({'log':{'entries':[{'request':{'method':'POST','url':'https://www.zhipin.com/wapi/zpgeek/search/joblist.json','postData':{'params':[{'name':'query','value':'AI%E6%B5%8B%E8%AF%95'},{'name':'city','value':'101280600'}]}},'response':{'content':{'text':json.dumps({'code':0,'zpData':{'jobList':[{'encryptJobId':'real-id','jobName':'AI test','brandName':'Company'}]}})}}}]}}))
   r=execute('captured-search',{'file':str(p),'query':'AI测试','city_code':'101280600'})
   self.assertFalse(r['live']);self.assertEqual(r['data'][0]['job_id'],'real-id')
   self.assertEqual(execute('captured-search',{'file':str(p),'query':'different'})['data'],[])
 def test_reject_unknown_filters(self):
  self.assertEqual(execute('search',{'query':'AI','city':'深圳','unexpected':True})['error']['code'],'INVALID_ARGUMENT')
if __name__=='__main__':unittest.main()

class RecommendJobToolTests(unittest.TestCase):
 def test_catalog_registers_filtered_recommendation(self):
  self.assertIn('recommend-jobs',[t['name'] for t in execute('catalog',{})['tools']])
 def test_tool_uses_shared_database_filter_and_rejects_args(self):
  from discovery import Discovery
  from boss_tools import filtered_recommend
  with tempfile.TemporaryDirectory() as tmp:
   d=Discovery(tmp,lambda *a:{'ok':True,'data':{'items':[{'job_id':'a','title':'AI开发工程师'},{'job_id':'b','title':'AI开发实习生'}]}},None)
   first=filtered_recommend(d,{})
   self.assertTrue(first['live']);self.assertEqual(len(first['data']['jobs']),1)
   self.assertEqual(first['data']['filtered_count'],1)
   self.assertEqual(filtered_recommend(d,{})['data']['duplicate_count'],2)
   with self.assertRaises(ValueError):filtered_recommend(d,{'url':'https://example.com'})
