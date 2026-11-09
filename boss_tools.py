# -*- coding: utf-8 -*-
"""BOSS tool facade: read-only page APIs, sanitized evidence, reviewed dispatch queue."""
import argparse,json,sys
from pathlib import Path
from urllib.parse import urlsplit,parse_qsl,unquote
ROOT=Path(__file__).resolve().parent
SOURCE='Search and detail observed in Chrome Network HAR on 2026-10-23; other endpoints remain source-only. Observed success is not independent transport validation.'
CATALOG=[
 {'tool':'expectations','method':'GET','path':'/wapi/zpgeek/recommend/conditions.json','parameters':[],'effect':'read','verification':'observed_browser_success'},
 {'tool':'recommend','method':'GET','path':'/wapi/zpgeek/recommend/job/list.json','parameters':['expectId','pk','sortType','page','salary','payType','degree','experience','stage','scale','districtCode','businessCode'],'effect':'read','verification':'observed_browser_success','sort_types':{'featured':1,'latest':2}},
 {'tool':'search','method':'POST','path':'/wapi/zpgeek/search/joblist.json','parameters':['page','pageSize','city','query','expectInfo','multiSubway','multiBusinessDistrict','position','jobType','salary','experience','degree','industry','scale','stage','scene','encryptExpectId'],'encoding':'application/x-www-form-urlencoded','effect':'read','verification':'observed_browser_success','http_status':200,'business_code':0},
 {'tool':'detail','method':'GET','path':'/wapi/zpgeek/job/detail.json','parameters':['securityId','lid','_'],'effect':'read','verification':'observed_browser_success','http_status':200,'business_code':0},
 {'tool':'card','method':'GET','path':'/wapi/zpgeek/job/card.json','parameters':['securityId','lid'],'effect':'read','verification':'source_only'},
 {'tool':'greet','method':'POST','path':'/wapi/zpgeek/friend/add.json','parameters':['securityId','jobId'],'parameter_location':'query','effect':'write_contact_default_greeting','verification':'observed_browser_success_and_history_receipt_20261029','callable':False,'note':'Custom first greeting and independent HTTP send remain unverified; no resume attachment.'},
 {'tool':'delivery_history','method':'GET','path':'/wapi/zprelation/resume/geekDeliverList','parameters':[],'effect':'read','verification':'source_only','callable':False},
 {'tool':'resume_send','method':None,'path':None,'parameters':[],'effect':'write_attachment','verification':'not_identified','callable':False},
]
RECOMMEND_TOOL={'name':'recommend-jobs','description':'读取BOSS网页综合推荐职位，入库并跨天去重，排除实习、非IT和方向无法确认岗位；仅返回新增候选','parameters':{}}
RESUME_TOOLS=[{'name':'resume-profile','description':'读取本地原始简历与求职偏好作为定制事实来源','parameters':{}},{'name':'resume-register','description':'保存已生成的岗位定制Word并关联JD和原始简历，始终待审阅，不发送','parameters':{'file':'absolute .docx path','job_file':'absolute verified job JSON path','source_resume_id':'string'}}]
RESUME_TOOLS += [{'name':'pipeline','description':'推荐岗位后台任务创建/查询/暂停/继续/取消，创建须明确授权','parameters':{'action':'create|status|pause|resume|cancel'}},

 {'name':'chat-opportunities-sync','description':'只读同步全部当前聊天联系人、历史和匹配机会，去重落库','parameters':{}},
 {'name':'chat-opportunities-status','description':'查询聊天机会状态、范围和筛选结果','parameters':{'filters':'object'}},
 {'name':'attachment-deliver','description':'后台执行已审阅版本上传、来源聊天、选附件、发送、回读及状态同步；已发不重发','parameters':{'query':'unique job','version_id':'ID or empty for latest','confirmed':'boolean'}},
 {'name':'attachment-delivery-status','description':'读取后台投递进度和持久化回执','parameters':{}},
 {'name':'attachment-delete','description':'明确确认满额替换计划中的附件ID后删除，保留本地备份；真实删除尚待验收','parameters':{'job_id':'string','version_id':'string','remote_id':'string','confirmed':'boolean'}},
 {'name':'attachment-inventory','description':'只读附件库实际容量及精确附件标识','parameters':{}},
 {'name':'attachment-plan','description':'核对岗位与版本并规划槽位，不执行远端写入','parameters':{'job_id':'string','version_id':'string'}},
 {'name':'attachment-upload','description':'明确授权且已审阅版本上传附件库；不发送HR；页面上传和SHA256回读已实测','parameters':{'job_id':'string','version_id':'string','confirmed':'boolean'}},
 {'name':'resume-tailor-context','description':'读取JD、原始简历、用户确认事实及定制Skill','parameters':{'query':'unique job ID, URL or company and title'}},
 {'name':'resume-tailor','description':'依据Skill启动后台Word定制，不发送','parameters':{'query':'unique job ID, URL or company and title'}},
 {'name':'resume-tailor-status','description':'查看后台定制状态及待审阅版本','parameters':{}}]
