"""One-job attachment delivery through observed BOSS UI, with durable deduplication."""
import json,time,threading,uuid
from pathlib import Path
from contextlib import contextmanager
from datetime import datetime,timezone
from urllib.parse import urlsplit
from resume_delivery import LOCK,records,save,version_for,require_review,upload
from resume_tailoring_tools import select_job
from observability import event,span

def already_delivered(library,job_id,version_id):
 return next((a for a in reversed(library.load()['applications']) if a.get('job',{}).get('job_id')==job_id and a.get('version_id')==version_id and a.get('status') not in ('failed','cancelled')),None)

def bind_chat(page,job):
 header=page.locator('.base-info')
 if header.count()!=1:raise ValueError('当前聊天身份无法唯一核验')
 text=header.inner_text()
 name=job.get('recruiter','').split(' · ')[0].strip()
 if not name or name not in text or job['company'] not in text:raise ValueError('聊天公司或招聘者不匹配')
 title=page.locator('.position-name')
 if title.count()!=1 or title.inner_text().strip()!=job['title']:raise ValueError('聊天岗位不匹配')
 return name

@contextmanager
def source_chat(job):
 from patchright.sync_api import sync_playwright
 from boss_ui_chat import challenge
 import boss_web
 with sync_playwright() as p:
  browser=p.chromium.connect_over_cdp(boss_web.DEBUG);context=browser.contexts[0]
  path=urlsplit(job['url']).path
  pages=[x for x in context.pages if urlsplit(x.url).path==path]
  source=pages[0] if pages else context.new_page()
  if not pages:source.goto(job['url'],wait_until='domcontentloaded',timeout=30000)
  source.locator('body').wait_for()
  text=source.locator('body').inner_text()
  if challenge(source.url,text):raise ValueError('平台验证阻塞；停止，不重试')
  name=job.get('recruiter','').split(' · ')[0].strip()
  if not name or not all(x in text for x in (name,job['title'],job['company'])):raise ValueError('岗位来源页身份不匹配或招聘者缺失')
  # Existing-contact path was live verified. Do not silently start another HR conversation.
  links=[x for x in source.get_by_text('继续沟通',exact=True).all() if x.is_visible()]
  if len(links)!=1:raise ValueError('未找到唯一继续沟通入口；新联系人流程需要先核验')
  before=set(context.pages)
  links[0].click()
  deadline=time.monotonic()+20
  while time.monotonic()<deadline:
   for page in context.pages:
    if page is not source and page in before:continue
    if urlsplit(page.url).path!='/web/geek/chat':continue
    try:bind_chat(page,job)
    except ValueError:continue
    if challenge(page.url,page.locator('body').inner_text()):raise ValueError('平台验证阻塞')
    yield page
    return
   time.sleep(.2)
  raise ValueError('未进入岗位对应的HR聊天，停止')

def reopen_chat(page,job):
 page.reload(wait_until='domcontentloaded',timeout=30000)
 name=job['recruiter'].split(' · ')[0].strip()
 contacts=page.locator('.name-box').filter(has=page.get_by_text(name,exact=True)).filter(has=page.get_by_text(job['company'],exact=True))
 contacts.wait_for(timeout=15000)
 if contacts.count()!=1:raise ValueError('回读联系人不唯一')
 contacts.click()
 page.locator('.position-name').wait_for(timeout=15000)
 bind_chat(page,job)

def sync_receipt(library,tracker,job,v,receipt):
 waiting=receipt['status']=='waiting_hr'
 tracker.register(job)
 tracker.event(job['job_id'],'resume','waiting' if waiting else 'sent','delivery-ui:'+receipt['message_id'],
               {'source':'browser_chat','summary':receipt['platform_status'],'message_id':receipt['message_id'],'version_id':v['id'],'evidence':receipt['evidence']})
 with library.lock:
  data=library.load()
  if not any(a.get('message_id')==receipt['message_id'] for a in data['applications']):
   data['applications'].append({'id':'ui-'+receipt['message_id'],'version_id':v['id'],'resume_name':v['name'],'sha256':v['sha256'],'job':v['job'],'status':receipt['status'],'resume_status':'waiting' if waiting else 'sent','created':receipt['created'],'message_id':receipt['message_id'],'note':receipt['platform_status']})
  library.put(data)
  from delivery_store import save_applications
  save_applications(library.root.parent.parent,data['applications'])

