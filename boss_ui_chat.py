"""Headless UI sender entered through an exact saved BOSS job URL.

No page SDK calls, direct message requests, or browser-debugging connection.
Security challenges stop execution. First contact may send the platform default, followed by the custom message.
"""
import argparse
import json
import os
import re
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit
from runtime_paths import WORKSPACE


class UIBlocked(ValueError):pass


def validate_job(job):
 key=job.get('job_id','');url=job.get('url','');parsed=urlsplit(url)
 if not re.fullmatch(r'[A-Za-z0-9_-]+',key) or parsed.scheme!='https' or parsed.hostname!='www.zhipin.com' or parsed.path!='/job_detail/'+key+'.html':raise UIBlocked('岗位ID与来源URL不一致')
 name=(job.get('recruiter') or '').split(' · ')[0].strip()
 if not name:raise UIBlocked('请先核验并保存该岗位HR姓名')
 if not job.get('company') or not job.get('title'):raise UIBlocked('岗位资料不完整')
 return url,name


def challenge(url,text):
 return '/verify' in url or 'code=36' in url or any(x in text for x in ['您的账号可能存在异常访问行为','请完成以下验证','操作过于频繁','访问受限','已暂时被限制访问'])


def single(locator,label):
 if locator.count()!=1:raise UIBlocked(label+'未唯一匹配，停止操作')
 return locator