def register_resume_files(library,args,root):
 if set(args)!={'file','job_file','source_resume_id'}:raise ValueError('需要file、job_file、source_resume_id')
 file=Path(args['file']);job_file=Path(args['job_file'])
 if not file.is_absolute() or not job_file.is_absolute() or file.suffix.lower()!='.docx':raise ValueError('需要绝对路径及Word文件')
 if not file.resolve().is_relative_to(Path(root).resolve()) or not job_file.resolve().is_relative_to(Path(root).resolve()):raise ValueError('登记文件必须位于助手工作区')
 if file.stat().st_size>8_000_000:raise ValueError('Word文件超过8MB')
 return library.add_tailored(file.name,file.read_bytes(),json.loads(job_file.read_text()),args['source_resume_id'])
def resume_tool(action,args):
 import os,base64
 from urllib.request import Request,urlopen
 if not isinstance(args,dict):raise ValueError('参数必须是对象')
 if action=='resume-profile' and args:raise ValueError('resume-profile 无参数')
 if action=='resume-register':
  if set(args)!={'file','job_file','source_resume_id'}:raise ValueError('需要file、job_file、source_resume_id')
  file=Path(args['file']);job_file=Path(args['job_file'])
  if not file.is_absolute() or file.suffix.lower()!='.docx' or not job_file.is_absolute():raise ValueError('需要绝对路径及Word文件')
  if file.stat().st_size>8_000_000:raise ValueError('Word文件超过8MB')
  payload={'action':'import-tailored','name':file.name,'body':base64.b64encode(file.read_bytes()).decode(),'job':json.loads(job_file.read_text()),'source_resume_id':args['source_resume_id']}
 elif action in ('chat-opportunities-sync','chat-opportunities-status'):
  payload={'tool':action,'arguments':args}
 elif action in ('attachment-inventory','attachment-plan','attachment-upload','attachment-delete','attachment-deliver','attachment-delivery-status'):
  payload={'tool':action,'arguments':args}
 elif action in ('resume-tailor-context','resume-tailor','resume-tailor-status'):
  if action=='resume-tailor-status' and args:raise ValueError('状态工具无参数')
  if action!='resume-tailor-status' and (set(args)!={'query'} or not isinstance(args['query'],str) or not args['query'].strip()):raise ValueError('需要query岗位标识')
  payload={'tool':action,'arguments':args}
 elif action=='resume-profile':payload={'tool':'resume-profile','arguments':{}}
 else:raise ValueError('未知简历工具')
 base='http://127.0.0.1:'+str(int(os.environ.get('CAREER_PORT','18743')))
 with urlopen(base+'/api/state',timeout=3) as r:token=json.load(r)['token']
 path='/api/library' if action=='resume-register' else '/api/boss-web'
 req=Request(base+path,data=json.dumps(payload,ensure_ascii=False).encode(),headers={'X-App-Token':token,'Content-Type':'application/json'})
 with urlopen(req,timeout=15) as r:data=json.load(r)
 return {'ok':True,'data':data,'sent':False}
def filtered_recommend(discovery,args):
 if not isinstance(args,dict) or args:raise ValueError('recommend-jobs 不接受参数，使用页面综合推荐条件')
 return {'ok':True,'live':True,'data':discovery.recommend('recommended')}