def deliver(library,tracker,job,version_id,confirmed=False,root=None):
 root=Path(root)
 with LOCK:
  v=version_for(library,job['job_id'],version_id);require_review(v,confirmed)
  existing=already_delivered(library,job['job_id'],v['id'])
  if existing:return {'status':'already_recorded','application_id':existing['id'],'resume_status':existing.get('resume_status'),'sent_now':False}
  data=records(root)
  prior=next((x for x in data.get('deliveries',[]) if x['job_id']==job['job_id'] and x['version_id']==v['id'] and x['status'] in ('pending','unknown','waiting_hr','sent')),None)
  if prior:return {'status':prior['status'],'reason':'已有发送或待核验记录，不重复发送','sent_now':False}
  with span('attachment.upload · 核验或上传岗位附件','tool'):attached=upload(library,job['job_id'],v['id'],True,root)
  data=records(root)
  receipt={'job_id':job['job_id'],'version_id':v['id'],'remote_id':attached['attachment']['remote_id'],'filename':v['name'],'created':datetime.now(timezone.utc).isoformat(),'status':'pending','transport':'browser_ui'}
  data.setdefault('deliveries',[]).append(receipt);save(root,data)
  folder=root/'data/delivery-evidence'/uuid.uuid4().hex;folder.mkdir(parents=True);clicked=False
  try:
   with source_chat(job) as page:
    bind_chat(page,job)
    # A server-persisted exact attachment card already in this chat is a no-send result.
    card=page.get_by_role('heading',name=v['name'],exact=True)
    if card.count():raise ValueError('聊天已有同名附件；需先核验历史，不重复发送')
    event('正在选择已核验的岗位定制附件')
    page.get_by_text('发简历',exact=True).click()
    dialog=page.locator('.dialog-wrap:visible').filter(has_text='请选择要发送的简历')
    dialog.wait_for(timeout=10000)
    row=dialog.locator('li.list-item').filter(has=page.get_by_text(v['name'],exact=True))
    if row.count()!=1:raise ValueError('目标附件未唯一匹配')
    row.click();button=dialog.get_by_role('button',name='发送',exact=True)
    if not button.is_enabled():raise ValueError('附件发送按钮不可用')
    bind_chat(page,job)
    page.screenshot(path=str(folder/'before-send.png'))
    event('正在发送附件并等待聊天回显')
    clicked=True
    button.click()
    dialog.wait_for(state='hidden',timeout=10000)
    card.wait_for(timeout=15000)
    message_id=card.evaluate('(x)=>x.closest("[data-mid]").getAttribute("data-mid")')
    event('正在刷新聊天核验附件记录')
    reopen_chat(page,job)
    card=page.get_by_role('heading',name=v['name'],exact=True);card.wait_for(timeout=15000)
    if card.count()!=1 or card.evaluate('(x)=>x.closest("[data-mid]").getAttribute("data-mid")')!=message_id:raise ValueError('回读附件消息不一致')
    body=page.locator('body').inner_text()
    waiting='附件简历请求已发送' in body
    if not waiting:raise ValueError('附件卡片存在，但平台状态需人工核验')
    evidence=folder/'verified.png';page.screenshot(path=str(evidence));evidence.chmod(0o600)
    receipt.update(status='waiting_hr',message_id=message_id,platform_status='附件简历请求已发送，等待HR处理，未确认已读',evidence=str(evidence),reloaded=True)
    data=records(root);data['deliveries'][-1]=receipt;save(root,data)
    sync_receipt(library,tracker,job,v,receipt)
    return receipt
  except Exception as exc:
   receipt.update(status='unknown' if clicked else 'blocked',reason=str(exc))
   data=records(root);data['deliveries'][-1]=receipt;save(root,data)
   raise ValueError(('发送结果待核验，不自动重试：' if clicked else '尚未发送：')+str(exc)) from exc

