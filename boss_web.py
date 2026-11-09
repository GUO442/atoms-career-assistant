# -*- coding: utf-8 -*-
"""Read-only BOSS page APIs, executed in the user's dedicated Chrome session.

No MCP, exported cookies, HAR replay, arbitrary URLs, or challenge retries.
"""
from discovery import policy_metadata
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen
from runtime_paths import WORKSPACE

ORIGIN='https://www.zhipin.com'
PORT=18744
DEBUG=f'http://127.0.0.1:{PORT}'
PROFILE=WORKSPACE/'data'/'boss-browser'
LOCK=threading.RLock()
CITIES={'全国':'100010000','北京':'101010100','上海':'101020100','广州':'101280100','深圳':'101280600','杭州':'101210100','成都':'101270100','南京':'101190100','苏州':'101190400','武汉':'101200100','西安':'101110100','长沙':'101250100','天津':'101030100','重庆':'101040100'}
TOOLS=[{'name':'status','description':'通过页面已观察的账号接口检查会话','parameters':{}},
 {'name':'open-login','description':'打开专用 Chrome，由用户登录 BOSS','parameters':{}},
 {'name':'search','description':'POST 页面岗位搜索接口；city 为城市名或9位城市码','parameters':{'query':'string','city':'string','page':'integer (optional, 1以上)'}},
 {'name':'expectations','description':'读取当前账号求职期望，返回推荐查询所需 expect_id','parameters':{}},
 {'name':'recommend','description':'读取精选职位或最新职位，不需要搜索关键词','parameters':{'kind':'featured|latest|recommended','expect_id':'string (optional; default first expectation)','page':'integer (optional, 1以上)'}},
 {'name':'detail','description':'GET 页面JD接口；保留搜索返回的 job_id、security_id、lid','parameters':{'job_id':'string','security_id':'string','lid':'string'}}]
class WebError(ValueError):
 def __init__(self,code,message):self.code=code;super().__init__(message)
_LAST_AUTO_OPEN=0

def targets():
 """List BOSS pages; if the window is empty, open one chat tab once and retry."""
 global _LAST_AUTO_OPEN
 try:
  with urlopen(DEBUG+'/json/list',timeout=2) as r:data=json.load(r)
 except Exception:raise WebError('BROWSER_NOT_READY','请先打开 BOSS 登录窗口并完成登录，再执行查询')
 pages=[t for t in data if t.get('type')=='page' and urlsplit(t.get('url','')).scheme=='https' and urlsplit(t['url']).hostname=='www.zhipin.com']
 if pages or time.time()-_LAST_AUTO_OPEN<10:return pages
 _LAST_AUTO_OPEN=time.time()
 try:urlopen(Request(DEBUG+'/json/new?'+ORIGIN+'/web/geek/chat',method='PUT'),timeout=5).read()
 except Exception:return pages
 for _ in range(25):
  time.sleep(0.3)
  try:
   with urlopen(DEBUG+'/json/list',timeout=2) as r:data=json.load(r)
  except Exception:break
  pages=[t for t in data if t.get('type')=='page' and urlsplit(t.get('url','')).scheme=='https' and urlsplit(t['url']).hostname=='www.zhipin.com']
  if pages:return pages
 return pages
