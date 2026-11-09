"""Durable bounded recommendation workflow. External effects are never replayed."""
import json,os,time,uuid,threading
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from discovery import classify_job,policy_metadata
from resume_tailoring_tools import source_version
from observability import span

# 小队 Agent 自动推进的定时任务间隔（秒）：默认 10 分钟，可用环境变量覆盖
TICK_SECONDS=max(60,int(os.environ.get('CAREER_SQUAD_TICK_SECONDS','600')))

NODES=['collect','read_jd','match','greet','tailor','wait_reply','review','deliver']
LABELS={'collect':'采集推荐','read_jd':'读取JD','match':'匹配分析','greet':'打招呼','tailor':'定制简历','wait_reply':'等待HR回复','review':'等待本人审阅','deliver':'投递核验','excluded':'规则排除','reject':'不匹配','caution':'待核实','done':'投递已记录','blocked':'需要处理','unknown':'结果待核验'}

class BatchPipeline:
 def __init__(self,legacy,root,discovery,tracker,library,model,adapter=None):
  self.legacy=legacy;self.root=Path(root);self.discovery=discovery;self.tracker=tracker;self.library=library;self.model=model
  self.adapter=adapter or PipelineTools(self);self.lock=threading.RLock();self.active=set();self.agent_workers=set();self.worker_context=threading.local();self.job_locks={};self.wake=threading.Event();self.thread=None
  from career_agents import AgentRuntime
  self.agents=AgentRuntime(legacy.db)
  # Recover side effects conservatively. Read/model nodes may be resumed.
  for r in self.records():
   if r.get('runtime')!=3:continue
   r=legacy.get(r['id'])
   for j in r['jobs']:
    if j.get('inflight') in ('greet','deliver'):
     j.update(node='unknown',reason='服务重启时外部操作未完成回执，禁止重发',inflight=None)
    else:j['inflight']=None
   if r['status'] not in ('cancelled','completed','waiting_connection','paused'):
    for j in r['jobs']:
     if j['node']=='blocked' and j.get('retry_node'):j['node']=j.pop('retry_node')
    r.update(status='scheduled',next_check=0)
   self.save(r)
 def records(self):
  with self.legacy.connect() as c:rows=[json.loads(x[0]) for x in c.execute('SELECT body FROM runs ORDER BY rowid DESC')]
  return [r for r in rows if r.get('runtime')==3]
 def connect(self):return self.legacy.connect()
 def get(self,key):return self.legacy.get(key)
 def save(self,r):
  r['goal']=r.get('context',{}).get('goal') or r.get('goal') or '求职小队';r['progress']=self.progress(r)
  r['pending']=r['progress'];self.legacy.put(r)
 @staticmethod
 def progress(r):
  js=r['jobs'];count=lambda n:sum(j['node']==n for j in js)
  return f"已采集 {len(js)}/{r['target_count']} · 已分析 {sum(bool(j.get('decision')) for j in js)} · 符合 {sum(j.get('decision')=='recommend' for j in js)} · 已招呼 {sum(bool(j.get('greet_at')) for j in js)} · 已定制 {sum(bool(j.get('version_id')) for j in js)} · 待审阅 {count('review')} · 等回复 {count('wait_reply')} · 投递记录 {count('done')} · 待处理 {count('blocked')+count('unknown')}"
 def event(self,r,node,message,job_id=None):
  r['cursor']+=1;r['events'].append({'time':time.time(),'kind':node,'message':message,'job_id':job_id,'step':r['cursor']})
 def create(self,count,authorized,consent,goal='',screening_only=False):
  if type(count)!=int or count<1:raise ValueError('本批岗位数量须为至少1岗')
  if authorized is not True and not screening_only:raise ValueError('需明确授权本批匹配通过岗位打招呼及回复后投递；不自动审阅简历')
  if consent is not True:raise ValueError('请先同意将真实简历和JD交给模型分析')
  original=source_version(self.library)
  if not original:raise ValueError('请先导入真实原始Word简历')
  profile=json.loads((self.root/'data/workspace.json').read_text())
  if not profile.get('preferences'):raise ValueError('请先设置求职条件')
  with self.lock:
   if not screening_only and any(r.get('runtime')==3 and r['status'] not in ('completed','cancelled') for r in self.records()):raise ValueError('已有推荐跟进任务，请先查看、继续或取消，避免重复联系')
   if screening_only:goal=goal or f'BOSS综合推荐{count}岗只读筛选'
   r={'id':uuid.uuid4().hex,'runtime':3,'mode':'recommended_batch','status':'scheduled','target_count':count,'authorized':authorized is True,'screening_only':bool(screening_only),'consent':True,'cursor':0,'plan':NODES,'context':{'goal':goal or f'BOSS推荐{count}岗筛选与回复后投递','preferences':profile['preferences'],'source_resume_id':original['id'],'source_sha256':original['sha256']},'jobs':[],'events':[],'results':{},'artifact':None,'page':1,'collection_done':False,'next_check':0,'created':time.time(),'concurrency':{'read':1,'match':3,'browser':1,'tailor':1},'poll_seconds':TICK_SECONDS}
   self.event(r,'created','已保存有限批次授权；先招呼再定制，回复后仅投最新且已审阅版本');self.save(r)
  self.start_scheduler();self.wake.set();return r['id']
 def start_scheduler(self):
  with self.lock:
   if self.thread and self.thread.is_alive():return
   self.thread=threading.Thread(target=self.loop,daemon=True,name='career-batch-scheduler');self.thread.start()
 def loop(self):
  # 定时任务主循环：每 10 分钟推进一步小队 Agent；任何异常都不退出线程
  while True:
   try:
    self.pass_once()
    self.write_state()
   except Exception as exc:
    try:self.write_state(error=str(exc)[:500])
    except Exception:pass
   self.wake.wait(5);self.wake.clear()
 def pass_once(self):
  for r in self.records():
   if r.get('runtime')==3 and r['status'] in ('scheduled','monitoring') and r.get('next_check',0)<=time.time():self.tick(r['id'])
  for r in self.records():self.agents.report(r['id'])
 def write_state(self,error=None):
  now=time.time()
  if error is None and now-getattr(self,'_state_ts',0)<30:return
  path=self.root/'data/scheduler-state.json'
  try:prev=json.loads(path.read_text()) if path.exists() else {}
  except Exception:prev={}
  active=[{'id':r['id'],'status':r['status'],'next_check':r.get('next_check',0),'next_check_at':time.strftime('%Y-%m-%d %H:%M:%S',time.localtime(r.get('next_check',0))) if r.get('next_check') else ''} for r in self.records() if r.get('runtime')==3 and r['status'] in ('scheduled','monitoring','running')]
  body={'interval_seconds':TICK_SECONDS,'passes':int(prev.get('passes',0))+(1 if error is None else 0),'last_pass_at':(now if error is None else prev.get('last_pass_at')),'last_error':error or '','active_squads':active,'scheduler_alive':True,'updated':now}
  try:path.write_text(json.dumps(body,ensure_ascii=False))
  except Exception:pass
  self._state_ts=now
 def jd_cooldown(self):
  path=self.root/'data/jd-cooldown.json'
  try:
   if path.exists():
    data=json.loads(path.read_text())
    if data.get('until',0)>time.time():return data
  except Exception:pass
  return None
 def control(self,key,action):
  with self.lock:
   r=self.get(key)
   if action in ('cancel','pause'):
    r['status']='cancelled' if action=='cancel' else 'paused'
   elif action=='resume':
    if r['status'] in ('cancelled','completed'):raise ValueError('终态任务不能重新执行')
    for job in r['jobs']:
     if job['node']=='blocked' and job.get('retry_node') in ('read_jd','match','tailor'):
      job['node']=job.pop('retry_node')
    r.pop('error',None)
    r.update(status='scheduled',next_check=0)
   else:raise ValueError('无效任务操作')
   self.event(r,action,'任务'+action+'；已开始的工具结束后保留回执，不再推进下一节点');self.save(r)
  self.start_scheduler();self.wake.set()
 def live(self,key):return self.get(key)['status']=='running' or getattr(self.worker_context,'batch',None)==key and self.get(key)['status']!='cancelled'
 def patch_job(self,key,jid,**fields):
  with self.lock:
   r=self.get(key);j=next(j for j in r['jobs'] if j['job_id']==jid);j.update(fields)
   self.event(r,fields.get('node',j['node']),j.get('company','')+' · '+LABELS.get(j['node'],j['node'])+('：'+fields['reason'] if fields.get('reason') else ''),jid);self.save(r)
   batch=r['id'];snapshot=dict(j)
  self.sync_ledger(batch,snapshot,fields)
 def sync_ledger(self,batch,job,fields):
  """Push squad progress into the job ledger the 岗位管理 view reads."""
  disco=getattr(self,'discovery',None)
  if disco is None or not hasattr(disco,'update_job'):return
  patch={'node':job.get('node'),'batch_id':batch}
  if job.get('decision') in ('recommend','caution','reject'):
   patch['squad_decision']=job['decision']
   if job.get('match'):patch['squad_match']=job['match']
  if 'reason' in fields:patch['reason']=fields.get('reason') or ''
  elif job.get('node') in ('tailor','wait_reply','review','done'):patch['reason']=''
  for k in ('greet_at','version_id','delivery','recruiter_id'):
   if job.get(k):patch[k]=job[k]
  try:disco.update_job(job.get('job_id'),patch)
  except Exception:pass
 def retry_call(self,key,j,node,fn):
  from retry_policy import retry
  def record(attempt,delay):
   with self.lock:
    r=self.get(key);self.event(r,'retry',node+f' 第{attempt}次失败，{delay}秒后重试（最多3次调用）',j['job_id']);self.save(r)
  return retry(fn,record,lambda:self.live(key))
 def invoke(self,key,j,node,fn):
  if not self.live(key):return None
  self.patch_job(key,j['job_id'],inflight=node)
  try:
   with span('batch.'+node,'tool',input={'batch_id':key,'job_id':j['job_id']}):return self.agents.execute(key,j['job_id'],node,fn)
  finally:self.patch_job(key,j['job_id'],inflight=None)
 def tick(self,key):
  with self.lock:
   if key in self.active:return
   r=self.get(key)
   if r['status'] not in ('scheduled','monitoring'):return
   self.active.add(key);r['status']='running';self.save(r)
  try:
   self.collect(key)
   if not self.live(key):return
   original=self.library.get(self.get(key)['context']['source_resume_id'])
   if source_version(self.library)['id']!=original['id'] or original['sha256']!=self.get(key)['context']['source_sha256']:raise ValueError('原始简历版本指纹变化，请重新建立任务')
   # Read operations remain serial, model work runs in bounded groups of five.
   for j in self.get(key)['jobs']:
    if not self.live(key):return
    if j['node']!='read_jd':continue
    try:
     data=self.invoke(key,j,'read_jd',lambda:self.retry_call(key,j,'read_jd',lambda:self.adapter.detail(j)))
     if data is None:return
     if data.get('job_id')!=j['job_id'] or not data.get('description'):raise ValueError('JD岗位或正文校验失败')
     j.update(policy_metadata(data));j.update(jd=data['description'],recruiter=data.get('recruiter') or j.get('recruiter',''),salary=data.get('salary') or j.get('salary',''))
     eligibility,reason=classify_job(j)
     j.update(node='excluded' if eligibility=='excluded' else 'match',reason=reason)
     self.persist_job(j);self.patch_job(key,j['job_id'],**{k:v for k,v in j.items() if k!='job_id'})
    except Exception as exc:
     # A single failed detail must not discard the rest of the batch.
     if any(token in str(exc) for token in ('AUTH_REQUIRED','SECURITY_VERIFICATION_REQUIRED','验证码','访问受限','操作过于频繁')):
      raise ValueError('详情连接需要处理：'+str(exc)) from exc
     self.patch_job(key,j['job_id'],node='blocked',retry_node='read_jd',reason='JD读取失败，已跳过并继续其他岗位：'+str(exc))
   pending=[j for j in self.get(key)['jobs'] if j['node']=='match']
   for offset in range(0,len(pending),5):
    if not self.live(key):return
    with ThreadPoolExecutor(max_workers=3) as pool:
     futures={pool.submit(self.match,key,j,original):j for j in pending[offset:offset+5]}
     for f in as_completed(futures):
      j=futures[f]
      try:f.result()
      except Exception as exc:self.patch_job(key,j['job_id'],node='blocked',reason='分析失败：'+type(exc).__name__)
   for j in self.get(key)['jobs']:
    if not self.live(key):return
    if j['node']=='greet':self.greet(key,j,original)
    j=next(x for x in self.get(key)['jobs'] if x['job_id']==j['job_id'])
    if not self.live(key):return
    if j['node']=='tailor':self.tailor(key,j)
    if self.live(key) and self.get(key).get('next_reply_check',0)<=time.time():self.poll_replies(key)
   if not self.live(key):return
   self.poll_replies(key)
   with self.lock:
    r=self.get(key)
    if r['status']=='running':
     terminal={'excluded','reject','caution','done','screened'}
     r['status']='completed' if r['collection_done'] and all(j['node'] in terminal for j in r['jobs']) else 'monitoring'
     r['next_check']=time.time()+TICK_SECONDS;self.save(r)
  except Exception as exc:
   with self.lock:
    r=self.get(key)
    if r['status']=='running':r['status']='waiting_connection';r['error']=str(exc);self.event(r,'blocked',str(exc));self.save(r)
  finally:
   with self.lock:self.active.discard(key)
 def screen_existing(self,key,count):
  if type(count)!=int or count<1:raise ValueError('数量须为至少1岗')
  r=self.get(key)
  if r.get('runtime')!=3 or r.get('screening_only'):raise ValueError('请选择真实的小队')
  with self.lock,self.connect() as c:
   c.execute('CREATE TABLE IF NOT EXISTS squad_work_requests(id TEXT PRIMARY KEY,squad_id TEXT,body TEXT)')
   for raw, in c.execute('SELECT body FROM squad_work_requests WHERE squad_id=?',(key,)):
    existing=json.loads(raw)
    if existing['status'] in ('queued','running'):return existing
   request={'id':uuid.uuid4().hex,'squad_id':key,'agent':'collect+match','target_count':count,'status':'queued','created':time.time(),'source':'BOSS综合推荐','scope':'read_only'}
   c.execute('INSERT INTO squad_work_requests VALUES(?,?,?)',(request['id'],key,json.dumps(request,ensure_ascii=False)))
  def save():
   with self.connect() as c:c.execute('UPDATE squad_work_requests SET body=? WHERE id=?',(json.dumps(request,ensure_ascii=False),request['id']))
  def work():
   request['status']='running';save()
   try:
    if self.get(key)['target_count']<count:
     with self.lock:
      latest=self.get(key);latest.update(target_count=count,collection_done=False);self.save(latest)
    for agent in ('collect','match'):
     self.start_agent(key,agent,False,limit=count)
     while (key,agent) in self.agent_workers:time.sleep(1)
     if self.get(key)['status']=='cancelled':raise ValueError('小队已取消')
    current=self.get(key)['jobs'][:count]
    request.update(status='completed' if all(j.get('decision') or j['node']=='excluded' for j in current) else 'partial',collected=len(current),analyzed=sum(bool(j.get('decision')) for j in current))
   except Exception as exc:request.update(status='failed',error=str(exc)[:700])
   request['finished']=time.time();save()
  threading.Thread(target=work,daemon=True).start()
  return request
 def work_requests(self,key):
  with self.connect() as c:
   c.execute('CREATE TABLE IF NOT EXISTS squad_work_requests(id TEXT PRIMARY KEY,squad_id TEXT,body TEXT)')
   return [json.loads(r[0]) for r in c.execute('SELECT body FROM squad_work_requests WHERE squad_id=? ORDER BY rowid DESC',(key,))]
 def start_agent(self,key,agent,authorized=False,limit=None):
  from career_agents import AGENTS
  if agent not in AGENTS:raise ValueError('未知Agent')
  if agent=='greet' and (self.root/'data/ui-chat/security-blocked.json').exists():raise ValueError('平台验证暂停尚未解除，本次未发送，也未生成新话术；请先人工完成验证。')
  if agent in ('greet','deliver') and authorized is not True:raise ValueError('需要明确发送授权')
  with self.lock:
   r=self.get(key)
   if r.get('runtime')!=3:raise ValueError('这是旧版任务，不支持独立Agent。请打开BOSS推荐100岗小队，或新建小队。')
   if r['status']=='cancelled':raise ValueError('小队已取消')
   token=(key,agent)
   if token in self.agent_workers:return {'id':key,'status':'already_running','note':'该Agent已运行，不重复启动'}
   self.agent_workers.add(token)
   self.event(r,'agent_started',agent+' 已独立启动，自动领取可处理岗位');self.save(r)
  def work():
   self.worker_context.batch=key
   try:
    if agent=='collect' and not self.get(key)['collection_done']:self.collect(key)
    reads=0
    self._reply_batch=None
    for snapshot in self.get(key)['jobs'][:limit]:
     if agent=='greet' and (self.root/'data/ui-chat/security-blocked.json').exists():break
     if self.get(key)['status']=='cancelled':break
     jid=snapshot['job_id']
     with self.lock:lock=self.job_locks.setdefault((key,jid),threading.Lock())
     if not lock.acquire(blocking=False):continue
     try:
      j=next(x for x in self.get(key)['jobs'] if x['job_id']==jid)
      if j.get('inflight'):continue
      if agent=='collect' and reads>=3:break
      if agent=='collect' and self.jd_cooldown():break
      if agent=='collect' and not j.get('jd') and j['node']!='excluded':
       d=self.invoke(key,j,'read_jd',lambda:self.retry_call(key,j,'read_jd',lambda:self.adapter.detail(j)))
       if not d or d.get('job_id')!=jid or not d.get('description'):raise ValueError('岗位JD校验失败')
       j.update(policy_metadata(d));j.update(jd=d['description'],recruiter=d.get('recruiter') or j.get('recruiter',''))
       self.persist_job(j);self.patch_job(key,jid,jd=j['jd'],recruiter=j['recruiter'],node='match')
       reads+=1
      elif agent=='match' and j.get('jd') and not j.get('decision'):self.match(key,j,self.library.get(r['context']['source_resume_id']))
      elif agent=='greet' and j.get('decision')=='recommend' and not j.get('greet_at') and j['node']!='unknown':self.greet(key,j,self.library.get(r['context']['source_resume_id']))
      elif agent=='tailor' and j.get('jd') and j.get('decision')=='recommend' and not j.get('version_id'):self.tailor(key,j)
      elif agent=='deliver' and j.get('version_id') and j['node']!='unknown':self.try_delivery(key,j,require_reply=False)
      elif agent in ('followup','interview'):
       cached=getattr(self,'_reply_batch',None)
       if cached is None:
        cached=self.agents.execute(key,'','followup',lambda:self.adapter.replies(key,self.get(key)['jobs'])) or {}
        self._reply_batch=cached
       replies=cached
       reply=replies.get(jid)
       if reply:
        payload={k:v for k,v in reply.items() if k!='uid'}
        patch={'reply':payload}
        if reply.get('uid') and not j.get('recruiter_id'):patch['recruiter_id']=reply['uid']
        self.patch_job(key,jid,**patch);self.record_interview(key,j,reply)
        if agent=='followup':self.followup_deliver(key,jid)
     except Exception as exc:
      if '业务码 37' in str(exc):
       (self.root/'data/jd-cooldown.json').write_text(json.dumps({'until':time.time()+180,'reason':'JD接口限流37，稍后继续'},ensure_ascii=False))
       if agent=='collect':self.patch_job(key,jid,node='blocked',retry_node='read_jd',reason='JD读取被限流（37），已暂停本批')
       break
      if agent=='collect':self.patch_job(key,jid,node='blocked',retry_node='read_jd',reason='JD读取失败：'+str(exc)[:700])
      with self.lock:
       latest=self.get(key);self.event(latest,'agent_error',agent+' 单岗失败：'+str(exc)[:700],jid);self.save(latest)
     finally:lock.release()
   except Exception as exc:
    with self.lock:
     latest=self.get(key);self.event(latest,'agent_error',agent+' 失败：'+str(exc)[:700]);self.save(latest)
   finally:
    self.worker_context.batch=None
    with self.lock:
     self.agent_workers.discard(token);latest=self.get(key);self.event(latest,'agent_finished',agent+' 本轮执行结束；结果已保存');self.save(latest)
    self.agents.report(key)
  threading.Thread(target=work,daemon=True,name='agent-'+agent).start()
  return {'id':key,'agent':agent,'status':'running','note':'Agent已独立启动，自动领取当前可处理岗位；无条件的岗位保持等待'}
 def run_agent(self,key,agent,job_id,authorized=False):
  from career_agents import AGENTS,interview_signal
  if agent not in AGENTS:raise ValueError('未知业务Agent')
  with self.lock:
   r=self.get(key)
   if key in self.active or r['status'] in ('running','scheduled'):raise ValueError('主任务正在执行，请先暂停并等待当前工具结束')
   if r['status'] in ('cancelled','completed'):raise ValueError('终态任务不能执行新的子任务')
   job=next((j for j in r['jobs'] if j['job_id']==job_id),None)
   if (agent!='collect' or job_id) and not job:raise ValueError('请选择本批真实岗位ID')
   if agent in ('greet','deliver') and authorized is not True:raise ValueError('发送Agent需要明确授权')
   prerequisites={'match':('match',),'greet':('greet',),'tailor':('tailor','wait_reply','review'),'deliver':('wait_reply','review','deliver')}
   if agent in prerequisites and job['node'] not in prerequisites[agent]:raise ValueError('当前岗位未满足该Agent前置条件：'+job['node'])
   if agent=='tailor' and not job.get('greet_at'):raise ValueError('请先完成并核验招呼')
   r['status']='running';self.save(r);self.active.add(key)
  def work():
   try:
    original=self.library.get(r['context']['source_resume_id'])
    if agent=='collect':
     if job:
      data=self.invoke(key,job,'read_jd',lambda:self.retry_call(key,job,'read_jd',lambda:self.adapter.detail(job)))
      if not data or data.get('job_id')!=job_id or not data.get('description'):raise ValueError('JD身份或正文无法核验')
      job.update(policy_metadata(data));job.update(jd=data['description'],recruiter=data.get('recruiter') or job.get('recruiter',''))
      eligible,reason=classify_job(job);job['node']='match' if eligible=='included' else 'excluded'
      self.persist_job(job);self.patch_job(key,job_id,jd=job['jd'],node=job['node'],reason=reason)
     else:self.collect(key)
    elif agent=='match':self.match(key,job,original)
    elif agent=='greet':self.greet(key,job,original)
    elif agent=='tailor':self.tailor(key,job)
    elif agent=='deliver':self.try_delivery(key,job)
    else:
     replies=self.agents.execute(key,job_id,'followup',lambda:self.adapter.replies(key,[job]))
     reply=replies.get(job_id)
     if reply:
      self.patch_job(key,job_id,reply=reply)
      self.record_interview(key,job,reply)
   except Exception as exc:
    with self.lock:
     latest=self.get(key);latest['error']=str(exc);self.event(latest,'failed','独立Agent执行失败：'+str(exc),job_id);self.save(latest)
   finally:
    with self.lock:
     latest=self.get(key)
     if latest['status']=='running':latest['status']='paused'
     self.save(latest);self.active.discard(key)
  threading.Thread(target=work,daemon=True).start()
  return {'id':key,'agent':agent,'job_id':job_id,'status':'running','note':'仅执行指定Agent，结束后主任务保持暂停；不会自动推进整条流程'}
 def record_interview(self,key,job,reply):
  from career_agents import interview_signal
  signal=interview_signal(reply.get('text'))
  if not signal:return
  def save():
   self.tracker.event(job['job_id'],'interview',signal['status'],'interview:'+str(reply['message_id']),{'source':'network_message','message_id':reply['message_id'],'summary':signal['summary']},reply['at'])
   self.patch_job(key,job['job_id'],interview=signal)
   return signal
  self.agents.execute(key,job['job_id'],'interview',save)
 def poll_replies(self,key):
  waiting=[j for j in self.get(key)['jobs'] if j['node'] in ('wait_reply','review','deliver')]
  replies=self.agents.execute(key,'','followup',lambda:self.adapter.replies(key,waiting)) if waiting else {}
  for j in waiting:
   if not self.live(key):return
   reply=replies.get(j['job_id'])
   if reply:
    self.patch_job(key,j['job_id'],reply=reply)
    self.record_interview(key,j,reply)
    if reply.get('declined'):
     self.patch_job(key,j['job_id'],node='reject',reason='HR明确拒绝，停止投递');continue
   self.try_delivery(key,{**j,'reply':reply or j.get('reply')})
  with self.lock:
   r=self.get(key);r['next_reply_check']=time.time()+TICK_SECONDS;self.save(r)
 def persist_job(self,j):
  with self.discovery.lock,self.discovery.connect() as c:self.discovery._save_job(c,j)
  self.tracker.register(j)
 def collect(self,key):
  while self.live(key):
   r=self.get(key)
   if r['collection_done']:return
   data=self.agents.execute(key,'','collect',lambda:self.adapter.recommend(r['page']))
   if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('推荐接口结构变化')
   with self.lock:
    r=self.get(key)
    if r['status']!='running':return
    ids={j['job_id'] for j in r['jobs']};new=0
    for item in data['items']:
     if item['job_id'] in ids or len(r['jobs'])>=r['target_count']:continue
     ids.add(item['job_id']);new+=1
     j={**item,'platform':'boss','collected_at':str(item.get('collected_at',time.time())),'node':'read_jd','batch_id':key}
     eligibility,reason=classify_job(j)
     if eligibility=='excluded':j.update(node='excluded',reason=reason)
     self.persist_job(j);r['jobs'].append(j)
    r['collection_done']=len(r['jobs'])>=r['target_count'] or not data['items'] or data.get('has_more') is False or new==0
    self.event(r,'collect',f"推荐第{r['page']}页已入库，本批去重后{len(r['jobs'])}岗")
    r['page']+=1;self.save(r)
 def match(self,key,j,original):
  context=self.get(key)['context']
  from matching_policy import assess
  a=self.invoke(key,j,'match',lambda:assess(j,context['preferences']))
  if a is None:return
  j.update(decision=a['decision'],match=a['analysis'],node=('screened' if self.get(key).get('screening_only') else 'greet') if a['decision']=='recommend' else a['decision'])
  self.persist_job(j);self.patch_job(key,j['job_id'],decision=j['decision'],match=j['match'],node=j['node'])
 def greet(self,key,j,original):
  known=next((x for x in self.tracker.listing()['jobs'] if x['job_id']==j['job_id']),{})
  if known.get('greet')=='sent':
   at=known.get('dimension_times',{}).get('greet')
   if not isinstance(at,(int,float)):self.patch_job(key,j['job_id'],node='blocked',reason='已有联系，但缺少可核验时间，避免重复打招呼');return
   self.patch_job(key,j['job_id'],node='tailor',greet_at=at,recruiter_id=known.get('recruiter_id'),recruiter=known.get('recruiter'));return
  try:
   result=self.invoke(key,j,'greet',lambda:self.adapter.greet(j,original))
   if result is None:return
   if not result.get('verified_sent'):
    if result.get('status')=='skipped_existing':
     self.patch_job(key,j['job_id'],node='wait_reply',reason='已有会话，跳过打招呼')
     return
    self.patch_job(key,j['job_id'],node='unknown' if result.get('status')=='unknown' else 'blocked',reason=result.get('reason','招呼未核验'),greeting_receipt=result,retry_node='greet' if result.get('status')!='unknown' else None)
    if (self.root/'data/ui-chat/security-blocked.json').exists():raise ValueError('平台安全验证待处理，已停止后续联系')
    return
   current=next(x for x in self.tracker.listing()['jobs'] if x['job_id']==j['job_id'])
   self.patch_job(key,j['job_id'],node='tailor',greet_at=time.time(),recruiter_id=current.get('recruiter_id'),recruiter=current.get('recruiter'),greeting_receipt=result)
  except Exception as exc:
   if (self.root/'data/ui-chat/security-blocked.json').exists():raise
   self.patch_job(key,j['job_id'],node='unknown',reason='招呼结果待核验：'+str(exc))
 def tailor(self,key,j):
  try:
   versions=[v for v in self.library.load()['versions'] if v.get('kind')=='tailored' and v.get('job',{}).get('job_id')==j['job_id']]
   v=versions[-1] if versions else self.invoke(key,j,'tailor',lambda:self.adapter.tailor(j))
   if v:self.patch_job(key,j['job_id'],node='wait_reply',version_id=v['id'])
  except Exception as exc:self.patch_job(key,j['job_id'],node='blocked',retry_node='tailor',reason='定制失败：'+str(exc))
 def followup_deliver(self,key,jid):
  """HR replied but no resume yet: tailor first, then send the reviewed version."""
  current=next(x for x in self.get(key)['jobs'] if x['job_id']==jid)
  reply=current.get('reply') or {}
  if not reply or reply.get('declined'):return
  if not current.get('jd'):return
  versions=[v for v in self.library.load()['versions'] if v.get('kind')=='tailored' and v.get('job',{}).get('job_id')==jid]
  if not versions:
   self.patch_job(key,jid,node='tailor',reason='HR已回复，先定制简历再发送')
   try:self.tailor(key,current)
   except Exception as exc:self.patch_job(key,jid,node='blocked',reason='定制失败：'+str(exc)[:160])
   return
  self.try_delivery(key,current,require_reply=True)

 def try_delivery(self,key,j,require_reply=True):
  if getattr(self,'draft_busy',lambda _:False)(j['job_id']):
   self.patch_job(key,j['job_id'],node='review',reason='最新简历仍在生成，等待完成及审阅');return
  versions=[v for v in self.library.load()['versions'] if v.get('kind')=='tailored' and v.get('job',{}).get('job_id')==j['job_id']]
  if not versions:self.patch_job(key,j['job_id'],node='blocked',reason='没有岗位定制版本');return
  latest=versions[-1]
  self.patch_job(key,j['job_id'],version_id=latest['id'])
  if require_reply and (not j.get('reply') or j['reply'].get('at',0)<=j.get('greet_at',0)):
   self.patch_job(key,j['job_id'],node='wait_reply');return
  if not latest.get('reviewed') or latest.get('reviewed_sha256')!=latest['sha256']:
   self.patch_job(key,j['job_id'],node='review');return
  # Any previous attachment outcome is a stop, including unknown/pending.
  apps=[a for a in self.library.load()['applications'] if a.get('job',{}).get('job_id')==j['job_id'] and a.get('status') not in ('failed','cancelled')]
  if apps:self.patch_job(key,j['job_id'],node='done' if apps[-1].get('status') in ('sent','waiting_hr') else 'unknown',delivery={'status':'already_recorded','application_id':apps[-1]['id'],'version_id':apps[-1].get('version_id')});return
  try:
   result=self.invoke(key,j,'deliver',lambda:self.adapter.deliver(j,latest['id']))
   if result is not None:self.patch_job(key,j['job_id'],node='done' if result.get('status') in ('sent','waiting_hr','already_recorded') else 'unknown',delivery=result)
  except Exception as exc:self.patch_job(key,j['job_id'],node='blocked',retry_node='deliver',reason='投递停止：'+str(exc))

