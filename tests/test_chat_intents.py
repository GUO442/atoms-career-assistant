import json,unittest
from chat_intents import IntentRouter,IntentError,validate
class IntentTests(unittest.TestCase):
 def test_every_message_reaches_semantic_model_without_keyword_gate(self):
  seen=[]
  plan={'tool':'resume.list','arguments':{'date':'today','basis':'screened','kind':'all','reviewed':'all'}}
  def model(instruction,ctx):seen.append(ctx);return json.dumps(plan)
  router=IntentRouter(model)
  for text in ['今天帮我看一下一共筛选了哪些简历。','今日整理好的履历有哪些','帮我瞅瞅那些','那昨天呢','你好']:
   router.plan({'messages':[{'role':'user','content':text}]},[])
  self.assertEqual(len(seen),5)
 def test_context_followup_preserves_history_roles_and_no_full_resume_in_router(self):
  seen=[]
  def model(i,c):seen.append(c);return json.dumps({'tool':'clarify','arguments':{'question':'你指的是简历还是岗位？'}})
  data={'messages':[{'role':'user','content':'查看昨天保存的简历'},{'role':'assistant','content':'昨日有2份'},{'role':'user','content':'那今天呢'}],'resume':'sensitive full resume'}
  result=IntentRouter(model).plan(data,[])
  self.assertEqual(len(seen[0]['messages']),3);self.assertNotIn('sensitive',json.dumps(seen));self.assertEqual(result['tool'],'clarify')
 def test_invalid_json_and_unknown_tools_fail_without_fallback(self):
  for raw in ['bad','[]',json.dumps({'tool':'shell.execute','arguments':{}}),json.dumps({'tool':'boss.query','arguments':{'command':'bad'}})]:
   with self.assertRaises(IntentError):IntentRouter(lambda *a:raw).plan({'messages':[{'role':'user','content':'test'}]},[])
 def test_invalid_dates_enums_or_extra_fields_rejected(self):
  base={'date':'today','basis':'created','kind':'all','reviewed':'all'}
  for delta in [{'date':'2026-02-30'},{'basis':'guessed'},{'command':'shell'},{'reviewed':True}]:
   with self.assertRaises(IntentError):validate({'tool':'resume.list','arguments':base|delta})
 def test_registered_tool_catalog_accepts_structured_workflow(self):
  p={'tool':'harness','arguments':{'action':'status','arguments':{}}};self.assertEqual(validate(p),p)