class DeliveryService:
 def __init__(self,library,tracker,root):
  self.library=library;self.tracker=tracker;self.root=Path(root);self.active=set();self.results={};self.lock=threading.RLock()
  from delivery_store import save_applications
  save_applications(self.root,self.library.load()['applications'])
  with LOCK:
   data=records(self.root);changed=False
   for receipt in data.get('deliveries',[]):
    if receipt['status']=='pending':
     receipt.update(status='unknown',reason='服务重启时发送未结束，需回读核验；不自动重试');changed=True
   if changed:save(self.root,data)
 def start(self,jobs,query,version_id='',confirmed=False):
  job=select_job(jobs,query)
  tracked=next((j for j in self.tracker.listing()['jobs'] if j['job_id']==job['job_id']),{})
  job={**job,**{k:tracked[k] for k in ('recruiter','recruiter_id') if tracked.get(k)}}
  v=self.library.get(version_id) if version_id else next((v for v in reversed(self.library.load()['versions']) if v['kind']=='tailored' and v.get('job',{}).get('job_id')==job['job_id']),None)
  if not v:raise ValueError('没有该岗位的定制简历')
  version_for(self.library,job['job_id'],v['id']);require_review(v,confirmed)
  existing=already_delivered(self.library,job['job_id'],v['id'])
  if existing:return {'status':'already_recorded','application_id':existing['id'],'sent_now':False}
  with self.lock:
   if job['job_id'] in self.active:return {'status':'running','job_id':job['job_id']}
   self.active.add(job['job_id'])
   threading.Thread(target=self.work,args=(job,v['id']),daemon=True).start()
  return {'status':'running','job_id':job['job_id'],'version_id':v['id'],'sent_now':False}
 def work(self,job,version_id):
  try:result=deliver(self.library,self.tracker,job,version_id,True,self.root)
  except Exception as exc:result={'status':'blocked_or_unknown','reason':str(exc)}
  with self.lock:self.results[job['job_id']]=result;self.active.discard(job['job_id'])
 def status(self):
  with self.lock:return {'running':sorted(self.active),'results':dict(self.results),'deliveries':records(self.root).get('deliveries',[]),'applications':[{k:a.get(k) for k in ('id','version_id','resume_name','status','resume_status','message_id','receipt_message_id')} for a in self.library.load()['applications'][-30:]]}

def acknowledge_receipt(library,tracker,job_id,recruiter_id,message_id,text,at):
 """Promote a pending request only on a bound, later positive receipt message."""
 import re
 if not re.match(r'^(?:您好[，,。\s]*)?(?:我们)?已收到您的(?:附件)?简历(?:[，,。\s]|$)',text):return False
 job=next((j for j in tracker.listing()['jobs'] if j['job_id']==job_id),None)
 if not job or str(job.get('recruiter_id'))!=str(recruiter_id):return False
 with library.lock:
  data=library.load()
  applications=[a for a in data['applications'] if a.get('job',{}).get('job_id')==job_id and a.get('status')=='waiting_hr']
  if not applications:return False
  app=applications[-1]
  try:created=datetime.fromisoformat(app['created']).timestamp()
  except (KeyError,ValueError):return False
  if at<created:return False
  tracker.event(job_id,'resume','sent','resume-ack:'+str(message_id),{'source':'network_message','message_id':str(message_id),'recruiter_id':str(recruiter_id),'summary':text,'basis':'HR明确回复收到简历'},at)
  app.update(status='sent',resume_status='sent',receipt_message_id=str(message_id));library.put(data)
  from delivery_store import save_applications
  save_applications(library.root.parent.parent,data['applications'])
 return True
