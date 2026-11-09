import hashlib,json,tempfile,unittest
from pathlib import Path
from assistant_skills import SkillRuntime
from chat_intents import IntentError,IntentRouter
class SkillTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name)
  self.path=self.root/'skills/job-search-screening/SKILL.md';self.path.parent.mkdir(parents=True);self.path.write_text('先查询本地岗位，不能把待分析当成筛选完成。')
  self.runtime=SkillRuntime(self.root)
  self.data={'messages':[{'role':'user','content':'看看已经筛选的岗位'}]}
  self.plan={'tool':'skill.run','arguments':{'id':'job-search-screening'}}
 def tearDown(self):self.tmp.cleanup()
 def test_catalog_then_actual_file_loading_before_tool_plan(self):
  seen=[]
  expected={'tool':'jobs.list','arguments':{'date':'all','basis':'screened','screening':'all'}}
  def model(i,c):seen.append(c);return json.dumps(expected)
  result,used=self.runtime.resolve(self.plan,self.data,[],IntentRouter(model))
  self.assertEqual(result,expected);self.assertEqual(seen[0]['loaded_skill']['instructions'],self.path.read_text())
  self.assertEqual(used[0]['sha256'],hashlib.sha256(self.path.read_bytes()).hexdigest())
 def test_missing_skill_unknown_skill_and_recursion_do_not_execute(self):
  with self.assertRaises(IntentError):self.runtime.resolve({'tool':'skill.run','arguments':{'id':'../../bad'}},self.data,[],None)
  self.path.unlink()
  with self.assertRaises(IntentError):self.runtime.resolve(self.plan,self.data,[],None)
  self.path.write_text('instructions')
  with self.assertRaises(IntentError):self.runtime.resolve(self.plan,self.data,[],IntentRouter(lambda *a:json.dumps(self.plan)))
 def test_skill_cannot_expand_registered_tool_scope(self):
  plan={'tool':'resume.list','arguments':{'date':'all','basis':'created','kind':'all','reviewed':'all'}}
  with self.assertRaises(IntentError):self.runtime.resolve(self.plan,self.data,[],IntentRouter(lambda *a:json.dumps(plan)))
 def test_catalog_selection_and_normal_chat_skips_skill_loading(self):
  self.assertEqual(self.runtime.catalog()[0]['id'],'job-search-screening')
  p={'tool':'chat.respond','arguments':{'answer':'你好'}}
  self.assertEqual(self.runtime.resolve(p,self.data,[],None),(p,[]))
  with self.assertRaises(IntentError):IntentRouter(lambda *a:json.dumps(self.plan)).plan(self.data,[],skills=[])

 def test_skill_planning_keeps_latest_context_with_a_bounded_history(self):
  seen=[]
  expected={'tool':'jobs.status','arguments':{'query':'XTransfer','filters':{},'date':'all','date_basis':'collected','include_history':False}}
  def model(i,c):seen.append(c);return json.dumps(expected)
  data={'messages':[{'role':'assistant','content':'old '*3000},{'role':'assistant','content':'第一个岗位是XTransfer金融测试主管'},{'role':'user','content':'第一个打过招呼么'}]}
  result,_=self.runtime.resolve(self.plan,data,[],IntentRouter(model))
  self.assertLessEqual(sum(len(m['content']) for m in seen[0]['messages']),2500)
  self.assertEqual(seen[0]['messages'][-1]['content'],'第一个打过招呼么')
  self.assertIn('XTransfer',str(seen[0]['messages']));self.assertEqual(result,expected)
