# -*- coding: utf-8 -*-
"""Evidence-based job tracking and durable, deduplicated automation outbox."""
import hashlib,json,re,sqlite3,threading,time,uuid
from pathlib import Path
STATES={'greet':{'not_sent','pending','sent','failed','unknown'},'reply':{'unknown','no_reply','replied'},'resume':{'not_sent','waiting','pending','sent','failed','unknown'},'interview':{'none','invited','scheduled','completed','cancelled'},'outcome':{'open','rejected','offer','accepted','closed'}}
LABELS={'greet':{'not_sent':'未打招呼','pending':'打招呼中','sent':'已打招呼','failed':'打招呼失败','unknown':'打招呼结果待核验'},'reply':{'unknown':'回复状态未知','no_reply':'未回复','replied':'已回复'},'resume':{'not_sent':'未投递','waiting':'待发简历','pending':'投递中','sent':'已投递','failed':'投递失败','unknown':'投递结果待核验'},'interview':{'none':'未约面试','invited':'收到面试邀请','scheduled':'已约面试／未面试','completed':'已面试','cancelled':'面试取消'},'outcome':{'open':'跟进中','rejected':'已拒绝','offer':'收到Offer','accepted':'已接受Offer','closed':'已结束'}}
class Tracker:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.root.chmod(0o700);self.path=self.root/'tracking.sqlite3';self.lock=threading.RLock()
  with self.connect() as c:c.executescript('CREATE TABLE IF NOT EXISTS jobs(id TEXT PRIMARY KEY,data TEXT NOT NULL);CREATE TABLE IF NOT EXISTS events(id TEXT PRIMARY KEY,job_id TEXT,data TEXT NOT NULL);CREATE TABLE IF NOT EXISTS actions(id TEXT PRIMARY KEY,job_id TEXT,kind TEXT,trigger_id TEXT,status TEXT,data TEXT,UNIQUE(job_id,kind,trigger_id));CREATE TABLE IF NOT EXISTS settings(id TEXT PRIMARY KEY,data TEXT);')
  with self.connect() as c:c.execute('UPDATE actions SET status="unknown" WHERE status="running"')
  self.path.chmod(0o600)
 def connect(self):return sqlite3.connect(self.path,timeout=15)
 def _put(self,c,j):c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?)',(j['job_id'],json.dumps(j,ensure_ascii=False)))
 def register(self,job):
  key=job.get('job_id') or job.get('job_key')
  if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',key):raise ValueError('岗位ID无效')
  with self.lock,self.connect() as c:
   row=c.execute('SELECT data FROM jobs WHERE id=?',(key,)).fetchone()
   j=json.loads(row[0]) if row else {'job_id':key,'greet':'not_sent','reply':'unknown','resume':'not_sent','interview':'none','outcome':'open','created_at':time.time(),'dimension_times':{}}
   for k in ('title','company','city','url','recruiter','recruiter_id','jd'):
    if isinstance(job.get(k),str) and job[k]:j[k]=job[k]
   j['updated_at']=time.time();self._put(c,j);return j
 def event(self,job_id,kind,value,event_id,evidence,at=None):
  if kind not in STATES or value not in STATES[kind]:raise ValueError('状态无效')
  if not isinstance(evidence,dict) or evidence.get('source') not in ('browser_chat','network_message','manual','legacy_record'):raise ValueError('状态更新需要明确证据来源')
  at=time.time() if at is None else at
  if not isinstance(at,(int,float)) or at<0 or at>time.time()+300:raise ValueError('证据时间无效')
  if not isinstance(event_id,str) or not event_id:raise ValueError('事件ID缺失')
  with self.lock,self.connect() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
   if not row:raise ValueError('岗位未登记')
   if c.execute('SELECT 1 FROM events WHERE id=?',(event_id,)).fetchone():return False
   j=json.loads(row[0]);record={'kind':kind,'value':value,'at':at,'evidence':evidence}
   c.execute('INSERT INTO events VALUES(?,?,?)',(event_id,job_id,json.dumps(record,ensure_ascii=False)))
   if at>=j['dimension_times'].get(kind,0):
    # Passive observations cannot undo a confirmed send/completed interview.
    regress=(kind=='resume' and j[kind]=='sent' and value in ('not_sent','waiting')) or (kind=='interview' and j[kind]=='completed' and value in ('none','invited','scheduled'))
    if not regress or evidence['source']=='manual':
     j[kind]=value;j['dimension_times'][kind]=at;j['updated_at']=time.time();j['last_evidence']=record
     if kind=='greet' and value=='sent' and j['reply']=='unknown':j['reply']='no_reply'
     self._put(c,j)
   return True
 def policy(self):
  with self.connect() as c:r=c.execute('SELECT data FROM settings WHERE id="policy"').fetchone()
  return json.loads(r[0]) if r else {'enabled':False,'reply_mode':'resume_requests','resume_id':'','resume_mode':'tailored_review','allowed_jobs':[],'activated_at':None}
 def configure(self,policy,library):
  if not isinstance(policy,dict) or set(policy)-{'enabled','reply_mode','resume_id','resume_mode','allowed_jobs'}:raise ValueError('自动化配置参数无效')
  p={**self.policy(),**policy}
  if type(p['enabled'])!=bool or p['reply_mode'] not in ('resume_requests','greetings') or not isinstance(p['allowed_jobs'],list) or not all(isinstance(j,str) for j in p['allowed_jobs']):raise ValueError('自动化范围无效')
  if p['enabled']:
   if not p['allowed_jobs']:raise ValueError('请指定自动处理的岗位范围')
   known={j['job_id'] for j in self.listing()['jobs']}
   if not set(p['allowed_jobs'])<=known:raise ValueError('自动化岗位不在跟进列表中')
   if p.get('resume_mode')!='tailored_review':raise ValueError('简历须逐岗定制并审阅后发送')
  if p['enabled'] and not self.policy().get('enabled'):p['activated_at']=time.time()
  with self.lock,self.connect() as c:c.execute('INSERT OR REPLACE INTO settings VALUES("policy",?)',(json.dumps(p),))
  return p
 def incoming(self,job_id,recruiter_id,message_id,text,at):
  with self.connect() as c:r=c.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
  if not r: return False
  j=json.loads(r[0])
  if not recruiter_id or j.get('recruiter_id')!=str(recruiter_id):return False
  eid='incoming:'+job_id+':'+str(message_id)
  fresh=self.event(job_id,'reply','replied',eid,{'source':'network_message','message_id':str(message_id),'recruiter_id':str(recruiter_id),'summary':text[:1000]},at)
  if not fresh:return False
  p=self.policy();kind=None
  resume_request=bool(re.search(r'(发|提供|投递|给|传).{0,12}简历|简历.{0,8}(发|给|提供)',text))
  special=bool(re.search(r'面试|薪资|工资|期望|到岗|入职|身份证|银行卡|验证码|转账',text))
  if re.search(r'邀请.{0,8}面试|安排.{0,8}面试|面试邀请',text):self.event(job_id,'interview','invited',eid+':interview',{'source':'network_message','message_id':str(message_id),'summary':text[:1000]},at)
  if special:kind='notify'
  elif resume_request:
   if j.get('resume')!='sent':self.event(job_id,'resume','waiting',eid+':resume',{'source':'network_message','message_id':str(message_id)},at)
   kind='tailor_resume' if j.get('resume')!='sent' else 'notify'
  elif p['reply_mode']=='greetings' and (re.fullmatch(r'[你好您好哈喽helloHi嗨早上下午晚上好呀啊！!，,。 .?？～~]+',text,re.I) or re.fullmatch(r'(?:\[hi\]\s*)?(?:你好|您好|哈喽|hello|hi)[啊呀，,！! ]*(?:可以聊一聊|可以聊聊|可以沟通|方便聊聊|聊一聊|聊聊)[吗么嘛啊呀~～！!。?？ ]*',text,re.I)):kind='reply_text'
  else:kind='notify'
  allowed=p['enabled'] and job_id in p['allowed_jobs'] and at>=(p.get('activated_at') or float('inf'))
  status='queued' if allowed and kind!='notify' else 'needs_attention'
  payload={'trigger_time':at,'text':text[:1000],'resume_id':p.get('resume_id'),'resume_sha256':p.get('resume_sha256'),'reply_text':'您好，感谢联系。我正在关注这个岗位，可以进一步沟通。' if kind=='reply_text' else '您好，这是我的简历，请查收。','reason':'需人工处理或自动化范围尚未配置' if status=='needs_attention' else ''}
  with self.lock,self.connect() as c:c.execute('INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,job_id,kind,eid,status,json.dumps(payload,ensure_ascii=False)))
  return True
 def attach_draft(self,job_id,version_id):
  with self.lock,self.connect() as c:
   row=c.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
   if not row:raise ValueError('岗位未登记')
   j=json.loads(row[0]);j['draft_resume_id']=version_id;j['review_status']='pending_review';j['updated_at']=time.time();self._put(c,j)
   c.execute('UPDATE actions SET status="awaiting_review" WHERE job_id=? AND kind="tailor_resume" AND status IN ("needs_attention","queued","drafting")',(job_id,))
 def approve_draft(self,job_id,version_id,library):
  v=library.get(version_id)
  if not v.get('reviewed') or v.get('reviewed_sha256')!=v['sha256']:raise ValueError('请先审阅指定简历版本')
  with self.lock,self.connect() as c:
   row=c.execute('SELECT data FROM jobs WHERE id=?',(job_id,)).fetchone()
   if not row:raise ValueError('岗位未登记')
   j=json.loads(row[0])
   if j.get('draft_resume_id')!=version_id or v.get('kind')!='tailored' or v.get('job',{}).get('url')!=j.get('url'):raise ValueError('简历与岗位不对应')
   fingerprint=hashlib.sha256((library.root/(version_id+'.docx')).read_bytes()).hexdigest()
   if fingerprint!=v['sha256']:raise ValueError('文件指纹与已审阅版本不同，请重新导入并审阅')
   j.update(review_status='approved',updated_at=time.time());self._put(c,j)
   action={'resume_id':version_id,'resume_sha256':fingerprint,'reply_text':'您好，这是我针对该岗位整理的简历，请查收。'}
   c.execute('INSERT OR IGNORE INTO actions VALUES(?,?,?,?,?,?)',(uuid.uuid4().hex,job_id,'send_resume','approved:'+version_id,'queued',json.dumps(action,ensure_ascii=False)))
  return j
 def history(self,job_id):
  with self.connect() as c:return [json.loads(r[0]) for r in c.execute('SELECT data FROM events WHERE job_id=? ORDER BY rowid DESC LIMIT 100',(job_id,))]
 def listing(self):
  with self.connect() as c:
   jobs=[json.loads(r[0]) for r in c.execute('SELECT data FROM jobs')]
   actions=[{'id':r[0],'job_id':r[1],'kind':r[2],'status':r[3],**json.loads(r[4])} for r in c.execute('SELECT id,job_id,kind,status,data FROM actions ORDER BY rowid DESC LIMIT 100')]
  for j in jobs:j['labels']={k:LABELS[k][j[k]] for k in STATES}
  return {'jobs':sorted(jobs,key=lambda j:j['updated_at'],reverse=True),'actions':actions,'policy':self.policy()}
 def dispatch(self,adapter,library):
  """Claims each action once; an interrupted/uncertain write is never auto-replayed."""
  p=self.policy()
  if not p['enabled']:return
  for action in self.listing()['actions']:
   if action['status']!='queued' or action['kind']=='tailor_resume':continue
   with self.lock,self.connect() as c:
    if c.execute('UPDATE actions SET status="running" WHERE id=? AND status="queued"',(action['id'],)).rowcount!=1:continue
   state='unknown';error=''
   try:
    if action['kind']=='reply_text' and time.time()-action.get('trigger_time',time.time())>300:raise ValueError('问候已超过5分钟，请人工确认是否仍需回复')
    if action['job_id'] not in p['allowed_jobs']:raise ValueError('岗位已移出自动化范围')
    if action['kind']=='send_resume':
     v=library.get(action['resume_id']);path=library.root/(v['id']+'.docx')
     if hashlib.sha256(path.read_bytes()).hexdigest()!=action['resume_sha256']:raise ValueError('简历版本已变化，请重新配置')
    if not adapter or not getattr(adapter,'verified',False) or action['kind'] not in getattr(adapter,'supported_kinds',set()):state='blocked_interface';error='发送接口尚未实抓核验，未执行发送'
    else:
     job=next(j for j in self.listing()['jobs'] if j['job_id']==action['job_id'])
     action['recruiter_id']=job.get('recruiter_id')
     result=adapter(action)
     if result.get('verified_sent') is True:
      state='sent'
      if action['kind']=='send_resume':self.event(action['job_id'],'resume','sent',action['id']+':sent',{'source':'browser_chat','receipt':result.get('receipt')})
     else:error=result.get('reason','未取得聊天发送回显，停止重试')
   except Exception as exc:state='needs_attention';error=str(exc)
   with self.lock,self.connect() as c:
    row=c.execute('SELECT data FROM actions WHERE id=?',(action['id'],)).fetchone();payload=json.loads(row[0]);payload['error']=error;c.execute('UPDATE actions SET status=?,data=? WHERE id=?',(state,json.dumps(payload,ensure_ascii=False),action['id']))
 def import_existing(self,discovery,records):
  for j in discovery.get('jobs',[]):self.register(j)
  for path in Path(records).glob('*.json'):
   try:
    r=json.loads(path.read_text());j=self.register(r)
    if r.get('greet_status')=='sent':self.event(j['job_id'],'greet','sent','legacy:'+j['job_id'],{'source':'legacy_record','summary':r.get('greet_evidence','')})
    if r.get('resume_status')=='waiting':self.event(j['job_id'],'resume','waiting','legacy:resume:'+j['job_id'],{'source':'legacy_record','summary':r.get('resume_note','')})
   except (ValueError,KeyError):continue