class HeadlessUIReplyAdapter:
 # Accepts explicit test execution through the greeting queue. This marks the
 # adapter's receipt contract, not a claim of live headless-send acceptance.
 verified=True
 supported_kinds={'reply_text'}
 supports_first_contact=True
 def __init__(self,root=WORKSPACE,dry_run=False):self.root=Path(root);self.dry_run=dry_run
 def __call__(self,action):
  if action.get('kind')!='reply_text':raise UIBlocked('仅支持文本，不发送附件')
  from greeting_tools import Greetings
  job=next((j for j in Greetings(self.root).listing() if j['platform']=='boss' and j['job_id']==action.get('job_id')),None)
  if not job or str(job.get('recruiter_id'))!=str(action.get('recruiter_id')):raise UIBlocked('岗位或HR身份不匹配')
  return self.run(job,action.get('reply_text',''))
 def run(self,job,text):
  gate=self.root/'data/ui-chat/security-blocked.json'
  if gate.exists():return {'verified_sent':False,'status':'blocked','reason':'SECURITY_VERIFICATION_REQUIRED：请先人工完成平台验证，再明确解除暂停；未启动浏览器'}
  url,name=validate_job(job)
  if not isinstance(text,str) or not 20<=len(text)<=200:raise UIBlocked('定制消息须为20至200字')
  from patchright.sync_api import sync_playwright
  from boss_agent_cli.auth.token_store import TokenStore
  session=TokenStore(self.root/'data/boss-mcp/auth').load()
  if not session or not session.get('cookies',{}).get('wt2'):raise UIBlocked('本地登录态缺失，请先登录并同步')
  folder=self.root/'data/ui-chat'/uuid.uuid4().hex;folder.mkdir(parents=True,exist_ok=True);folder.chmod(0o700)
  result={'verified_sent':False,'dry_run':self.dry_run,'job_id':job['job_id'],'transport':'headless_ui','evidence_dir':str(folder),'clicked_send':False}
  def save(page,label):
   path=folder/(label+'.png')
   try:page.screenshot(path=str(path),timeout=5000);path.chmod(0o600)
   except Exception:pass
  with sync_playwright() as p:
   executable=os.environ.get('CAREER_CHROME','/Applications/Google Chrome.app/Contents/MacOS/Google Chrome')
   browser=p.chromium.launch(executable_path=executable,headless=True)
   try:
    context=browser.new_context(viewport={'width':1440,'height':1000})
    context.add_cookies([{'name':k,'value':v,'domain':'.zhipin.com','path':'/','secure':True} for k,v in session['cookies'].items()])
    page=context.new_page();page.set_default_timeout(12000)
    try:
     result['stage']='navigate'
     page.goto(url,wait_until='domcontentloaded',timeout=30000)
     # Wait for a real title or a real challenge, not a fixed sleep.
     ready=page.get_by_role('heading',name=job['title'],exact=True).or_(page.get_by_text(re.compile('安全验证|访问受限'),exact=False))
     result['stage']='wait-title'
     ready.first.wait_for(timeout=20000)
     body=page.locator('body').inner_text()
     if challenge(page.url,body):raise UIBlocked('SECURITY_VERIFICATION_REQUIRED：停止，不自动重试或切换通道')
     if urlsplit(page.url).path!=urlsplit(url).path:raise UIBlocked('来源页跳转到其他页面，请处理登录状态')
     result['stage']='verify-title'
     single(page.get_by_role('heading',name=job['title'],exact=True),'岗位标题')
     result['stage']='verify-hr'
     single(page.get_by_role('heading',name=re.compile(re.escape(name))),'HR标题')
     if job['company'] not in body:raise UIBlocked('页面企业与岗位记录不一致')
     result['stage']='job-screenshot'
     save(page,'01-job')
     result['stage']='open-chat'
     ongoing=page.get_by_role('link',name='继续沟通',exact=True)
     if ongoing.count()==0:
      first=single(page.get_by_role('link',name='立即沟通',exact=True),'立即沟通')
      if self.dry_run:raise UIBlocked('FIRST_CONTACT_READY：需要默认招呼后再定制；仅检查未点击')
      # First click has an external effect. Persist intent before it too.
      result['first_contact_attempted']=True
      record=folder/'result.json';record.write_text(json.dumps(result,ensure_ascii=False));record.chmod(0o600)
      first.click();result['default_greeting_triggered']=True
     else:single(ongoing,'继续沟通').click()
     editor=page.get_by_placeholder('请简短描述您的问题',exact=True)
     result['stage']='wait-editor'
     editor.wait_for(state='visible')
     single(editor,'聊天输入框')
     # Mini-chat heading observed in the existing job detail page.
     result['stage']='verify-chat'
     single(page.get_by_role('heading',name=re.compile(re.escape(name)+'.*'+re.escape(job['company']))),'聊天HR与企业标题')
     button=single(page.get_by_text('发送',exact=True),'发送按钮')
     result['stage']='check-draft'
     draft=editor.input_value()
     if draft.strip():raise UIBlocked('聊天输入框已有草稿，未覆盖')
     if page.get_by_text(text,exact=True).count():raise UIBlocked('当前页面已有相同消息，未重复发送')
     if not job.get('recruiter_id') and not self.dry_run:
      contact=self.resolve_contact(job)
      if contact.get('name')!=name:raise UIBlocked('新会话HR名称与来源页不一致')
      job={**job,'recruiter_id':str(contact['uid'])}
      from career_tracking import Tracker
      Tracker(self.root/'data/tracking').register(job)
     result['stage']='chat-screenshot'
     save(page,'02-chat-ready')
     result['selectors_verified']=True
     if self.dry_run:
      result['reason']='已核对岗位、HR、输入框与发送按钮；仅检查，未填写或发送'
     else:
      result['stage']='fill'
      editor.fill(text)
      if editor.input_value()!=text:raise UIBlocked('输入内容校验失败，未点击发送')
      # Keep the durable pending record before this final irreversible click.
      result['clicked_send']=True
      record=folder/'result.json';record.write_text(json.dumps(result,ensure_ascii=False));record.chmod(0o600)
      result['send_started_at']=time.time()
      result['stage']='send-click'
      button.click()
      result['stage']='echo'
      page.get_by_text(text,exact=True).wait_for(state='visible',timeout=15000)
      # A UI echo alone may be optimistic. Require the history readback too.
      result['ui_echo']=True;save(page,'03-ui-echo')
      receipt=self.readback(job,text,result['send_started_at'])
      result.update(receipt)
    except Exception as exc:
     if challenge(page.url,page.locator('body').inner_text(timeout=3000)) or (isinstance(exc,UIBlocked) and 'SECURITY_VERIFICATION_REQUIRED' in str(exc)):
      gate.write_text(json.dumps({'blocked_at':time.time(),'reason':'platform_security_verification'},ensure_ascii=False));gate.chmod(0o600)
     result['reason']=str(exc)[:250] if isinstance(exc,UIBlocked) else type(exc).__name__
     result['status']='unknown' if result['clicked_send'] or result.get('first_contact_attempted') else 'blocked'
     save(page,'blocked' if not result['clicked_send'] else 'unknown')
   finally:browser.close()
  record=folder/'result.json';record.write_text(json.dumps(result,ensure_ascii=False,indent=2));record.chmod(0o600)
  return result
 def resolve_contact(self,job):
  import httpx
  from boss_agent_cli.auth.token_store import TokenStore
  from boss_agent_cli.api import endpoints
  from boss_agent_cli.api.httpx_helpers import browser_headers
  s=TokenStore(self.root/'data/boss-mcp/auth').load();headers=browser_headers(endpoints.DEFAULT_HEADERS,s);headers['Referer']='https://www.zhipin.com/web/geek/chat'
  with httpx.Client(cookies=s['cookies'],headers=headers,timeout=20,follow_redirects=False) as client:
   response=client.get(endpoints.FRIEND_LIST_URL,params={'page':1,'__zp_stoken__':s.get('stoken','')});data=response.json()
  if data.get('code')!=0:raise UIBlocked('首次招呼后联系人查询失败，禁止重发')
  contacts=[c for c in (data.get('zpData') or {}).get('result',[]) if c.get('encryptJobId')==job['job_id']]
  if len(contacts)!=1 or not contacts[0].get('uid'):raise UIBlocked('新会话身份未唯一确认，禁止重发')
  return contacts[0]
 def readback(self,job,text,started):
  """Query independently using stored auth; never send or retry a write here."""
  import httpx
  from boss_agent_cli.auth.token_store import TokenStore
  from boss_agent_cli.api import endpoints
  from boss_agent_cli.api.httpx_helpers import browser_headers
  s=TokenStore(self.root/'data/boss-mcp/auth').load();headers=browser_headers(endpoints.DEFAULT_HEADERS,s);headers['Referer']='https://www.zhipin.com/web/geek/chat'
  with httpx.Client(cookies=s['cookies'],headers=headers,timeout=20,follow_redirects=False) as client:
   response=client.get(endpoints.FRIEND_LIST_URL,params={'page':1,'__zp_stoken__':s.get('stoken','')});data=response.json()
   if data.get('code')!=0:raise UIBlocked('回执查询登录失效或被限制')
   contact=next((c for c in (data.get('zpData') or {}).get('result',[]) if c.get('encryptJobId')==job['job_id'] and str(c.get('uid'))==str(job['recruiter_id'])),None)
   if not contact:raise UIBlocked('回执联系人不在查询范围，需核验，禁止重发')
   response=client.get('https://www.zhipin.com/wapi/zpchat/geek/historyMsg',params={'bossId':contact['encryptBossId'],'securityId':contact['securityId'],'maxMsgId':'0','c':'20','page':'1','src':'0','__zp_stoken__':s.get('stoken','')});data=response.json()
   if data.get('code')!=0:raise UIBlocked('历史消息查询失败')
   for message in (data.get('zpData') or {}).get('messages',[]):
    at=message.get('time',0);at=at/1000 if at>100000000000 else at
    if at<started-2:continue
    if (message.get('body') or {}).get('text')==text and str((message.get('to') or {}).get('uid'))==str(job['recruiter_id']):return {'verified_sent':True,'status':'sent','receipt':{'message_id':str(message['mid']),'source':'history_api_after_ui','at':time.time()}}
  return {'verified_sent':False,'status':'unknown','reason':'页面已有回显但未取得历史消息回执，禁止重发'}


