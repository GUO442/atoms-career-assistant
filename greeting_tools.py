"""Evidence-backed greeting plans; remote sends require an explicitly authorized batch.

First-contact custom text has no verified transport. Existing conversations use
PageReplyAdapter and require history receipts; ambiguous sends are not replayed.
"""
import argparse
import hashlib
import json
import sqlite3
import time
import uuid
from pathlib import Path

from runtime_paths import WORKSPACE
from job_management import dashboard
from resume_library import Library
from career_tracking import Tracker

TOOLS = [
 {'name':'greeting-context','description':'读取逐岗JD、原始简历与匹配证据，供撰写定制招呼；不发送','parameters':{'job_ids':'array[string]'}},
 {'name':'greeting-plan','description':'持久保存有限数量的逐岗话术及原文证据，不发送','parameters':{'items':'array[{job_id,text,evidence:[{source,quote}]}]','resume_id':'string'}},
 {'name':'greeting-send','description':'执行明确授权的计划；首次定制招呼通道未验证则停止，已联系默认跳过','parameters':{'plan_id':'string','authorized':'boolean','max_jobs':'integer','allow_existing':'boolean'}},
 {'name':'greeting-status','description':'查看计划、逐岗结果与发送回执','parameters':{'plan_id':'string'}},
 {'name':'greeting-ui-probe','description':'从岗位来源页检查无头UI定位，不输入不发送；安全验证时暂停','parameters':{'job_id':'string'}},
 {'name':'greeting-ui-send','description':'通过无头浏览器UI执行已授权的话术计划，发送与查询分离','parameters':{'plan_id':'string','authorized':'boolean','max_jobs':'integer','allow_existing':'boolean'}},
 {'name':'greeting-ui-resume','description':'用户人工完成平台验证后明确解除本地UI暂停，不自动登录或重试','parameters':{'verification_completed':'boolean'}},
 {'name':'greeting-web-probe','description':'在已登录的常驻Chrome中核对岗位页与沟通入口，不点击不填写不发送','parameters':{'job_id':'string'}},
 {'name':'greeting-web-send','description':'通过常驻Chrome走首次沟通UI并发送定制正文，需本轮明确授权；回执以历史消息为准','parameters':{'plan_id':'string','authorized':'boolean','max_jobs':'integer','allow_existing':'boolean'}},
 {'name':'greeting-recheck','description':'只读复核unknown记录是否实际送达；未送达才重置为可重试','parameters':{'job_ids':'array[string] (optional)','plan_id':'string (optional)'}},
]


def digest(text):return hashlib.sha256(text.encode()).hexdigest()