class PipelineTools:
 def __init__(self,pipeline):self.p=pipeline
 def query(self,name,args):
  result=self.p.discovery.query(name,args)
  if not result.get('ok'):raise ValueError(str((result.get('error') or {}).get('message','BOSS接口不可用')))
  return result['data']
 def recommend(self,page):return self.query('recommend',{'kind':'recommended','page':page})
 _last_jd_at=0
 _param_cache={'at':0,'map':{}}
 def refresh_params(self,job_id):
  """Stale securityId/lid from old collection rounds cause 37/200301; refresh from recommend."""
  now=time.time()
  if now-PipelineTools._param_cache.get('at',0)>600:
   mapping={}
   for page in range(1,7):
    try:
     data=self.query('recommend',{'kind':'recommended','page':page})
    except Exception:
     break
    for it in data.get('items') or []:
     mapping[it['job_id']]=(it.get('security_id'),it.get('lid'))
   PipelineTools._param_cache={'at':now,'map':mapping}
  return PipelineTools._param_cache['map'].get(job_id)

 def detail(self,j):
  # BOSS rate-limits rapid job_detail calls: business code 37 is throttling,
  # not a dead job. Pace the reads and back off before retrying.
  for attempt in range(3):
   gap=2.0-(time.time()-PipelineTools._last_jd_at)
   if gap>0:time.sleep(gap)
   PipelineTools._last_jd_at=time.time()
   try:return self.query('detail',{'job_id':j['job_id'],'security_id':j.get('security_id',''),'lid':j.get('lid','')})
   except Exception as exc:
    text=str(exc)
    if ('业务码 37' in text or '业务码 200301' in text) and attempt<2:
     fresh=self.refresh_params(j['job_id'])
     if fresh and fresh[0]:
      j['security_id'],j['lid']=fresh
      try:self.p.patch_job(j.get('batch_id',''),j['job_id'],security_id=fresh[0],lid=fresh[1])
      except Exception:pass
      continue
    if '业务码 36' in text:
     (self.p.root/'data/jd-cooldown.json').write_text(json.dumps({'until':time.time()+900,'reason':'BOSS 安全验证（业务码36）：岗位详情页被重定向到 verify 页'},ensure_ascii=False))
     raise ValueError('BOSS 要求安全验证（业务码36）：请在专用浏览器窗口完成验证后再点小采')
    if '业务码 37' not in text or attempt==2:raise
    time.sleep(6*(attempt+1))
  raise ValueError('JD读取多次被限流')
 def greet(self,j,original):
  from greeting_tools import Greetings
  from boss_web_greet import WebGreetAdapter
  raw=self.p.retry_call(j['batch_id'],j,'greeting.model',lambda:self.p.model('仅输出JSON：text（20至200字的逐岗定制招呼），evidence（source=jd/resume及逐字quote，二者都必须有）。结合JD核心要求与原始简历真实经历，不编造事实。',{'job':j,'resume':original['text'],'skill':(self.p.root/'skills/boss-jd-greeting/SKILL.md').read_text()}))
  a=json.loads(raw.strip().removeprefix('```json').removesuffix('```').strip())
  followup=bool(j.get('recruiter_id'))
  store=Greetings(self.p.root,WebGreetAdapter(self.p.root,allow_existing=followup))
  plan=store.plan([{'job_id':j['job_id'],'text':a['text'],'evidence':a['evidence']}],original['id'])['plan']
  from resume_delivery import LOCK
  with LOCK:result=store.send(plan['id'],True,1,followup)
  row=result['results'][0]
  saved=store.status(plan['id'])['results']
  receipt=next((x.get('receipt') for x in saved if x['job_id']==j['job_id']),None)
  return receipt or {'verified_sent':False,'status':row['status'],'reason':row.get('reason','招呼未发送或需核验')}
 def tailor(self,j):
  from resume_tailoring import tailor
  v=tailor(self.p.library,lambda *args:self.p.retry_call(j['batch_id'],j,'tailor.model',lambda:self.p.model(*args)),j,source_resume_id=self.p.get(j['batch_id'])['context']['source_resume_id']);self.p.tracker.attach_draft(j['job_id'],v['id']);return v
 def replies(self,key,jobs):
  from chat_opportunities import list_contacts,fetch_history,ChatStore
  if not jobs:return {}
  contacts,self_uid,scope=list_contacts();store=ChatStore(self.p.root)
  store.evidence(key,'batch_reply_scope',scope);out={}
  for j in jobs:
   bound=[c for c in contacts if c.get('encryptJobId')==j['job_id']]
   if j.get('recruiter_id'):bound=[c for c in bound if str(c.get('uid'))==str(j['recruiter_id'])]
   if len(bound)!=1:continue
   messages,complete=fetch_history(bound[0],self_uid,store,key)
   replies=[m for m in messages if m['role']=='company' and m.get('text') and m['at']>j.get('greet_at',time.time())]
   if not replies:continue
   m=max(replies,key=lambda x:x['at']);text=m['text']
   import re
   out[j['job_id']]={'uid':str(bound[0]['uid']),'message_id':m['mid'],'at':m['at'],'declined':bool(re.search(r'不合适|不匹配|暂不考虑|暂停招聘|停止招聘|职位已关闭|岗位已关闭',text)),'text':text}
   self.p.tracker.event(j['job_id'],'reply','replied','batch:'+m['mid'],{'source':'network_message','message_id':m['mid'],'summary':text},m['at'])
  return out
 def deliver(self,j,version):
  # Recheck closure immediately before external sending.
  data=self.detail(j);check={**j,**policy_metadata(data),'jd':data['description'],'salary':data.get('salary') or j.get('salary')}
  if classify_job(check)[0]=='excluded':raise ValueError('投递前岗位已被排除')
  from resume_delivery_workflow import deliver
  from resume_delivery import LOCK
  with LOCK,self.p.library.lock:
   latest=next((v for v in reversed(self.p.library.load()['versions']) if v.get('kind')=='tailored' and v.get('job',{}).get('job_id')==j['job_id']),None)
   if not latest or latest['id']!=version:raise ValueError('投递前最新版本变化，停止并重新核验')
   return deliver(self.p.library,self.p.tracker,j,version,True,self.p.root)

