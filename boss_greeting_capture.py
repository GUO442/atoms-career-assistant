# -*- coding: utf-8 -*-
"""Passively record the next real BOSS greeting request. Never sends a greeting."""
import json
import time
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl
from urllib.request import urlopen
import boss_web

GREETING='/wapi/zpgeek/friend/add.json'
def shape(value,depth=0):
 if depth>4:return type(value).__name__
 if isinstance(value,dict):return {str(k):shape(v,depth+1) for k,v in value.items()}
 if isinstance(value,list):return {'type':'array','item_schema':shape(value[0],depth+1) if value else None}
 return 'null' if value is None else ('boolean' if isinstance(value,bool) else 'number' if isinstance(value,(int,float)) else 'string')
def sanitize_request(req):
 u=urlsplit(req['url']);text=req.get('postData','');params={}
 if text:
  try:params=json.loads(text)
  except ValueError:params=dict(parse_qsl(text,keep_blank_values=True))
 headers=req.get('headers',{})
 return {'method':req.get('method'),'path':u.path,'query_fields':sorted(k for k,v in parse_qsl(u.query,keep_blank_values=True)),'body_schema':shape(params),'content_type':next((v for k,v in headers.items() if k.lower()=='content-type'),None),'values_saved':False}
def capture(timeout_seconds=600,output=None):
 if type(timeout_seconds)!=int or not 10<=timeout_seconds<=600:raise ValueError('timeout_seconds须为10至600整数')
 import websocket
 output=Path(output or boss_web.WORKSPACE/'data'/'boss-greeting-interface.json')
 with urlopen(boss_web.DEBUG+'/json/version',timeout=3) as r:version=json.load(r)
 u=urlsplit(version['webSocketDebuggerUrl'])
 if u.scheme!='ws' or u.hostname not in ('127.0.0.1','localhost') or u.port!=boss_web.PORT:raise ValueError('Invalid browser endpoint')
 ws=websocket.create_connection(version['webSocketDebuggerUrl'],timeout=1,suppress_origin=True)
 counter=0;sessions=set();pending={};body_requests={};captured=[]
 def command(method,params,session=None):
  nonlocal counter
  counter+=1;d={'id':counter,'method':method,'params':params}
  if session:d['sessionId']=session
  ws.send(json.dumps(d));return counter
 try:
  command('Target.setAutoAttach',{'autoAttach':True,'waitForDebuggerOnStart':False,'flatten':True})
  deadline=time.monotonic()+timeout_seconds
  print(json.dumps({'status':'listening','effect':'observe_only','path':GREETING},ensure_ascii=False),flush=True)
  while time.monotonic()<deadline:
   try:d=json.loads(ws.recv())
   except websocket.WebSocketTimeoutException:continue
   p=d.get('params',{});session=d.get('sessionId');method=d.get('method')
   if method=='Target.attachedToTarget':
    sid=p['sessionId'];info=p.get('targetInfo',{})
    if info.get('type')=='page':sessions.add(sid);command('Network.enable',{},sid)
   if session not in sessions:continue
   key=(session,p.get('requestId'))
   if method=='Network.requestWillBeSent':
    req=p['request'];u=urlsplit(req.get('url',''))
    if u.hostname=='www.zhipin.com' and u.path==GREETING:pending[key]=sanitize_request(req)
   elif method=='Network.responseReceived' and key in pending:
    pending[key]['http_status']=p['response']['status']
   elif method=='Network.loadingFinished' and key in pending:
    body_requests[command('Network.getResponseBody',{'requestId':p['requestId']},session)]=key
   elif method=='Network.loadingFailed' and key in pending:
    captured.append({**pending.pop(key),'transport_status':'failed','sent_verified':False})
   elif d.get('id') in body_requests:
    key=body_requests.pop(d['id']);record=pending.pop(key)
    try:
     body=json.loads(d.get('result',{}).get('body',''))
     record.update(business_code=body.get('code'),response_schema=shape(body),sent_verified=False,note='真实页面请求；业务成功不等于已发送附件，需另核验聊天送达回显')
    except (ValueError,TypeError):record.update(response_readable=False,sent_verified=False)
    captured.append(record)
   if captured:
    result={'captured_at':time.strftime('%Y-%m-%dT%H:%M:%S%z'),'effect':'observe_only','requests':captured,'credentials_saved':False,'request_values_saved':False,'sent_by_recorder':False}
    output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(result,ensure_ascii=False,indent=2));output.chmod(0o600)
    return {'ok':True,'captured':True,'file':str(output),'requests':captured,'sent_by_recorder':False}
  return {'ok':False,'captured':False,'error':{'code':'CAPTURE_TIMEOUT','message':'监听期间未捕获新的打招呼请求；未发送或重试任何消息'}}
 finally:ws.close()
if __name__=='__main__':
 import argparse
 parser=argparse.ArgumentParser();parser.add_argument('--timeout',type=int,default=600);args=parser.parse_args()
 print(json.dumps(capture(args.timeout),ensure_ascii=False),flush=True)