class Greetings:
 def __init__(self,root=WORKSPACE,adapter=None):
  self.root=Path(root);self.library=Library(self.root/'data/resumes')
  self.folder=self.root/'data/greetings';self.folder.mkdir(parents=True,exist_ok=True);self.folder.chmod(0o700)
  self.path=self.folder/'plans.sqlite3';self.adapter=adapter
  with self.db() as c:c.executescript('CREATE TABLE IF NOT EXISTS plans(id TEXT PRIMARY KEY,body TEXT NOT NULL);CREATE TABLE IF NOT EXISTS sends(job_id TEXT PRIMARY KEY,plan_id TEXT,status TEXT,body TEXT);')
  self.path.chmod(0o600)
 def db(self):return sqlite3.connect(self.path,timeout=15)
 def listing(self):
  # Read directly: opening Tracker can mark interrupted dispatch actions unknown.
  tracking={'jobs':[]};path=self.root/'data/tracking/tracking.sqlite3'
  if path.exists():
   with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as c:tracking['jobs']=[json.loads(r[0]) for r in c.execute('SELECT data FROM jobs')]
  history={'jobs':[]};path=self.root/'data/jobs.sqlite3'
  if path.exists():
   with sqlite3.connect('file:'+str(path)+'?mode=ro',uri=True) as c:history['jobs']=[json.loads(r[0]) for r in c.execute('SELECT data FROM jobs')]
  return dashboard(history,tracking,self.library.load())['jobs']
 def context(self,ids):
  if not isinstance(ids,list) or not 1<=len(ids)<=10 or any(not isinstance(i,str) for i in ids) or len(set(ids))!=len(ids):raise ValueError('请明确指定1至10个不同岗位ID')
  jobs={j['job_id']:j for j in self.listing() if j['platform']=='boss'}
  if any(i not in jobs for i in ids):raise ValueError('包含未入库的BOSS岗位')
  originals=[{k:v.get(k) for k in ('id','name','text','sha256')} for v in self.library.load()['versions'] if v.get('kind')=='original']
  fields=('job_id','title','company','jd','match','screening','eligibility','greet','reply','recruiter','recruiter_id','url')
  return {'jobs':[{k:jobs[i].get(k) for k in fields} for i in ids],'originals':originals,'sent':False,'first_contact_custom_transport':False}
 def plan(self,items,resume_id):
  if not isinstance(items,list) or not items or len(items)>10 or any(not isinstance(x,dict) for x in items):raise ValueError('计划须有1至10个岗位')
  ids=[x.get('job_id') for x in items];context=self.context(ids)
  resume=self.library.get(resume_id)
  if resume.get('kind')!='original':raise ValueError('事实来源必须是原始简历')
  jobs={j['job_id']:j for j in context['jobs']};result=[]
  for item in items:
   j=jobs[item['job_id']];text=item.get('text','');evidence=item.get('evidence',[])
   if not j.get('jd'):raise ValueError('岗位缺少完整JD')
   if j.get('eligibility')=='excluded' or j.get('screening') in ('excluded','reject'):raise ValueError('不符合或规则排除岗位不可进入招呼计划')
   if not isinstance(text,str) or not 20<=len(text.strip())<=200:raise ValueError('招呼须为20至200字的岗位定制文本')
   if not isinstance(evidence,list) or not evidence:raise ValueError('需要JD及原始简历引用证据')
   sources=set()
   for ev in evidence:
    if not isinstance(ev,dict):raise ValueError('证据格式错误')
    source=ev.get('source');quote=ev.get('quote')
    body=j['jd'] if source=='jd' else resume['text'] if source=='resume' else ''
    if not isinstance(quote,str) or not quote.strip() or quote not in body:raise ValueError('引用必须逐字来自该岗位JD或原始简历')
    sources.add(source)
   if sources!={'jd','resume'}:raise ValueError('必须同时包含JD与简历证据')
   result.append({'job_id':j['job_id'],'company':j.get('company'),'title':j.get('title'),'screening':j.get('screening'),'recruiter_id':j.get('recruiter_id'),'text':text.strip(),'evidence':evidence,'jd_sha256':digest(j['jd'])})
  record={'id':uuid.uuid4().hex,'created_at':time.time(),'resume_id':resume_id,'resume_sha256':resume['sha256'],'items':result,'note':'证据引用已校验；话术事实一致性仍由调用Skill核对。保存计划不等于发送授权。'}
  with self.db() as c:c.execute('INSERT INTO plans VALUES(?,?)',(record['id'],json.dumps(record,ensure_ascii=False)))
  return {'sent':False,'plan':record}
 def status(self,plan_id):
  with self.db() as c:
   r=c.execute('SELECT body FROM plans WHERE id=?',(plan_id,)).fetchone()
   results=[{'job_id':j,'status':s,**json.loads(b)} for j,s,b in c.execute('SELECT job_id,status,body FROM sends WHERE plan_id=?',(plan_id,))]
  if not r:raise ValueError('计划不存在')
  return {'plan':json.loads(r[0]),'results':results}
 def send(self,plan_id,authorized,max_jobs,allow_existing=False):
  if authorized is not True or type(max_jobs)!=int or not 1<=max_jobs<=10 or type(allow_existing)!=bool:raise ValueError('需要本轮明确发送授权、1至10个岗位上限')
  plan=self.status(plan_id)['plan']
  if max_jobs!=len(plan['items']):raise ValueError('授权数量必须与本计划岗位数一致，请拆分或重新生成计划')
  resume=self.library.get(plan['resume_id']);file=self.library.root/(resume['id']+'.docx')
  if resume['sha256']!=plan['resume_sha256'] or hashlib.sha256(file.read_bytes()).hexdigest()!=plan['resume_sha256']:raise ValueError('原始简历已变化，请重新生成话术计划')
  jobs={j['job_id']:j for j in self.listing() if j['platform']=='boss'};out=[]
  for item in plan['items']:
   key=item['job_id'];job=jobs.get(key)
   if not job or digest(job.get('jd',''))!=item['jd_sha256'] or job.get('screening') in ('reject','excluded'):out.append({'job_id':key,'status':'blocked_changed_job'});break
   if not job.get('recruiter_id') and not getattr(self.adapter,'supports_first_contact',False):
    out.append({'job_id':key,'status':'blocked_first_contact','reason':'首次沟通接口只验证了平台默认问候；定制首句未验证，未发请求'});break
   if job.get('recruiter_id')!=item.get('recruiter_id'):out.append({'job_id':key,'status':'blocked_changed_recruiter'});break
   if job.get('recruiter_id') and not allow_existing:
    out.append({'job_id':key,'status':'skipped_existing','reason':'已有联系人绑定；默认不追加问候，需本轮明确授权跟进'});continue
   if not self.adapter or not getattr(self.adapter,'verified',False) or 'reply_text' not in getattr(self.adapter,'supported_kinds',set()):out.append({'job_id':key,'status':'blocked_transport'});break
   with self.db() as c:
    inserted=c.execute('INSERT OR IGNORE INTO sends VALUES(?,?,?,?)',(key,plan_id,'pending',json.dumps({'text':item['text'],'created_at':time.time()},ensure_ascii=False))).rowcount
   if not inserted:
    with self.db() as c:
     inserted=c.execute('UPDATE sends SET plan_id=?,status=?,body=? WHERE job_id=? AND status=?',(plan_id,'pending',json.dumps({'text':item['text'],'created_at':time.time()},ensure_ascii=False),key,'blocked')).rowcount
   if not inserted:out.append({'job_id':key,'status':'skipped_recorded','reason':'已有发送或结果未知记录；不自动重复'});continue
   status='unknown';detail={'text':item['text'],'created_at':time.time()}
   try:
    receipt=self.adapter({'kind':'reply_text','job_id':key,'recruiter_id':job.get('recruiter_id'),'reply_text':item['text']})
    detail['receipt']=receipt
    if receipt.get('status')=='blocked' and not receipt.get('clicked_send') and not receipt.get('first_contact_attempted'):status='blocked'
    if receipt.get('status')=='skipped_existing':status='skipped_existing'
    if receipt.get('verified_sent') is True and (receipt.get('receipt') or {}).get('message_id'):
     status='sent';tracker=Tracker(self.root/'data/tracking');tracker.event(key,'greet','sent','custom-greeting:'+plan_id+':'+key,{'source':'browser_chat','receipt':receipt.get('receipt'),'summary':item['text']})
   except Exception as exc:
    detail['error_type']=type(exc).__name__
    try:
     from observability import capture
     detail['error']=capture(str(exc))[:700]
    except Exception:
     detail['error']=(type(exc).__name__+': '+str(exc))[:700]
   with self.db() as c:c.execute('UPDATE sends SET status=?,body=? WHERE job_id=?',(status,json.dumps(detail,ensure_ascii=False),key))
   if status=='skipped_existing':
    with self.db() as c:c.execute('DELETE FROM sends WHERE job_id=?',(key,))
   out.append({'job_id':key,'status':status})
   if status!='sent':break
  with self.db() as c:
   plan['last_execution']={'at':time.time(),'results':out};c.execute('UPDATE plans SET body=? WHERE id=?',(json.dumps(plan,ensure_ascii=False),plan_id))
  return {'results':out,'resume_sent':False,'note':'首次定制招呼尚未验证；自定义文本使用已存在浏览器会话SDK，不是独立后台发送。'}
 def recheck(self,job_ids=None,plan_id=None):
  """Read-only: prove whether an earlier unknown send landed; only then unlock."""
  if job_ids is not None and (not isinstance(job_ids,list) or any(not isinstance(i,str) or not i for i in job_ids)):raise ValueError('job_ids须为非空字符串数组')
  if plan_id is not None and not isinstance(plan_id,str):raise ValueError('plan_id须为字符串')
  reader=getattr(self.adapter,'recheck',None)
  if reader is None:raise ValueError('当前适配器不支持复核；请使用常驻Chrome适配器')
  with self.db() as c:rows=[r for r in c.execute("SELECT job_id,plan_id,status,body FROM sends WHERE status IN ('unknown','blocked')")]
  if plan_id is not None:rows=[r for r in rows if r[1]==plan_id]
  if job_ids is not None:rows=[r for r in rows if r[0] in set(job_ids)]
  jobs={j['job_id']:j for j in self.listing() if j['platform']=='boss'};out=[]
  for job_id,pid,status,body in rows:
   d=json.loads(body);job=jobs.get(job_id);text=d.get('text','')
   if not job or not isinstance(text,str) or not text:out.append({'job_id':job_id,'status':'skipped','reason':'岗位或原文本缺失'});continue
   try:verdict=reader(job,text,d.get('created_at',0))
   except Exception as exc:out.append({'job_id':job_id,'status':'skipped','reason':'复核失败：'+type(exc).__name__});continue
   if verdict.get('verified_sent') is True and (verdict.get('receipt') or {}).get('message_id'):
    with self.db() as c:c.execute("UPDATE sends SET status='sent',body=? WHERE job_id=?",(json.dumps({**d,**verdict,'rechecked_at':time.time()},ensure_ascii=False),job_id))
    try:
     Tracker(self.root/'data/tracking').event(job_id,'greet','sent','custom-greeting-recheck:'+job_id,{'source':'browser_chat','receipt':verdict['receipt'],'summary':text})
    except Exception:pass
    out.append({'job_id':job_id,'status':'confirmed_sent','message_id':verdict['receipt']['message_id']})
   else:
    with self.db() as c:c.execute("UPDATE sends SET status='blocked',body=? WHERE job_id=?",(json.dumps({**d,**verdict,'released_at':time.time()},ensure_ascii=False),job_id))
    out.append({'job_id':job_id,'status':'released','reason':verdict.get('reason','未找到送达证据，已重置为可重试')})
  return {'rechecked':len(out),'results':out,'sent':False,'note':'只读复核；确认已送达记 sent，未送达才重置为 blocked'}