def open_login():
 PROFILE.mkdir(parents=True,exist_ok=True);PROFILE.chmod(0o700)
 try:
  if targets():
   evaluate('(()=>{const a=[...document.querySelectorAll("a")].find(x=>x.textContent.trim().startsWith("登录/注册") && x.getClientRects().length);if(a)a.click();return {login_entry_opened:!!a}})()')
   return {'browser_open':True,'logged_in':None,'note':'已打开登录入口，请在窗口完成登录后检查连接'}
 except WebError:pass
 candidates=[os.environ.get('CAREER_CHROME',''),'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',shutil.which('google-chrome'),shutil.which('chromium'),str(Path(os.environ.get('PROGRAMFILES','C:/Program Files'))/'Google/Chrome/Application/chrome.exe'),str(Path(os.environ.get('LOCALAPPDATA',''))/'Google/Chrome/Application/chrome.exe')]
 binary=next((p for p in candidates if p and Path(p).is_file()),None)
 if not binary:raise WebError('CHROME_NOT_FOUND','未找到 Chrome；可通过 CAREER_CHROME 指定可执行文件')
 subprocess.Popen([binary,f'--remote-debugging-port={PORT}','--remote-debugging-address=127.0.0.1',f'--user-data-dir={PROFILE}','--no-first-run','--no-default-browser-check',ORIGIN+'/web/user/?ka=header-login'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,start_new_session=True)
 return {'browser_open':True,'logged_in':None,'note':'请在专用 Chrome 窗口完成登录，再检查连接；不导出 Cookie'}
def evaluate(expression,target_path=None):
 try:import websocket
 except ImportError:raise WebError('DEPENDENCY_MISSING','请安装 requirements.txt 中的 websocket-client')
 pages=targets()
 if target_path is not None:
  pages=[p for p in pages if urlsplit(p['url']).path==target_path]
  if not pages:
   # The requested route is not open yet; create it once and re-read.
   try:urlopen(Request(DEBUG+'/json/new?'+ORIGIN+target_path,method='PUT'),timeout=5).read()
   except Exception:pass
   for _ in range(20):
    time.sleep(0.3)
    pages=[p for p in targets() if urlsplit(p['url']).path==target_path]
    if pages:break
 if not pages:raise WebError('BROWSER_NOT_READY','专用浏览器中没有 BOSS 页面，请打开登录窗口')
 pages.sort(key=lambda t: 0 if urlsplit(t['url']).path not in ('/web/geek/chat','/web/user/') else 1)
 wsurl=pages[0].get('webSocketDebuggerUrl','');u=urlsplit(wsurl)
 if u.scheme!='ws' or u.hostname not in ('127.0.0.1','localhost') or u.port!=PORT:raise WebError('INVALID_BROWSER','浏览器调试地址无效')
 try:
  ws=websocket.create_connection(wsurl,timeout=35,suppress_origin=True)
  try:
   ws.send(json.dumps({'id':1,'method':'Runtime.evaluate','params':{'expression':expression,'awaitPromise':True,'returnByValue':True}}))
   deadline=time.monotonic()+35
   while time.monotonic()<deadline:
    data=json.loads(ws.recv())
    if data.get('id')!=1:continue
    result=data.get('result',{})
    if data.get('error') or result.get('exceptionDetails'):raise WebError('PAGE_REQUEST_FAILED','页面请求失败，请检查登录或验证页面；未自动重试')
    value=result.get('result',{}).get('value')
    if not isinstance(value,dict):raise WebError('PAGE_REQUEST_FAILED','页面未返回可识别结果')
    return value
   raise WebError('REQUEST_TIMEOUT','页面请求超时，未自动重试')
  finally:ws.close()
 except WebError:raise
 except Exception:raise WebError('BROWSER_CONNECTION_FAILED','无法连接专用 Chrome；请重新检查登录窗口，未自动重试')
def request(path,method,params,target_path=None):
 # The origin's own page supplies cookies and runtime request hooks.
 payload={'path':path,'method':method,'params':params}
 expression='''(async()=>{const p=PAYLOAD;if(location.origin!=="https://www.zhipin.com")return {transport_error:true};const q=new URLSearchParams(p.params);let url=p.path;const o={method:p.method,credentials:"same-origin",signal:AbortSignal.timeout(25000)};if(p.method==="GET")url+="?"+q;else{o.headers={"Content-Type":"application/x-www-form-urlencoded;charset=UTF-8"};o.body=q.toString()}try{const r=await fetch(url,o);let b;try{b=await r.json()}catch{return {http_status:r.status,invalid_json:true}}return {http_status:r.status,body:b}}catch{return {transport_error:true}}})()'''.replace('PAYLOAD',json.dumps(payload,ensure_ascii=False))
 if target_path is None and any(urlsplit(t.get('url','')).path=='/web/geek/chat' for t in targets()):
  target_path='/web/geek/chat'  # a stable same-origin page; job tabs may hold stale challenges
 result=evaluate(expression,target_path=target_path) if target_path else evaluate(expression)
 if result.get('transport_error'):raise WebError('PAGE_REQUEST_FAILED','页面接口请求失败或超时，未自动重试')
 if result.get('http_status')!=200 or result.get('invalid_json'):raise WebError('AUTH_OR_RISK_REQUIRED','页面未返回成功JSON，请处理登录、验证码或限流后手动继续')
 body=result.get('body')
 if not isinstance(body,dict) or body.get('code')!=0:
  code=body.get('code') if isinstance(body,dict) else 'invalid_body'
  raise WebError('AUTH_OR_RISK_REQUIRED','BOSS接口 '+path+' 返回业务码 '+str(code)+'；未获得成功数据，请检查页面提示后继续')
 if not isinstance(body.get('zpData'),dict):raise WebError('INVALID_RESPONSE','页面响应结构变化，已停止')
 return body['zpData']
def city_code(value):
 if not isinstance(value,str):raise WebError('INVALID_ARGUMENT','city须为城市名或9位城市码')
 value=value.strip().removesuffix('市')
 if re.fullmatch(r'\d{9}',value):return value
 if value in CITIES:return CITIES[value]
 raise WebError('INVALID_CITY','暂不识别该城市；请使用BOSS页面URL中的9位city城市码')
def ensure_session():
 user=request('/wapi/zpuser/wap/getUserInfo.json','GET',{'_':str(int(time.time()*1000))})
 if not user:raise WebError('AUTH_REQUIRED','请先在专用浏览器登录，再查询岗位')
 return {'logged_in':True,'live':True,'source':'boss_web_api'}
def search(args):
 if set(args)-{'query','city','page','salary','experience','degree'}:raise WebError('INVALID_ARGUMENT','搜索参数不支持')
 query=args.get('query');page=args.get('page',1)
 if not isinstance(query,str) or not query.strip() or len(query)>100 or type(page)!=int or page<1:raise WebError('INVALID_ARGUMENT','需要有效关键词和1以上的页码')
 params={k:'' for k in ('expectInfo','multiSubway','multiBusinessDistrict','position','jobType','salary','experience','degree','industry','scale','stage','scene','encryptExpectId')}
 for k in ('salary','experience','degree'):
  v=args.get(k,'')
  if not isinstance(v,str) or (v and not re.fullmatch(r'[\d,]+',v)):raise WebError('INVALID_ARGUMENT','筛选条件须使用页面枚举码')
  params[k]=v
 params.update(query=query.strip(),city=city_code(args.get('city')),page=str(page),pageSize='10')
 ensure_session()
 data=request('/wapi/zpgeek/search/joblist.json','POST',params)
 if not isinstance(data.get('jobList'),list):raise WebError('INVALID_RESPONSE','搜索响应缺少jobList，不能当作零结果')
 return {'items':normalize_jobs(data),'query':query.strip(),'city':params['city'],'page':page,'has_more':data.get('hasMore',False)}
def normalize_jobs(data):
 if not isinstance(data.get('jobList'),list):raise WebError('INVALID_RESPONSE','岗位响应缺少jobList')
 items=[];seen=set()
 for row in data['jobList']:
  if not isinstance(row,dict):raise WebError('INVALID_RESPONSE','岗位结构变化')
  key=row.get('encryptJobId','')
  if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9_-]+',key):raise WebError('INVALID_RESPONSE','搜索结果缺少有效岗位ID')
  if key in seen:continue
  seen.add(key)
  items.append({'job_id':key,'title':row.get('jobName',''),'company':row.get('brandName',''),'city':row.get('cityName',''),'salary':row.get('salaryDesc',''),'experience':row.get('jobExperience',''),'education':row.get('jobDegree',''),'security_id':row.get('securityId',''),'lid':row.get('lid') or data.get('lid',''),'url':ORIGIN+'/job_detail/'+key+'.html','source':'boss_web_api','collected_at':time.time()})
  items[-1].update(policy_metadata(row))
 return items