def pipeline(args):
 from urllib.request import Request,urlopen
 from chat_intents import validate_pipeline
 validate_pipeline(args)
 import os
 base='http://127.0.0.1:'+str(int(os.environ.get('CAREER_PORT','18743')))
 with urlopen(base+'/api/state',timeout=3) as r:token=json.load(r)['token']
 req=Request(base+'/api/pipeline',data=json.dumps(args).encode(),headers={'X-App-Token':token,'Content-Type':'application/json'})
 with urlopen(req,timeout=15) as r:return json.load(r)

def recommend_jobs(args):
 import os
 from urllib.request import Request,urlopen
 if not isinstance(args,dict) or args:raise ValueError('recommend-jobs 不接受参数')
 base='http://127.0.0.1:'+str(int(os.environ.get('CAREER_PORT','18743')))
 with urlopen(base+'/api/state',timeout=3) as r:token=json.load(r)['token']
 req=Request(base+'/api/boss-web',data=json.dumps({'tool':'recommend-jobs','arguments':{}}).encode(),headers={'X-App-Token':token,'Content-Type':'application/json'})
 with urlopen(req,timeout=90) as r:return json.load(r)

def inspect_har(path):
 data=json.loads(Path(path).read_text());rows=[]
 for e in data.get('log',{}).get('entries',[]):
  req=e.get('request',{});url=urlsplit(req.get('url',''))
  if url.scheme!='https' or url.hostname!='www.zhipin.com' or not url.path.startswith('/wapi/'):continue
  query=[x[0] for x in parse_qsl(url.query,keep_blank_values=True)]
  post=req.get('postData',{});fields=[x.get('name','') for x in post.get('params',[])]
  # Persist names only: never headers, cookies, parameter values, payload bodies, or response text.
  rows.append({'method':req.get('method'),'path':url.path,'query_fields':sorted(set(query)),'body_fields':sorted(set(fields)),'http_status':e.get('response',{}).get('status'),'evidence':'observed_har_request','note':'Observed request is not proof of business success; no request replay.'})
 return {'requests':rows,'credentials_saved':False,'response_bodies_saved':False}
def captured_data(path,action,args):
 import base64
 raw=json.loads(Path(path).read_text());jobs=[];details=[];captured_queries=[]
 for entry in raw.get('log',{}).get('entries',[]):
  req=entry.get('request',{});url=urlsplit(req.get('url',''))
  if url.hostname!='www.zhipin.com' or url.path not in ('/wapi/zpgeek/search/joblist.json','/wapi/zpgeek/job/detail.json'):continue
  content=entry.get('response',{}).get('content',{});text=content.get('text','')
  if content.get('encoding')=='base64':text=base64.b64decode(text).decode('utf-8')
  try:body=json.loads(text)
  except (ValueError,TypeError):continue
  if body.get('code')!=0:continue
  data=body.get('zpData') or {}
  if url.path.endswith('/search/joblist.json'):
   form={x['name']:unquote(x.get('value','')) for x in req.get('postData',{}).get('params',[])}
   if args.get('query') and form.get('query')!=args['query']:continue
   if args.get('city_code') and form.get('city')!=args['city_code']:continue
   captured_queries.append({'query':form.get('query'),'city_code':form.get('city'),'page':form.get('page'),'page_size':form.get('pageSize')})
   for item in data.get('jobList',[]):
    key=item.get('encryptJobId','')
    if not key:continue
    jobs.append({'job_id':key,'title':item.get('jobName',''),'company':item.get('brandName',''),'city':item.get('cityName',''),'salary':item.get('salaryDesc',''),'experience':item.get('jobExperience',''),'education':item.get('jobDegree',''),'url':'https://www.zhipin.com/job_detail/'+key+'.html','source':'captured_browser_response'})
  else:
   item=data.get('jobInfo') or {};key=item.get('encryptId') or item.get('encryptJobId') or ''
   if args.get('job_id') and key!=args['job_id']:continue
   details.append({'job_id':key,'title':item.get('jobName',''),'company':(data.get('brandComInfo') or {}).get('brandName',''),'jd':item.get('postDescription',''),'source':'captured_browser_response'})
 if action=='captured-search':
  unique={j['job_id']:j for j in jobs};return {'ok':True,'live':False,'source':'local_har','data':list(unique.values()),'captured_queries':list({json.dumps(q,sort_keys=True):q for q in captured_queries}.values()),'note':'Historical capture only; no new platform search performed.'}
 if not args.get('job_id'):raise ValueError('job_id required for captured-detail')
 return {'ok':bool(details),'live':False,'source':'local_har','data':details[-1] if details else None,'note':'Only a detail actually present in this capture is returned.'}

