import tempfile,unittest,importlib.util
from pathlib import Path
from unittest.mock import patch
from boss_ui_chat import HeadlessUIReplyAdapter,UIBlocked,challenge,validate_job
from greeting_tools import execute

JOB={'job_id':'demo','url':'https://www.zhipin.com/job_detail/demo.html','title':'AI测试','company':'示例公司','recruiter':'苏女士 · 示例公司招聘HR','recruiter_id':'123'}
TEXT='看到贵司的Agent评测岗位，我负责过银行Agent质量验证，希望交流测试体系建设经验。'

class GuardTests(unittest.TestCase):
 def test_job_identity_validation(self):
  self.assertEqual(validate_job(JOB)[1],'苏女士')
  for change in [{'url':'https://example.com/job_detail/demo.html'},{'job_id':'other'},{'recruiter':''}]:
   with self.assertRaises(UIBlocked):validate_job({**JOB,**change})
 def test_security_detection(self):
  self.assertTrue(challenge('https://www.zhipin.com/web/passport/zp/verify.html?code=36',''))
  self.assertTrue(challenge('https://www.zhipin.com','您的账号可能存在异常访问行为'))
  self.assertTrue(challenge(JOB['url'],'访问受限：您的账户存在异常行为，已暂时被限制访问'))
  self.assertFalse(challenge(JOB['url'],'正常岗位'))
 def test_gate_prevents_browser_and_send_queue(self):
  with tempfile.TemporaryDirectory() as t:
   gate=Path(t)/'data/ui-chat/security-blocked.json';gate.parent.mkdir(parents=True);gate.write_text('{}')
   result=HeadlessUIReplyAdapter(t).run(JOB,TEXT)
   self.assertFalse(result['verified_sent'])
   with self.assertRaises(ValueError):execute('greeting-ui-send',{},t)
   self.assertFalse((Path(t)/'data/greetings/plans.sqlite3').exists())
   with self.assertRaises(ValueError):execute('greeting-ui-resume',{'verification_completed':False},t)
   self.assertTrue(execute('greeting-ui-resume',{'verification_completed':True},t)['resumed'])
   self.assertFalse(gate.exists())

HTML='''<html><head><meta charset="utf-8"></head><body><h1>AI测试</h1><h2>苏女士 在线</h2><p>示例公司</p><a href="#" onclick="document.getElementById('chat').hidden=false;return false">继续沟通</a><section hidden id="chat"><h3>苏女士 示例公司·招聘HR</h3><textarea placeholder="请简短描述您的问题"></textarea><button onclick="document.querySelector('#messages').textContent=document.querySelector('textarea').value;document.querySelector('textarea').value='';document.body.dataset.sent=String(Number(document.body.dataset.sent||0)+1)">发送</button><div id="messages"></div></section></body></html>'''

@unittest.skipUnless(importlib.util.find_spec('patchright'), 'Optional UI runtime not installed')
class OfflineBrowserTests(unittest.TestCase):
 def run_fixture(self,dry_run,html=HTML):
  from patchright.sync_api import sync_playwright as real_playwright
  from types import SimpleNamespace
  from contextlib import nullcontext
  with tempfile.TemporaryDirectory() as root,real_playwright() as p:
   state={}
   class Browser:
    def __init__(self):self.b=p.chromium.launch(executable_path='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',headless=True)
    def new_context(self,**kwargs):
     self.c=self.b.new_context(**kwargs);self.c.route('https://www.zhipin.com/**',lambda route:route.fulfill(status=200,content_type='text/html',body=html));return self.c
    def close(self):
     pages=self.c.pages
     state['sent']=pages[0].evaluate('Number(document.body.dataset.sent||0)') if pages else 0
     state['body']=pages[0].content() if pages else '';state['url']=pages[0].url if pages else ''
     self.b.close()
   fake=SimpleNamespace(chromium=SimpleNamespace(launch=lambda **kwargs:Browser()))
   adapter=HeadlessUIReplyAdapter(root,dry_run=dry_run)
   adapter.readback=lambda *args:{'verified_sent':True,'status':'sent','receipt':{'message_id':'fixture-only'}}
   with patch('patchright.sync_api.sync_playwright',lambda:nullcontext(fake)),patch('boss_agent_cli.auth.token_store.TokenStore.load',return_value={'cookies':{'wt2':'fixture'}}):result=adapter.run(JOB,TEXT)
   return result,state
 def test_dry_run_does_not_type_or_send(self):
  result,state=self.run_fixture(True)
  self.assertTrue(result.get('selectors_verified'),str((result,state)));self.assertFalse(result['clicked_send']);self.assertEqual(state['sent'],0)
 def test_ui_fills_clicks_and_requires_receipt(self):
  result,state=self.run_fixture(False)
  self.assertTrue(result['verified_sent'],str((result,state)));self.assertEqual(state['sent'],1);self.assertTrue(result['ui_echo'])
 def test_first_contact_default_followed_by_custom(self):
  result,state=self.run_fixture(False,HTML.replace('继续沟通','立即沟通'))
  self.assertTrue(result['default_greeting_triggered']);self.assertTrue(result['clicked_send']);self.assertEqual(state['sent'],1)
  self.assertTrue(result['verified_sent'])
 def test_first_contact_dry_run_does_not_trigger_default(self):
  result,state=self.run_fixture(True,HTML.replace('继续沟通','立即沟通'))
  self.assertFalse(result['clicked_send']);self.assertEqual(state['sent'],0)
  self.assertIn('FIRST_CONTACT_READY',result['reason'])