def expectations(args):
 if args:raise WebError('INVALID_ARGUMENT','求职期望查询不需要参数')
 ensure_session()
 data=request('/wapi/zpgeek/recommend/conditions.json','GET',{})
 rows=data.get('expectList')
 if not isinstance(rows,list):raise WebError('INVALID_RESPONSE','求职期望响应缺少expectList')
 result=[]
 for row in rows:
  if not isinstance(row,dict) or not isinstance(row.get('encryptId'),str) or not row['encryptId']:raise WebError('INVALID_RESPONSE','求职期望标识缺失')
  result.append({'expect_id':row['encryptId'],'city':row.get('locationName',''),'position':row.get('positionName',''),'salary':row.get('salary','')})
 return {'items':result}
def recommend(args):
 if set(args)-{'kind','expect_id','page'}:raise WebError('INVALID_ARGUMENT','推荐参数不支持')
 kind=args.get('kind','featured');page=args.get('page',1);expect_id=args.get('expect_id')
 if kind not in ('featured','latest','recommended') or type(page)!=int or page<1:raise WebError('INVALID_ARGUMENT','kind须为featured、latest或recommended，page须为1以上整数')
 if expect_id is not None and (not isinstance(expect_id,str) or not expect_id or len(expect_id)>2000):raise WebError('INVALID_ARGUMENT','expect_id须使用求职期望查询结果')
 if kind=='recommended':return pc_recommend(page,expect_id)
 available=expectations({})['items']
 if not available:raise WebError('NO_EXPECTATIONS','请先在BOSS设置求职期望')
 selected=next((e for e in available if e['expect_id']==expect_id),None) if expect_id else available[0]
 if selected is None:raise WebError('INVALID_EXPECTATION','所选求职期望不在当前账号期望列表中')
 pk=evaluate('({pk:document.querySelector("#page_key_name")?.value||""})').get('pk','')
 params={k:'' for k in ('salary','payType','degree','experience','stage','scale','districtCode','businessCode')}
 params.update(expectId=selected['expect_id'],pk=pk,sortType='1' if kind=='featured' else '2',page=str(page))
 data=request('/wapi/zpgeek/recommend/job/list.json','GET',params)
 return {'items':normalize_jobs(data),'kind':kind,'page':page,'expectation':selected,'default_expectation':expect_id is None,'total_count':data.get('totalCount'),'page_size':data.get('pageSize')}