class HarnessWithBatches:
 def __init__(self,legacy,batch):self.legacy=legacy;self.batch=batch
 def __getattr__(self,k):return getattr(self.legacy,k)
 def listing(self):
  rows=[r for r in self.legacy.listing() if not r.get('screening_only')]
  ids={r['id'] for r in rows}
  rows += [{k:v for k,v in r.items() if k!='context'} for r in self.batch.records() if r['id'] not in ids and not r.get('screening_only') and r['status'] not in ('completed','cancelled')]
  for r in rows:
   if r.get('runtime')==3:
    r['agent_running']=[agent for batch,agent in self.batch.agent_workers if batch==r['id']]
    r['agent_tasks']=self.batch.agents.status(r['id'])['tasks']
    r['agent_reports']=self.batch.agents.reports(r['id'])
    r['work_requests']=self.batch.work_requests(r['id'])
    for j in r['jobs']:
     for f in ('security_id','lid'):j.pop(f,None)
  return rows
 def start(self,key,consent=False):
  if self.get(key).get('runtime')==3:return self.batch.control(key,'resume')
  return self.legacy.start(key,consent)
 def cancel(self,key):
  if self.get(key).get('runtime')==3:return self.batch.control(key,'cancel')
  return self.legacy.cancel(key)
 def update(self,key,context):
  if self.get(key).get('runtime')==3:raise ValueError('批次条件已快照固定，调整条件请取消后新建任务')
  return self.legacy.update(key,context)
