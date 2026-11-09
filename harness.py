# -*- coding: utf-8 -*-
from observability import STORE, span, event
from execution_control import TASKS, TaskCancelled
"""Durable, bounded workflow harness. Browser adapter is deliberately unbound."""
import hashlib, json, re, sqlite3, threading, uuid
from datetime import datetime, timezone
from pathlib import Path

TOOLS = [
 {'name':'boss.verify_session','kind':'browser','description':'实时核验BOSS账号入口；等待浏览器适配器'},
 {'name':'profile.validate','kind':'local','description':'检查真实简历和求职条件'},
 {'name':'boss.search_jobs','kind':'browser','description':'按条件搜索真实岗位；等待浏览器适配器'},
 {'name':'boss.read_jd','kind':'browser','description':'读取岗位详情；等待浏览器适配器'},
 {'name':'jd.validate','kind':'local','description':'验证BOSS岗位链接与已录入JD'},
 {'name':'resume.match','kind':'model','description':'按JD逐项生成匹配证据与缺口'},
 {'name':'resume.tailor','kind':'model','description':'依据真实经历生成定制简历'},
 {'name':'artifact.save','kind':'local','description':'保存与岗位关联的Markdown交付物'},
]
PLANS={'boss':['boss.verify_session','profile.validate','boss.search_jobs','boss.read_jd','jd.validate','resume.match','resume.tailor','artifact.save'],
       'jd':['profile.validate','jd.validate','resume.match','resume.tailor','artifact.save']}
