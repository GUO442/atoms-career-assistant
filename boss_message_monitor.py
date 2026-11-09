# -*- coding: utf-8 -*-
"""Near-real-time read-only message polling using observed page APIs."""
import hashlib,json,threading,time
import boss_web
class MessageMonitor:
 def __init__(self,tracker,library=None,adapter=None):
  self.tracker=tracker;self.library=library;self.adapter=adapter;self.thread=None;self.stop_event=threading.Event();self.lock=threading.RLock();self.last_seen={};self.self_uid='';self.state={'status':'stopped','interval_seconds':10,'note':'未启动消息监控；自动发送能力另行核验'}
 def status(self):
  with self.lock:return dict(self.state)
 def update(self,**state):
  with self.lock:self.state.update(state)
 def start(self):
  with self.lock:
   if self.thread and self.thread.is_alive():return self.status()
   self.stop_event.clear();self.update(status='starting',note='正在核验已登录的消息页面');self.thread=threading.Thread(target=self.loop,daemon=True);self.thread.start();return self.status()
 def stop(self):self.stop_event.set();self.update(status='stopped',note='消息监控已停止');return self.status()
 def snapshot(self):
  page=boss_web.evaluate('({ids:Object.values(window.chatStore?.friendInfos||{}).map(x=>String(x.uid)).join(","),available:!!window.chatStore,self_uid:String(window._PAGE?.uid||"")})',target_path='/web/geek/chat')
  self.self_uid=page.get('self_uid','')
  if not page.get('available'):raise boss_web.WebError('CHAT_NOT_READY','请在已登录浏览器打开BOSS消息页')
  if not page.get('ids'):return []
  data=boss_web.request('/wapi/zprelation/friend/getGeekFriendList.json','POST',{'friendIds':page['ids']},target_path='/web/geek/chat')
  if not isinstance(data.get('result'),list):raise boss_web.WebError('CHAT_SCHEMA_CHANGED','消息列表结构变化，监控已停止')
  return data['result']
 def history(self,contact):
  params={'bossId':contact['encryptBossId'],'securityId':contact['securityId'],'maxMsgId':'0','c':'20','page':'1','src':'0'}
  data=boss_web.request('/wapi/zpchat/geek/historyMsg','GET',params,target_path='/web/geek/chat')
  if not isinstance(data.get('messages'),list):raise boss_web.WebError('CHAT_SCHEMA_CHANGED','历史消息结构变化，已停止')
  return data['messages'],data.get('hasMore',False)
 def sync(self):
  contacts=self.snapshot();known={j['job_id']:j for j in self.tracker.listing()['jobs']};updated=0
  for contact in contacts:
   job_id=contact.get('encryptJobId');uid=str(contact.get('uid',''))
   if job_id not in known or not uid:continue
   # The API supplies the job/contact association; names alone never bind a message.
   self.tracker.register({'job_id':job_id,'recruiter_id':uid,'recruiter':contact.get('name','')})
   msg=contact.get('lastMessageInfo') or {};marker=str(msg.get('msgId',''))+':'+str(contact.get('lastTS',''))
   if self.last_seen.get((job_id,uid))==marker:continue
   messages,more=self.history(contact)
   if more:self.update(history_note='部分会话历史多于20条，仅核验最新20条；较早记录未推断')
   for m in sorted(messages,key=lambda m:m.get('time',0)):
    at=m.get('time',0);at=at/1000 if at>100000000000 else at
    if not at:continue
    sender=str((m.get('from') or {}).get('uid',''));mid=str(m.get('mid',''));body=m.get('body') or {}
    # Only observed text bodies are eligible for response classification.
    text=body.get('text') or body.get('content')
    if sender==uid:
     if isinstance(text,str) and text:
      updated+=int(self.tracker.incoming(job_id,uid,mid,text,at))
      if self.library:
       from resume_delivery_workflow import acknowledge_receipt
       acknowledge_receipt(self.library,self.tracker,job_id,uid,mid,text,at)
     else:self.tracker.event(job_id,'reply','replied','incoming-card:'+job_id+':'+mid,{'source':'network_message','message_id':mid,'summary':'收到非文本消息，需人工查看'},at)
    elif sender and sender==self.self_uid:
     # An outgoing text proves contact, never attachment delivery.
     self.tracker.event(job_id,'greet','sent','outgoing:'+job_id+':'+mid,{'source':'network_message','message_id':mid},at)
   self.last_seen[(job_id,uid)]=marker
  self.update(last_sync=time.time(),observed_contacts=len(contacts),tracked_contacts=sum(c.get('encryptJobId') in known for c in contacts),new_events=updated)
  return self.status()
 def loop(self):
  try:
   while not self.stop_event.is_set():
    self.sync()
    if self.stop_event.is_set():return
    self.update(status='monitoring',note='每10秒同步已加载联系人的消息；登录失效即停止，不自动登录')
    if self.library:self.tracker.dispatch(self.adapter,self.library)
    if getattr(self,'drafts',None):self.drafts.process()
    self.stop_event.wait(10)
  except Exception as e:
   self.update(status='needs_attention',note=str(e),stopped_at=time.time())