def execute(name,args,root=WORKSPACE,adapter=None):
 if not isinstance(args,dict):raise ValueError('参数必须是对象')
 if name=='greeting-ui-probe':
  from boss_ui_chat import probe
  return probe(args.get('job_id'),root)
 if name=='greeting-ui-resume':
  if args.get('verification_completed') is not True:raise ValueError('必须由用户确认已人工完成平台验证')
  gate=Path(root)/'data/ui-chat/security-blocked.json'
  if gate.exists():gate.rename(gate.with_name('security-cleared-'+uuid.uuid4().hex+'.json'))
  return {'resumed':True,'sent':False,'note':'仅解除本地暂停，未证明平台验证通过；下一次操作仍会检查'}
 if name=='greeting-ui-send':
  from boss_ui_chat import HeadlessUIReplyAdapter
  if (Path(root)/'data/ui-chat/security-blocked.json').exists():raise ValueError('平台安全验证尚待人工完成，未启动浏览器或发送')
  adapter=HeadlessUIReplyAdapter(root)
 if name=='greeting-web-probe':
  from boss_web_greet import probe
  return probe(args.get('job_id'),root)
 if name=='greeting-web-send':
  from boss_web_greet import WebGreetAdapter
  if (Path(root)/'data/ui-chat/security-blocked.json').exists():raise ValueError('平台安全验证尚待人工完成，未点击或发送')
  adapter=WebGreetAdapter(root,allow_existing=args.get('allow_existing') is True)
 if name=='greeting-recheck':
  from boss_web_greet import WebGreetAdapter
  return Greetings(root,WebGreetAdapter(root)).recheck(args.get('job_ids'),args.get('plan_id'))
 store=Greetings(root,adapter)
 if name=='greeting-context':return store.context(args.get('job_ids'))
 if name=='greeting-plan':return store.plan(args.get('items'),args.get('resume_id'))
 if name=='greeting-status':return store.status(args.get('plan_id'))
 if name in ('greeting-send','greeting-ui-send','greeting-web-send'):
  import fcntl
  with (store.folder/'send.lock').open('a') as lock:
   try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
   except BlockingIOError:raise ValueError('另一个招呼计划正在执行，请等待完成')
   return store.send(args.get('plan_id'),args.get('authorized'),args.get('max_jobs'),args.get('allow_existing',False))
 raise ValueError('未知招呼工具')


def main():
 parser=argparse.ArgumentParser();parser.add_argument('tool',choices=[t['name'] for t in TOOLS]);parser.add_argument('--stdin',action='store_true');parser.add_argument('--json',default='{}');p=parser.parse_args()
 try:
  import sys
  from boss_reply_tool import PageReplyAdapter
  result={'ok':True,'data':execute(p.tool,json.load(sys.stdin) if p.stdin else json.loads(p.json),adapter=PageReplyAdapter())}
 except Exception as exc:result={'ok':False,'error':str(exc) if isinstance(exc,ValueError) else type(exc).__name__}
 print(json.dumps(result,ensure_ascii=False))

if __name__=='__main__':main()