def probe(job_id,root=WORKSPACE):
 from greeting_tools import Greetings
 job=next((j for j in Greetings(root).listing() if j['platform']=='boss' and j['job_id']==job_id),None)
 if not job:raise UIBlocked('岗位未入库')
 return HeadlessUIReplyAdapter(root,dry_run=True).run(job,'仅用于定位校验的占位内容，不会填写或发送给招聘者。')


def main():
 parser=argparse.ArgumentParser();parser.add_argument('action',choices=['probe','send-plan']);parser.add_argument('--job-id');parser.add_argument('--plan-id');parser.add_argument('--max-jobs',type=int);parser.add_argument('--authorized',action='store_true');parser.add_argument('--allow-existing',action='store_true');args=parser.parse_args()
 try:
  if args.action=='probe':result=probe(args.job_id)
  else:
   from greeting_tools import execute
   result=execute('greeting-ui-send',{'plan_id':args.plan_id,'authorized':args.authorized,'max_jobs':args.max_jobs,'allow_existing':args.allow_existing},adapter=HeadlessUIReplyAdapter())
  print(json.dumps({'ok':True,'data':result},ensure_ascii=False))
 except Exception as exc:print(json.dumps({'ok':False,'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__},ensure_ascii=False))

if __name__=='__main__':main()