class Harness:
 def __init__(self,root,model):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.db=self.root/'runs.sqlite3';self.model=model;self.lock=threading.RLock();self.active=set()
  with self.connect() as c:
   c.execute('CREATE TABLE IF NOT EXISTS runs (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
   for key,body in c.execute('SELECT id,body FROM runs').fetchall():
    r=json.loads(body)
    if r['status']=='running':
     r['status']='interrupted';self.event(r,'interrupted','服务重启；可从最近检查点继续');self.put(r,c)
 def connect(self): return sqlite3.connect(self.db,timeout=10)
 def event(self,r,kind,message): r['events'].append({'time':datetime.now(timezone.utc).isoformat(),'kind':kind,'message':message,'step':r['cursor']})
 def put(self,r,c=None):
  if c is not None: c.execute('INSERT OR REPLACE INTO runs VALUES (?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))
  else:
   with self.connect() as db: self.put(r,db)
 def get(self,key):
  with self.connect() as c: row=c.execute('SELECT body FROM runs WHERE id=?',(key,)).fetchone()
  if not row: raise ValueError('任务不存在')
  return json.loads(row[0])
 def listing(self):
  with self.connect() as c: rows=[json.loads(x[0]) for x in c.execute('SELECT body FROM runs ORDER BY rowid DESC LIMIT 30')]
  return [{k:v for k,v in r.items() if k!='context'} for r in rows]
 def create(self,mode,context,consent=False):
  if mode not in PLANS: raise ValueError('无效任务类型')
  # Only explicitly supplied career fields are persisted; no login credentials.
  context={k:context.get(k,'') for k in ('resume','preferences','jd','jobtitle','joburl')}
  if any(not isinstance(v,str) or len(v)>200000 for v in context.values()): raise ValueError('档案字段必须是限长文本')
  r={'id':uuid.uuid4().hex,'mode':mode,'status':'ready','cursor':0,'plan':PLANS[mode], 'context':context,'consent':bool(consent),'events':[],'results':{},'artifact':None}
  self.event(r,'created','任务已创建；尚未执行');self.put(r);return r['id']
 def start(self,key,consent=False):
  with self.lock:
   r=self.get(key)
   if key in self.active or r['status'] in ('completed','cancelled'): return
   if r['status']=='waiting_browser': raise ValueError('浏览器适配器尚未连接；不能跳过网站核验。可另建“已录入JD”任务。')
   if consent:r['consent']=True
   r['status']='running';self.event(r,'started','从检查点开始执行');self.put(r);self.active.add(key)
   threading.Thread(target=self.execute,args=(key,),daemon=True).start()
 def cancel(self,key):
  with self.lock:
   r=self.get(key)
   if r['status'] in ('completed','cancelled'): return
   r['status']='cancelled';TASKS.cancel('run:'+key);self.event(r,'cancelled','停止请求已发出；模型进程将终止，网页读取结束后不再执行后续步骤');self.put(r)
 def execute(self,key):
  try:
   with TASKS.scope('run:'+key):self._execute_traced(key)
  except TaskCancelled:pass
  finally:
   with self.lock:self.active.discard(key)
 def _execute_traced(self,key):
  try:
   with STORE.trace('Harness 工作流') as trace_id:
    with self.lock:
     r=self.get(key);r['trace_id']=trace_id;self.put(r)
    self._execute(key)
    status=self.get(key)['status'];event('工作流状态：'+status)
    if status=='failed':raise RuntimeError('workflow_failed')
  except RuntimeError:pass
 def _execute(self,key):
  try:
   while True:
    with self.lock:
     r=self.get(key)
     if r['status']!='running': return
     if r['cursor']>=len(r['plan']):
      r['status']='completed';self.event(r,'completed','任务已完成，交付物已保存');self.put(r);return
     tool=r['plan'][r['cursor']];self.event(r,'tool_started',tool);self.put(r)
    if tool.startswith('boss.'):
     with self.lock:
      r=self.get(key)
      if r['status']!='running':return
      r['status']='waiting_browser';self.event(r,'waiting_browser',tool+'：当前服务未绑定浏览器执行通道');self.put(r)
     return
    try:
     with span(tool,'tool',input={'context':r['context'],'results':r['results']}) as observation:
      result=self.call(tool,r)
      if observation is not None:observation['output']=result
    except Exception as exc:
     with self.lock:
      latest=self.get(key)
      if latest['status']!='running':return
      latest['status']='waiting_input' if isinstance(exc,ValueError) else 'failed'
      # Tool errors must be controlled messages, not subprocess stderr/prompt dumps.
      self.event(latest,latest['status'],str(exc) if isinstance(exc,ValueError) else '工具执行失败，请检查模型服务后重试');self.put(latest)
     return
    with self.lock:
     latest=self.get(key)
     if latest['status']!='running': return
     latest['results'][tool]=result;latest['cursor']+=1
     if tool=='artifact.save':latest['artifact']=result
     self.event(latest,'tool_completed',tool);self.put(latest)
  finally:
   pass
 def call(self,tool,r):
  ctx=r['context']
  if tool=='profile.validate':
   if not ctx['resume'].strip() or not ctx['preferences'].strip():raise ValueError('缺少真实简历或求职偏好；请补充档案后更新任务输入')
   return '真实简历与求职偏好已提供'
  if tool=='jd.validate':
   if not re.match(r'^https://www\.zhipin\.com/job_detail/[^/?#]+(?:[?#].*)?$',ctx['joburl']):raise ValueError('请提供BOSS岗位详情链接：https://www.zhipin.com/job_detail/…')
   if not ctx['jd'].strip():raise ValueError('缺少岗位JD原文')
   return {'source':'user_import','url':ctx['joburl'],'sha256':hashlib.sha256(ctx['jd'].encode()).hexdigest(),'note':'用户录入，未声称网站实时采集'}
  if tool in ('resume.match','resume.tailor'):
   if not r['consent']:raise ValueError('等待你同意将本任务简历、求职偏好和JD发送给模型服务')
   instruction='按JD逐项列出真实经历证据、硬条件缺口、待确认信息和申请建议。' if tool=='resume.match' else '输出针对JD的完整定制简历正文，随后列出修改依据和待确认信息；不得编造经历或数字。'
   if tool=='resume.tailor':
    skill=Path(__file__).resolve().parent/'skills/boss-tailor-resume/SKILL.md'
    instruction+='\n以下为定制写法规则，本流程输出文本草稿，不能声称已生成Word：\n'+skill.read_text()
   return self.model(instruction,ctx,r['results'].get('resume.match',''))
  if tool=='artifact.save':
   text='\n\n'.join(['# '+(ctx['jobtitle'] or 'BOSS岗位定制简历'),ctx['joburl'],'来源：用户录入JD；未实时采集网站','## 匹配分析',r['results']['resume.match'],'## 定制简历',r['results']['resume.tailor']])
   p=self.root/(r['id']+'.md');p.write_text(text);p.chmod(0o600);return r['id']+'.md'
  raise ValueError('未注册的工具')
 def update(self,key,context):
  with self.lock:
   r=self.get(key)
   if key in self.active or r['status'] in ('completed','cancelled'):raise ValueError('请等待任务结束或创建新任务')
   for k in r['context']:
    if k in context:
     if not isinstance(context[k],str) or len(context[k])>200000:raise ValueError('档案字段必须是限长文本')
     r['context'][k]=context[k]
   r['cursor']=0;r['results']={};r['artifact']=None;r['status']='ready';self.event(r,'updated','输入已更新；失效的旧结果已清空，重新验证');self.put(r)
