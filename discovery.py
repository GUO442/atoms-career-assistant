# -*- coding: utf-8 -*-
"""BOSS query workflow. Source IDs are retained; failures never become job data."""
import json,re,threading,sqlite3
from pathlib import Path
from datetime import datetime,timezone
FILTER_VERSION='ai-salary-direct-v1'
# Explicit source fields only: numeric platform enums remain uninterpreted.
JOB_POLICY_FIELDS=('isClosed','is_closed','jobClosed','jobStatus','job_status','jobStatusDesc','statusDesc','status_text','payType','pay_type','salaryUnit','salary_unit','settlementType')
def policy_metadata(source):
 return {k:source[k] for k in JOB_POLICY_FIELDS if k in source and type(source[k]) in (str,bool,int,float)}
def hard_exclusion(job):
 for k in ('isClosed','is_closed','jobClosed'):
  if job.get(k) is True:return '岗位已关闭'
 for k in ('jobStatus','job_status','jobStatusDesc','statusDesc','status_text'):
  v=str(job.get(k,'')).strip().lower()
  if v in ('closed','offline','expired','已关闭','已下线','停止招聘','招聘结束','已结束','已过期','职位已关闭','职位已下线'):return '岗位已关闭'
 if re.search(r'(?:该|本)?(?:岗位|职位)(?:已关闭|已下线|已过期|已停止招聘)|(?:停止招聘|招聘结束)[）)]?$',str(job.get('title',''))+' '+str(job.get('jd',''))):return '岗位已关闭'
 for k in ('payType','pay_type','salaryUnit','salary_unit','settlementType'):
  if str(job.get(k,'')).strip().lower() in ('daily','day','日','天','日结','日薪','按日','按天'):return '日结或按日计薪岗位'
 salary=str(job.get('salary') or '')
 text=salary+' '+str(job.get('title') or '')+' '+str(job.get('jd') or '')
 text=re.sub(r'(?:不是|并非|非|不支持|不接受|不提供|不采用)\s*(?:日结|日薪|按日计薪|按天计薪)','',text)
 if re.search(r'日薪|按[日天]计薪|按[日天]结算|日结(?!算系统|算平台|算模块|算业务)|(?:元|\d)\s*[/／]\s*[天日]',text):return '日结或按日计薪岗位'
 return None
def classify_job(job):
 reason=hard_exclusion(job)
 if reason:return 'excluded',reason
 title=str(job.get('title') or '')
 jd=str(job.get('jd') or '')
 internship=r'实习|\bintern(?:ship)?\b'
 unrelated=r'销售|客服|行政|人事|招聘专员|商务拓展|市场营销|新媒体|直播|带货|标注|产品经理|项目经理'
 technical=r'测试主管|测试总监|测试经理|测试负责人|质量保障|软件|程序|前端|后端|全栈|测试开发|测开|软件测试|自动化测试|测试工程师|AI测试|AI测评|大模型评测|算法工程师|数据工程师|数据开发|运维|网络工程师|信息安全|网络安全|\b(?:java|python|golang|devops|sre|qa|sdet|frontend|backend|full.?stack)\b|c\+\+|(?:AI|Agent|大模型|人工智能|RAG|LLM|智能体).*(?:开发|工程师|测试|评测|研发)|(?:开发|研发).*(?:工程师|AI|Agent|大模型|智能体)'
 if re.search(internship,title,re.I) or re.search(r'职位类型[：:]?\s*实习|岗位性质[：:]?\s*实习|实习岗位|招聘实习生',jd):return 'excluded','实习岗位'
 if re.search(r'AI|人工智能|大模型|智能体|\b(?:agent|rag|llm|aigc)\b',title+' '+jd,re.I):return 'included','AI相关岗位'
 if re.search(unrelated,title,re.I):return 'excluded','非目标IT技术岗位'
 if re.search(technical,title,re.I):return 'included','岗位名称明确属于IT开发、测试或AI技术方向'
 return 'excluded','无法确认属于目标IT技术方向'

