# -*- coding: utf-8 -*-
"""Text replies through the page's observed Editor.sendText -> chat SDK path.

Only the currently selected, exactly bound conversation is executable. A remote
history readback is required; an uncertain send is never retried automatically.
"""
import json,time
import boss_web

class PageReplyAdapter:
 verified=True
 supported_kinds={'reply_text'}
 def __call__(self,action):
  if action['kind']!='reply_text':return {'verified_sent':False,'reason':'附件发送链路尚未实抓核验'}
  job_id=action['job_id'];uid=action.get('recruiter_id');text=action.get('reply_text','')
  if not uid or not isinstance(text,str) or not 1<=len(text)<=200:raise ValueError('回复目标或预设话术无效')
  payload=json.dumps({'job_id':job_id,'uid':str(uid),'text':text},ensure_ascii=False)
  expression='''(async()=>{const p=PAYLOAD;if(!window._PAGE?.uid)return {sent:false,reason:"未确认当前求职账号身份，未发送"};let c=window.chat?.communicating;if(c?.encryptJobId!==p.job_id||String(c?.uid)!==p.uid){const nodes=[document.getElementById("wrap")?.__vue__];let target;while(nodes.length){const v=nodes.shift();if(!v)continue;if(v.$options?.name==="Editor"&&v.getInputText?.().trim())return {sent:false,reason:"当前会话有未发送草稿，未切换联系人"};if(v.$options?.name==="boss-item"&&v.source?.encryptJobId===p.job_id&&String(v.source?.uid)===p.uid)target=v;nodes.push(...(v.$children||[]))}if(!target||typeof target.handleOpenChat!=="function")return {sent:false,reason:"对应联系人尚未加载到页面，请打开对应会话"};target.handleOpenChat();await new Promise(resolve=>setTimeout(resolve,800));c=window.chat?.communicating;if(c?.encryptJobId!==p.job_id||String(c?.uid)!==p.uid)return {sent:false,reason:"会话身份尚未匹配，未发送"}}const q=[document.getElementById("wrap")?.__vue__];let editor;while(q.length){const x=q.shift();if(!x)continue;if(x.$options?.name==="Editor"){editor=x;break}q.push(...(x.$children||[]))}if(!editor||typeof editor.sendText!=="function"||!editor.$refs?.editbox)return {sent:false,reason:"页面SDK结构变化，未发送"};if(editor.getInputText().trim()&&editor.getInputText().trim()!==p.text)return {sent:false,reason:"输入框有未发送草稿，未覆盖"};editor.$refs.editbox.textContent=p.text;editor.$refs.editbox.dispatchEvent(new InputEvent("input",{bubbles:true,inputType:"insertText",data:p.text}));await new Promise(resolve=>setTimeout(resolve,250));await new Promise(resolve=>editor.$nextTick(resolve));if(!editor.enableSubmit)return {sent:false,reason:"发送按钮尚不可用，未发送"};editor.sendText();return {sent:true,self_uid:String(window._PAGE.uid)}})()'''.replace('PAYLOAD',payload)
  started=time.time();result=boss_web.evaluate(expression,target_path='/web/geek/chat')
  if not result.get('sent'):return {'verified_sent':False,'reason':result.get('reason')}
  # The page SDK uses the user's existing session; no cookie/signature export.
  for _ in range(3):
   time.sleep(.5)
   contacts=boss_web.evaluate('({items:Object.values(window.chatStore?.friendInfos||{}).map(x=>({uid:String(x.uid),encryptJobId:x.encryptJobId,encryptBossId:x.encryptBossId,securityId:x.securityId}))})',target_path='/web/geek/chat')['items']
   contact=next((c for c in contacts if c['uid']==str(uid) and c['encryptJobId']==job_id),None)
   if not contact:return {'verified_sent':False,'reason':'发送后岗位会话绑定变化，需人工核验'}
   history=boss_web.request('/wapi/zpchat/geek/historyMsg','GET',{'bossId':contact['encryptBossId'],'securityId':contact['securityId'],'maxMsgId':'0','c':'20','page':'1','src':'0'},target_path='/web/geek/chat')
   for msg in history.get('messages',[]):
    at=msg.get('time',0)/1000 if msg.get('time',0)>100000000000 else msg.get('time',0)
    if at>=started-2 and str((msg.get('from') or {}).get('uid'))==result.get('self_uid') and str((msg.get('to') or {}).get('uid'))==str(uid) and (msg.get('body') or {}).get('text')==text:
     return {'verified_sent':True,'receipt':{'message_id':str(msg['mid']),'at':at,'source':'history_api'}}
  return {'verified_sent':False,'reason':'请求已发起，但未能从历史接口核验结果；请查看聊天，不自动重试'}