def pc_recommend(page,expect_id):
 if expect_id is not None:raise WebError('INVALID_ARGUMENT','推荐页综合推荐不接受单条求职期望ID')
 ensure_session()
 conditions=request('/wapi/zpgeek/pc/recommend/expect/list.json','GET',{})
 mix=conditions.get('mixExpect')
 if not isinstance(mix,dict) or not mix.get('encryptExpectId') or not mix.get('location') or mix.get('mixExpectType')!=1:raise WebError('INVALID_RESPONSE','推荐页缺少有效综合推荐条件')
 params={k:'' for k in ('expectInfo','jobType','salary','experience','degree','industry','scale')}
 params.update(page=str(page),pageSize='15',city=str(mix['location']),encryptExpectId=mix['encryptExpectId'],mixExpectType='1')
 data=request('/wapi/zpgeek/pc/recommend/job/list.json','GET',params)
 return {'items':normalize_jobs(data),'kind':'recommended','page':page,'expectation':{'city':mix.get('locationName',''),'position':mix.get('positionName','推荐职位')},'default_expectation':False,'source_page':ORIGIN+'/web/geek/jobs?ka=header-jobs','has_more':data.get('hasMore',False)}

def detail(args):
 if set(args)-{'job_id','security_id','lid'}:raise WebError('INVALID_ARGUMENT','详情参数不支持')
 for k in ('job_id','security_id','lid'):
  if not isinstance(args.get(k),str) or not args[k].strip() or len(args[k])>2000:raise WebError('INVALID_ARGUMENT','详情须使用搜索结果中的 job_id、security_id、lid')
 ensure_session()
 data=request('/wapi/zpgeek/job/detail.json','GET',{'securityId':args['security_id'],'lid':args['lid'],'_':str(int(time.time()*1000))})
 row=data.get('jobInfo') or {};key=row.get('encryptId') or row.get('encryptJobId')
 if key!=args['job_id']:raise WebError('JOB_MISMATCH','详情岗位ID与搜索结果不一致，已停止')
 jd=row.get('postDescription')
 if not isinstance(jd,str) or not jd.strip():raise WebError('INVALID_RESPONSE','未返回完整JD')
 return {**policy_metadata(row),'salary':row.get('salaryDesc',''),'job_id':key,'description':jd,'recruiter':str((data.get('bossInfo') or {}).get('name') or ''),'title':row.get('jobName',''),'company':(data.get('brandComInfo') or {}).get('brandName',''),'url':ORIGIN+'/job_detail/'+key+'.html','source':'boss_web_api','collected_at':time.time()}
def call(name,args=None):
 args={} if args is None else args
 try:
  if not isinstance(args,dict):raise WebError('INVALID_ARGUMENT','参数须为对象')
  with LOCK:
   if name=='catalog':data={'tools':TOOLS,'transport':'same-origin page fetch','source':'boss_web_api'}
   elif name=='open-login':
    if args:raise WebError('INVALID_ARGUMENT','登录不需要参数')
    data=open_login()
   elif name=='status':
    if args:raise WebError('INVALID_ARGUMENT','状态检查不需要参数')
    data=ensure_session()
   elif name=='search':data=search(args)
   elif name=='expectations':data=expectations(args)
   elif name=='recommend':data=recommend(args)
   elif name=='detail':data=detail(args)
   else:raise WebError('UNKNOWN_TOOL','未注册的网页工具')
  return {'ok':True,'live':name in ('status','search','detail','expectations','recommend'),'data':data}
 except WebError as e:return {'ok':False,'live':False,'error':{'code':e.code,'message':str(e)}}
 except Exception:return {'ok':False,'live':False,'error':{'code':'WEB_TOOL_FAILED','message':'网页工具执行失败，未自动重试'}}
