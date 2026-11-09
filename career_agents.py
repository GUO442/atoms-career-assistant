"""Business-agent registry and durable subtask execution within the existing Harness."""
import json,sqlite3,time,uuid,threading
AGENTS={
 'collect':{'title':'岗位采集Agent','skill':'boss-web-tools','tools':['recommend','detail']},
 'match':{'title':'匹配筛选Agent','skill':'job-search-screening','tools':['matching_policy.assess']},
 'greet':{'title':'沟通Agent','skill':'boss-jd-greeting','tools':['greeting-plan','greeting-web-send']},
 'tailor':{'title':'简历定制Agent','skill':'boss-tailor-resume','tools':['resume-tailor']},
 'deliver':{'title':'简历投递Agent','skill':'boss-job-apply','tools':['attachment-deliver']},
 'followup':{'title':'回复跟进Agent','skill':'boss-chat-opportunities','tools':['historyMsg']},
 'interview':{'title':'面试管理Agent','skill':'job-search-screening','tools':['jobs.status']},
}
OWNERS={'read_jd':'collect','greeting.model':'greet','tailor.model':'tailor','wait_reply':'followup'}
class AgentRuntime:
 def __init__(self,path):
  self.path=path;self.lock=threading.RLock()
  with self.connect() as c:
   c.executescript('CREATE TABLE IF NOT EXISTS agent_tasks(id TEXT PRIMARY KEY,batch_id TEXT,job_id TEXT,agent TEXT,node TEXT,status TEXT,started REAL,finished REAL,error TEXT);CREATE TABLE IF NOT EXISTS agent_events(id TEXT PRIMARY KEY,task_id TEXT,kind TEXT,at REAL,body TEXT);')
   if 'output' not in [r[1] for r in c.execute('PRAGMA table_info(agent_tasks)')]:c.execute('ALTER TABLE agent_tasks ADD COLUMN output TEXT')
   c.execute('CREATE TABLE IF NOT EXISTS agent_reports(id TEXT PRIMARY KEY,batch_id TEXT,at REAL,body TEXT)')
   c.execute("UPDATE agent_tasks SET status='interrupted',error='服务中断，外部发送需先核验' WHERE status='running'")
 def connect(self):return sqlite3.connect(self.path,timeout=15)
 def execute(self,batch,job,node,fn):
  agent=OWNERS.get(node,node)
  if agent not in AGENTS:raise ValueError('未注册的业务Agent节点')
  key=uuid.uuid4().hex
  with self.connect() as c:c.execute('INSERT INTO agent_tasks(id,batch_id,job_id,agent,node,status,started,finished,error) VALUES(?,?,?,?,?,?,?,?,?)',(key,batch,job,agent,node,'running',time.time(),None,''))
  result=None
  try:
   result=fn();state='completed';error=''
   return result
  except Exception as exc:
   from observability import capture
   state='failed';error=capture(type(exc).__name__+': '+str(exc))[:1500];raise
  finally:
   with self.connect() as c:
    from observability import capture
    c.execute('UPDATE agent_tasks SET status=?,finished=?,error=?,output=? WHERE id=?',(state,time.time(),error,json.dumps(capture(result),ensure_ascii=False),key))
    c.execute('INSERT INTO agent_events VALUES(?,?,?,?,?)',(uuid.uuid4().hex,key,state,time.time(),json.dumps({'batch_id':batch,'job_id':job,'agent':agent,'node':node})))
 def report(self,batch):
  tasks=self.status(batch)['tasks'];groups=[]
  for agent,meta in AGENTS.items():
   rows=[t for t in tasks if t['agent']==agent]
   if not rows:continue
   groups.append({'agent':agent,'title':meta['title'],'completed':sum(t['status']=='completed' for t in rows),'failed':sum(t['status'] in ('failed','interrupted') for t in rows),'running':sum(t['status']=='running' for t in rows),'latest_task':rows[0]})
  body=json.dumps(groups,ensure_ascii=False)
  with self.connect() as c:
   last=c.execute('SELECT at,body FROM agent_reports WHERE batch_id=? ORDER BY at DESC LIMIT 1',(batch,)).fetchone()
   if last and (time.time()-last[0]<900 or last[1]==body):return
   c.execute('INSERT INTO agent_reports VALUES(?,?,?,?)',(uuid.uuid4().hex,batch,time.time(),body))
 def reports(self,batch=None):
  with self.connect() as c:
   rows=c.execute('SELECT batch_id,at,body FROM agent_reports '+('WHERE batch_id=? ' if batch else '')+'ORDER BY at DESC LIMIT 30',(batch,) if batch else ()).fetchall()
  return [{'batch_id':b,'at':at,'agents':json.loads(body)} for b,at,body in rows]
 def status(self,batch=None):
  with self.connect() as c:
   c.row_factory=sqlite3.Row
   rows=c.execute('SELECT * FROM agent_tasks '+('WHERE batch_id=? ' if batch else '')+'ORDER BY started DESC LIMIT 300',(batch,) if batch else ()).fetchall()
  return {'reports':self.reports(batch),'agents':[{'id':k,**v} for k,v in AGENTS.items()],'tasks':[dict(r) for r in rows]}

def interview_signal(text):
 """An invitation is observed evidence, never confirmation of an appointment."""
 import re
 if not isinstance(text,str) or not re.search(r'面试|笔试',text):return None
 if re.search(r'取消面试|面试取消',text):return {'status':'cancelled','summary':text[:1000],'confirmed':False}
 if re.search(r'邀请|安排|参加|方便|时间|约|预约',text):return {'status':'invited','summary':text[:1000],'confirmed':False,'note':'邀请信息待本人确认时间，不自动记为已约面试'}
 return None