class Discovery:
 def __init__(self,root,query,model,platform='boss'):
  self.path=Path(root)/'discovery.json';self.query=query;self.model=model;self.platform=platform;self.lock=threading.RLock()
  self.db_path=Path(root)/'jobs.sqlite3';self.db_path.parent.mkdir(parents=True,exist_ok=True)
  with self.connect() as c:
   c.execute("CREATE TABLE IF NOT EXISTS jobs(platform TEXT NOT NULL,job_id TEXT NOT NULL,data TEXT NOT NULL,PRIMARY KEY(platform,job_id))")
   c.execute("CREATE TABLE IF NOT EXISTS state(platform TEXT PRIMARY KEY,data TEXT NOT NULL)")
   cols=[r[1] for r in c.execute('PRAGMA table_info(state)').fetchall()]
   if cols and cols[0]!='platform':
    legacy=None
    try:legacy=c.execute('SELECT data FROM state WHERE id=1').fetchone()
    except Exception:legacy=None
    c.execute('DROP TABLE state');c.execute('CREATE TABLE state(platform TEXT PRIMARY KEY,data TEXT NOT NULL)')
    if legacy:c.execute('INSERT OR REPLACE INTO state VALUES(?,?)',('boss',legacy[0]))
   migrated=c.execute('SELECT 1 FROM state WHERE platform=?',(platform,)).fetchone()
  self.db_path.chmod(0o600)
  if not migrated:
   legacy=json.loads(self.path.read_text()) if (self.path.exists() and platform=='boss') else {'jobs':[],'status':'idle','note':'尚未执行查询'}
   self.put(legacy)
  with self.lock,self.connect() as c:
   for (pf,raw) in c.execute('SELECT platform,data FROM jobs').fetchall():
    job=json.loads(raw);job.setdefault('platform',pf);self._save_job(c,job)
  self.put(self.load())
 def connect(self):return sqlite3.connect(self.db_path,timeout=15)
 def load(self):
  with self.lock,self.connect() as c:
   row=c.execute('SELECT data FROM state WHERE platform=?',(self.platform,)).fetchone()
   return json.loads(row[0]) if row else {'jobs':[],'status':'idle','note':'尚未执行查询'}
 def _save_job(self,c,job,refresh=False):
  key=job.get('job_id','')
  if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',key):raise ValueError('岗位ID无效')
  platform=job.get('platform') or self.platform
  row=c.execute('SELECT data FROM jobs WHERE platform=? AND job_id=?',(platform,key)).fetchone()
  old=json.loads(row[0]) if row else {}
  now=datetime.now(timezone.utc).isoformat()
  merged={**old,**job}
  if refresh:
   for field in ('jd','match','decision','status'):
    if field in old:merged[field]=old[field]
  merged.update(first_seen_at=old.get('first_seen_at',now),last_seen_at=now if refresh or not old else old.get('last_seen_at',now),is_new=not bool(old) if refresh else job.get('is_new',old.get('is_new',False)),platform=platform)
  eligibility,reason=classify_job(merged)
  merged.update(eligibility=eligibility,filter_reason=reason,filter_version=FILTER_VERSION)
  c.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?)',(platform,key,json.dumps(merged,ensure_ascii=False)))
  return merged
 def put(self,d,refresh=False):
  with self.lock,self.connect() as c:
   unique={}
   for job in d.get('jobs',[]):
    p=job.get('platform') or self.platform
    unique.setdefault((p,job['job_id']),job)
   saved=[self._save_job(c,j,refresh) for j in unique.values()]
   if refresh:
    d['new_count']=sum(j['is_new'] for j in saved);d['seen_count']=len(saved)-d['new_count']
    d['received_count']=len(saved);d['duplicate_count']=d['seen_count']
    d['filtered_count']=sum(j['is_new'] and j['eligibility']=='excluded' for j in saved)
    d['jobs']=[j for j in saved if j['is_new'] and j['eligibility']=='included']
    d['eligible_count']=len(d['jobs'])
    d['note']=f"本次获取 {len(saved)} 个岗位，已跳过 {d['seen_count']} 个历史重复岗位，新增 {d['new_count']} 个，其中排除 {d['filtered_count']} 个，仅保留 {d['eligible_count']} 个明确符合方向的非实习岗位。"
   else:d['jobs']=[j for j in saved if j['eligibility']=='included']
   c.execute('INSERT OR REPLACE INTO state VALUES(?,?)',(self.platform,json.dumps(d,ensure_ascii=False)))
 def update_job(self,job_id,fields):
  """Merge squad-owned fields (node/reason/...) into the stored job snapshot."""
  if not isinstance(job_id,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',job_id):raise ValueError('岗位ID无效')
  if not isinstance(fields,dict):raise ValueError('更新字段必须是对象')
  with self.lock,self.connect() as c:
   row=c.execute('SELECT data FROM jobs WHERE platform=? AND job_id=?',(self.platform,job_id)).fetchone()
   if not row:return False
   job=json.loads(row[0]);job.update({k:v for k,v in fields.items() if v is not None});job['updated_at']=time.time()
   c.execute('UPDATE jobs SET data=? WHERE platform=? AND job_id=?',(json.dumps(job,ensure_ascii=False),self.platform,job_id))
   return True
 def history(self):
  with self.lock,self.connect() as c:
   jobs=[json.loads(r[0]) for r in c.execute('SELECT data FROM jobs ORDER BY rowid DESC')]
  return {'jobs':jobs,'total':len(jobs)}
 def import_jobs(self,jobs):
  with self.lock,self.connect() as c:
   for job in jobs:
    key=job.get('job_id','')
    if not isinstance(key,str) or not re.fullmatch(r'[A-Za-z0-9._:-]{1,128}',key):continue
    platform=job.get('platform') or self.platform
    old=c.execute('SELECT data FROM jobs WHERE platform=? AND job_id=?',(platform,key)).fetchone()
    # Imported snapshots fill gaps without replacing newer query or assessment data.
    existing=json.loads(old[0]) if old else {}
    self._save_job(c,{**{k:v for k,v in job.items() if v not in ('',None)},**existing,**policy_metadata(job),**({'salary':job['salary']} if job.get('salary') else {}),**({'platform':platform})})
 def call(self,name,args):
  result=self.query(name,args)
  if not result.get('ok'):
   error=result.get('error') or {};code=error.get('code','QUERY_FAILED');raise ValueError(str(code)+'：'+str(error.get('message','查询失败'))+'；已停止，不自动重试。')
  return result.get('data')
 def search(self,query,city):
  if not isinstance(query,str) or not query.strip() or not isinstance(city,str) or not city.strip():raise ValueError('请填写关键词和城市')
  with self.lock:
   d=self.load()
   try:
    data=self.call('search',{'query':query,'city':city,'page':1})
    items=data if isinstance(data,list) else (data or {}).get('items',[])
    if not isinstance(items,list):raise ValueError('未识别查询结果格式')
    jobs=[];seen=set()
    for item in items:
     key=item.get('job_id','')
     if not re.fullmatch(r'[A-Za-z0-9_-]+',key) or key in seen:continue
     seen.add(key);jobs.append({k:item.get(k,'') for k in ('job_id','title','company','city','salary','experience','education','security_id','lid')})
     jobs[-1].update(policy_metadata(item))
     jobs[-1].update(url='https://www.zhipin.com/job_detail/'+key+'.html',jd='',match='',status='listed',source='boss_web_api',collected=datetime.now(timezone.utc).isoformat())
     if len(jobs)>=10:break
    d={'jobs':jobs,'status':'searched','query':query,'city':city,'note':'本次返回 '+str(len(jobs))+' 个岗位；尚未读取JD和判断个人匹配。'};self.put(d,refresh=True);return d
   except ValueError as e:
    d.update(status='blocked',note=str(e));self.put(d);raise
 def recommend(self,kind='featured',expect_id=None):
  with self.lock:
   args={'kind':kind}
   if expect_id is not None:args['expect_id']=expect_id
   data=self.call('recommend',args)
   if not isinstance(data,dict) or not isinstance(data.get('items'),list):raise ValueError('推荐岗位响应结构无效')
   jobs=[{**j,'jd':'','match':'','status':'listed'} for j in data['items']]
   result={'jobs':jobs,'status':'searched','kind':kind,'expectation':data.get('expectation'),'default_expectation':data.get('default_expectation'),'note':'已读取'+str(len(jobs))+'个推荐岗位，尚未分析匹配'}
   self.put(result,refresh=True);return result
 def read_detail(self,key):
  with self.lock:
   d=self.load();job=next((j for j in d['jobs'] if j['job_id']==key),None)
   if not job:raise ValueError('未找到本次查询的岗位')
   if not job.get('security_id'):raise ValueError('岗位缺少详情查询标识，需在BOSS页面核验')
   data=self.call('detail',{'job_id':job['job_id'],'security_id':job['security_id'],'lid':job.get('lid','')})
   if not isinstance(data,dict) or not data.get('description'):raise ValueError('未获得完整JD，不能生成简历')
   if data.get('job_id') and data['job_id']!=key:raise ValueError('详情与查询岗位不一致，已停止')
   job.update(policy_metadata(data))
   if data.get('salary'):job['salary']=data['salary']
   job['jd']=data['description'];job['status']='matched' if job.get('match') else 'jd_ready';self.put(d)
   eligibility,reason=classify_job(job)
   if eligibility=='excluded':raise ValueError('岗位已排除：'+reason)
   return job
 def detail(self,key,resume,preferences,consent):
  if not consent:raise ValueError('请同意将简历与JD发送模型')
  if not resume.strip():raise ValueError('请先导入真实简历')
  with self.lock:
   d=self.load();job=next((j for j in d['jobs'] if j['job_id']==key),None)
   if not job:raise ValueError('未找到本次查询的岗位')
   self.read_detail(key)
   d=self.load();job=next(j for j in d['jobs'] if j['job_id']==key)
   from matching_policy import assess
   parsed=assess(job,preferences);decision=parsed['decision'];analysis=parsed['analysis']
   job['match']=analysis;job['decision']=decision;job['status']='matched';self.put(d);return job