def execute(action,args):
 if action=="pipeline":return pipeline(args)
 if action=='catalog':
  from boss_web import TOOLS as WEB_TOOLS
  from tracking_tools import TOOLS as TRACKING_TOOLS
  from greeting_tools import TOOLS as GREETING_TOOLS
  TOOLS=WEB_TOOLS+[RECOMMEND_TOOL]+RESUME_TOOLS+TRACKING_TOOLS+GREETING_TOOLS
  return {'source':SOURCE,'interfaces':CATALOG,'tools':TOOLS,'transport':'same-origin page fetch; no MCP'}
 if action.startswith('greeting-'):
  from greeting_tools import execute as greeting_execute
  from boss_reply_tool import PageReplyAdapter
  return greeting_execute(action,args,adapter=PageReplyAdapter())
 if action in ('chat-opportunities-sync','chat-opportunities-status','attachment-inventory','attachment-plan','attachment-upload','attachment-delete','attachment-deliver','attachment-delivery-status','resume-profile','resume-register','resume-tailor-context','resume-tailor','resume-tailor-status'):return resume_tool(action,args)
 if action=='recommend-jobs':return recommend_jobs(args)
 if action.startswith('tracking-'):
  from tracking_tools import call
  return call(action,args)
 if action=='capture-greeting':
  from boss_greeting_capture import capture
  return capture(args.get('timeout_seconds',600))
 if action=='inspect-har':return inspect_har(args['file'])
 if action in ('search','detail','status','open-login','expectations','recommend'):
  from boss_web import call
  return call(action,args)
 if action in ('captured-search','captured-detail'):
  return captured_data(args.get('file'),action,args)
 if action=='prepare-application':
  from resume_library import Library
  if args.get('confirmed') is not True:raise ValueError('Explicit confirmation of this job and resume version is required')
  lib=Library(ROOT/'data/resumes');result=lib.action('apply',args.get('version_id'),True)
  return {'ok':True,'sent':False,'status':'waiting_browser','applications':result['applications'],'note':'Queue only. Reviewed immutable resume snapshot required; no remote send performed.'}
 if action=='send-resume':
  if set(args)!={'query','version_id','confirmed'}:return {'ok':False,'sent':False,'error':{'code':'EXPLICIT_VERSION_REQUIRED','message':'请指定query、version_id及confirmed；不发送默认附件'}}
  return resume_tool('attachment-deliver',args)
 raise ValueError('Unknown tool')
def main():
 parser=argparse.ArgumentParser();parser.add_argument('tool',choices=['pipeline','chat-opportunities-sync','chat-opportunities-status','attachment-deliver','attachment-delivery-status','attachment-delete','attachment-inventory','attachment-plan','attachment-upload','greeting-ui-probe','greeting-ui-send','greeting-ui-resume','greeting-web-probe','greeting-web-send','greeting-recheck','greeting-context','greeting-plan','greeting-send','greeting-status','resume-profile','resume-register','resume-tailor-context','resume-tailor','resume-tailor-status','recommend-jobs','tracking-status','tracking-start','tracking-stop','tracking-sync','tracking-generate','tracking-review','capture-greeting','catalog','status','open-login','search','detail','expectations','recommend','captured-search','captured-detail','inspect-har','prepare-application','send-resume']);parser.add_argument('--json',default='{}',help='Arguments as JSON; omit to use --stdin');parser.add_argument('--stdin',action='store_true');ns=parser.parse_args()
 try:
  args=json.load(sys.stdin) if ns.stdin else json.loads(ns.json)
  if not isinstance(args,dict):raise ValueError('Arguments must be an object')
  result=execute(ns.tool,args)
 except Exception as e:result={'ok':False,'error':{'code':'TOOL_FAILED','message':str(e) if isinstance(e,ValueError) else 'Tool failed; no automatic retry.'}}
 print(json.dumps(result,ensure_ascii=False))
if __name__=='__main__':main()
