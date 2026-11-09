# -*- coding: utf-8 -*-
"""Conversation-to-Harness bridge. Models propose actions; Harness executes them."""
from agent_runtime import FIELDS
from execution_control import check_cancelled

STATUS = {'ready':'待启动','running':'执行中','waiting_input':'等待补充资料','waiting_selection':'等待选岗',
          'waiting_connection':'等待恢复连接','interrupted':'执行中断','failed':'执行失败',
          'budget_exceeded':'达到执行预算','cancelled':'已停止','completed':'已完成'}

def latest_text(data):
 return next((m['content'] for m in reversed(data.get('messages',[])) if m['role']=='user'),'')

def recent_messages(messages,limit=24000):
 result=[];remaining=limit
 for message in reversed(messages[-24:]):
  content=message['content']
  if remaining<=0:break
  text=content[-remaining:];result.append({'role':message['role'],'content':text});remaining-=len(text)
 return list(reversed(result))

class ChatWorkflows:
 def __init__(self,harness):
  self.harness=harness
  with harness.connect() as c:c.execute('CREATE TABLE IF NOT EXISTS chat_runs (conversation TEXT NOT NULL, run_id TEXT NOT NULL UNIQUE)')

 def linked(self,conversation):
  with self.harness.connect() as c:ids=[r[0] for r in c.execute('SELECT run_id FROM chat_runs WHERE conversation=? ORDER BY rowid DESC',(conversation,))]
  return [self.harness.get(key) for key in ids[:20]]

 def execute(self,data,plan):
  latest=latest_text(data)
  conversation=data.get('conversation_id') or '__legacy__'
  runs=self.linked(conversation)
  action=plan['action'];args=plan['arguments'];allowed={r['id']:r for r in runs}
  check_cancelled()
  try:
   if action=='none' and not args:return None
   if action=='create':
    if set(args)!={'mode','context'} or args['mode'] not in ('boss','jd'):raise ValueError('任务类型或参数无效')
    ctx=self.validate_context(args['context'])
    ctx={k:data.get(k,'') for k in FIELDS}|ctx
    ctx['goal']=ctx.get('goal') or latest
    key=self.harness.create(args['mode'],ctx,data.get('consent') is True)
    with self.harness.connect() as c:c.execute('INSERT INTO chat_runs VALUES (?,?)',(conversation,key))
    self.harness.start(key);run=self.harness.get(key)
    return self.response('已创建并启动 Harness 任务。',run,action)
   if action=='status' and not args:
    if not runs:return {'answer':'本对话还没有 Harness 任务。可以说“启动工作流，寻找深圳 AI 测试岗位并生成简历草稿”。','tool_results':[{'tool':'harness.status','runs':[]}]}
    return {'answer':'本对话的 Harness 任务：\n\n'+'\n\n'.join(self.describe(r) for r in runs),
            'tool_results':[{'tool':'harness.status','runs':[self.summary(r) for r in runs]}]}
   key=args.get('id')
   if not isinstance(key,str) or key not in allowed:raise ValueError('请明确本对话中的任务，或在 Agent任务 页面操作已有任务')
   if action in ('status','resume','cancel') and set(args)=={'id'}:
    if action=='resume':self.harness.start(key,data.get('consent') is True)
    if action=='cancel':self.harness.cancel(key)
   elif action=='select' and set(args)=={'id','job_id'} and isinstance(args['job_id'],str):
    self.harness.select(key,args['job_id']);self.harness.start(key,data.get('consent') is True)
   elif action=='update' and set(args)=={'id','context'}:
    self.harness.update(key,self.validate_context(args['context']))
   else:raise ValueError('工作流操作或参数无效')
   return self.response({'status':'已读取任务状态。','resume':'已请求从检查点继续。','cancel':'已停止任务。','select':'已确认选岗并继续执行。','update':'已更新任务输入，可说“继续任务”执行。'}[action],self.harness.get(key),action)
  except (ValueError,TypeError) as exc:return self.error(str(exc))

 @staticmethod
 def validate_context(ctx):
  fields={'goal','query','city','deliverable','jd','jobtitle','joburl'}
  if not isinstance(ctx,dict) or set(ctx)-fields or any(not isinstance(v,str) or len(v)>200000 for v in ctx.values()):raise ValueError('工作流输入未通过校验')
  return ctx

 @staticmethod
 def summary(r):
  return {k:r.get(k) for k in ('id','status','cursor','pending','selected_job','artifact')}|{'goal':r['context'].get('goal',''), 'jobs':[{k:v for k,v in j.items() if k not in ('security_id','lid')} for j in r.get('jobs',[])]}

 @staticmethod
 def describe(r):
  text='任务：'+r['id']+'\n状态：'+STATUS.get(r['status'],r['status'])+' · '+str(r['cursor'])+' 个检查点'
  if r.get('pending'):text+='\n'+r['pending']
  if r['status']=='waiting_selection':text+='\n'+'\n'.join(str(i+1)+'. '+str(j.get('company',''))+' · '+str(j.get('title',''))+'（'+j['job_id']+'）' for i,j in enumerate(r.get('jobs',[])))
  if r['status']=='completed':text+='\n交付物已保存，可在 Agent任务 中查看并保存。'
  return text

 def response(self,message,run,action):
  return {'workflow_id':run['id'],'answer':message+'\n\n'+self.describe(run)+'\n\n可在“Agent任务”查看执行记录，或在此询问任务进度。',
          'tool_results':[{'tool':'harness.'+action,'run':self.summary(run)}]}

 @staticmethod
 def error(message):
  return {'answer':message,'tool_results':[{'tool':'harness','error':message}]}
