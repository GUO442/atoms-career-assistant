# -*- coding: utf-8 -*-
"""Read-only job lifecycle queries over the same records as the management UI."""
from collections import Counter
from datetime import datetime
from career_tracking import STATES,LABELS
from local_chat_tools import target_date,on_date,SHANGHAI

from chat_opportunities import PHASES,ORIGINS,QUALIFICATIONS
FILTER_OPTIONS={k:sorted(v) for k,v in STATES.items()}
FILTER_OPTIONS.update(chat_phase=list(PHASES),contact_initiator=list(ORIGINS),needs_reply=['yes','no','unknown'],chat_qualification=list(QUALIFICATIONS))
FILTER_OPTIONS.update({
 'interview':sorted(STATES['interview']|{'unknown'}),'outcome':sorted(STATES['outcome']|{'unknown'}),
 'screening':['unassessed','recommend','caution','reject','excluded'],
 'review':['none','pending','reviewed'],'customized':['yes','no'],
 'review_status':['none','pending_review','approved','unknown'],
 'resume_kinds':['original','pending','reviewed'],'jd_status':['available','missing'],
 'match_status':['available','missing'],'action_status':['queued','running','unknown','sent','blocked_interface','needs_attention','awaiting_review','drafting','dismissed'],
 'action_kind':['reply_text','send_resume','tailor_resume','notify'],
 'resume_acceptance':['unknown']})
TEXT_FILTERS={'job_id','platform','category','city','batch_id'}
DATE_BASES={'collected','greet','reply','resume','interview','outcome','customized','reviewed'}
NAMES={'chat_phase':'聊天阶段','contact_initiator':'沟通发起方','needs_reply':'待我方回复','chat_qualification':'聊天岗位匹配','greet':'打招呼','reply':'HR回复','resume':'简历发送','interview':'面试','outcome':'结果','screening':'匹配筛选','review':'本人审阅','customized':'岗位定制','review_status':'草稿审阅流程','resume_kinds':'简历版本','jd_status':'完整JD','match_status':'匹配分析','action_status':'待办状态','action_kind':'待办类型','resume_acceptance':'HR简历初筛','platform':'平台','category':'岗位类型','job_id':'岗位ID','city':'城市'}
EXTRA_LABELS={'chat_phase':PHASES,'contact_initiator':ORIGINS,'needs_reply':{'yes':'待回复','no':'无需回复','unknown':'未知'},'chat_qualification':QUALIFICATIONS,'screening':{'unassessed':'待分析','recommend':'符合','caution':'需核实','reject':'不符合','excluded':'规则排除'},'review':{'none':'无定制简历','pending':'有版本待本人审阅','reviewed':'定制版本均已本人审阅'},'customized':{'yes':'已有定制简历','no':'未关联定制简历'},'review_status':{'none':'无草稿流程记录','pending_review':'草稿待本人审阅','approved':'本人已批准草稿','unknown':'草稿流程未知'},'resume_kinds':{'original':'关联原始来源','pending':'有待审阅版本','reviewed':'有已审阅版本'},'jd_status':{'available':'已保存JD','missing':'未保存JD'},'match_status':{'available':'已保存分析','missing':'未保存分析'},'resume_acceptance':{'unknown':'HR初筛未记录'},'action_kind':{'reply_text':'回复消息','send_resume':'发送简历','tailor_resume':'定制简历','notify':'人工提醒'},'action_status':{'queued':'已排队','running':'执行中','unknown':'结果待核验','sent':'已完成发送','blocked_interface':'接口未接通','needs_attention':'需人工处理','awaiting_review':'待本人审阅','drafting':'草稿处理中','dismissed':'已忽略'}}

def label(key,value):return {**LABELS.get(key,{}),**EXTRA_LABELS.get(key,{})}.get(value,'状态未知' if value=='unknown' else value)

def validate_args(args):
 if not isinstance(args,dict) or set(args)!={'query','filters','date','date_basis','include_history'}:raise ValueError('岗位状态参数结构无效')
 if not isinstance(args['query'],str) or len(args['query'])>200 or not isinstance(args['filters'],dict) or type(args['include_history'])!=bool:raise ValueError('岗位查询条件类型无效')
 if not isinstance(args['date_basis'],str) or args['date_basis'] not in DATE_BASES:raise ValueError('状态时间口径无效')
 # Date strings are checked without silently accepting malformed or naive dates.
 if not isinstance(args['date'],str):raise ValueError('查询日期无效')
 try:
  parsed_date=target_date(args['date'])
  if args['date'] not in ('all','today','yesterday') and str(parsed_date)!=args['date']:raise ValueError('日期格式无效')
 except (ValueError,TypeError):raise ValueError('查询日期无效')
 for key,value in args['filters'].items():
  if key not in FILTER_OPTIONS and key not in TEXT_FILTERS:raise ValueError('未知岗位状态维度：'+key)
  values=value if isinstance(value,list) else [value]
  if not values or len(values)>20 or any(not isinstance(v,str) or not v or len(v)>80 for v in values):raise ValueError('状态筛选值无效')
  if key in FILTER_OPTIONS and any(v not in FILTER_OPTIONS[key] for v in values):raise ValueError('非法状态值：'+key)
 return args

def query(jobs,versions,actions,args,history=None,now=None):
 validate_args(args);target=target_date(args['date'],now);rows=[];unknown_dates=0;matched=[]
 for j in jobs:
  related=[v for v in versions if v.get('kind')=='tailored' and (v.get('job',{}).get('job_id')==j['job_id'] or (v.get('job',{}).get('url') and v['job']['url']==j.get('url'))) and v.get('job',{}).get('platform','boss')==j.get('platform','boss')]
  tasks=[a for a in actions if a['job_id']==j['job_id'] and j.get('platform','boss')=='boss']
  states={k:j.get(k,'unknown') for k in STATES}
  recorded=j.get('recorded_states')
  if recorded is not None:
   for k in STATES:
    if not recorded.get(k):states[k]='unknown'
  states.update({k:j.get(k,'unknown' if k!='chat_qualification' else 'unassessed') for k in ('chat_phase','contact_initiator','needs_reply','chat_qualification','screening','review','resume_kinds','platform','category','city','batch_id')})
  states.update(customized='yes' if related else 'no',review_status=j.get('review_status','none'),jd_status='available' if j.get('jd') else 'missing',match_status='available' if j.get('match') else 'missing',resume_acceptance='unknown',job_id=j['job_id'])
  q=args['query'].strip().casefold()
  haystack=' '.join(str(j.get(k,'')) for k in ('title','company','city','job_id','url')).casefold()
  if q and not all(term in haystack for term in q.split()):continue
  ok=True
  for key,wanted in args['filters'].items():
   wanted=wanted if isinstance(wanted,list) else [wanted]
   if key=='action_status' or key=='action_kind':continue
   actual=states.get(key)
   if not any(v in actual if isinstance(actual,list) else v==actual for v in wanted):ok=False;break
  if not ok:continue
  # Action kind and status must match the SAME action, not unrelated rows.
  selected_tasks=tasks
  for key,field in [('action_kind','kind'),('action_status','status')]:
   if key in args['filters']:
    wanted=args['filters'][key];wanted=wanted if isinstance(wanted,list) else [wanted]
    selected_tasks=[a for a in selected_tasks if a[field] in wanted]
  if any(k in args['filters'] for k in ('action_kind','action_status')) and not selected_tasks:continue
  basis=args['date_basis'];times=[]
  if basis=='collected':times=[j.get('first_seen_at')]
  elif basis in STATES:
   stamp=j.get('dimension_times',{}).get(basis)
   if type(stamp) in (int,float):
    try:times=[datetime.fromtimestamp(stamp,SHANGHAI).isoformat()]
    except (ValueError,OverflowError,OSError):pass
  elif basis=='customized':times=[v.get('created') for v in related]
  elif basis=='reviewed':times=[v.get('reviewed_at') for v in related if v.get('reviewed') and v.get('sha256') and v.get('reviewed_sha256')==v['sha256']]
  if target:
   checks=[on_date(t,target) for t in times]
   if True not in checks:
    if not checks or None in checks:unknown_dates+=1
    continue
  public_versions=[{k:v.get(k) for k in ('id','name','created','reviewed_at')}|{'reviewed':bool(v.get('reviewed') and v.get('sha256') and v.get('reviewed_sha256')==v['sha256'])} for v in related]
  row={k:j.get(k) for k in ('job_id','management_id','platform','title','company','city','url','first_seen_at','draft_resume_id')}
  row.update(states=states,labels={k:label(k,v) for k,v in states.items() if isinstance(v,str)},resume_versions=public_versions,action_records=[{k:a.get(k) for k in ('id','kind','status')} for a in selected_tasks],dimension_times=j.get('dimension_times',{}))
  if args['include_history'] and history and j.get('platform','boss')=='boss':
   row['history']=[{'kind':e['kind'],'value':e['value'],'at':e['at'],'source':e.get('evidence',{}).get('source')} for e in history(j['job_id'])[:20]]
  rows.append(row);matched.append(states)
 distributions={key:dict(Counter(s.get(key,'unknown') for s in matched)) for key in ('greet','reply','resume','interview','outcome','screening','review','customized')}
 text=f'符合查询条件共 {len(rows)} 个岗位（本机总计 {len(jobs)} 个）。'
 if target:text+=f'\n日期：北京时间 {target}；口径：'+('首次入库时间' if args['date_basis']=='collected' else '定制简历保存时间' if args['date_basis']=='customized' else '有效审阅时间' if args['date_basis']=='reviewed' else '当前'+NAMES[args['date_basis']]+'状态的最近记录时间')+'。'
 keys=('chat_phase','contact_initiator','needs_reply','chat_qualification','screening','greet','reply','customized','review','review_status','resume','interview','outcome','jd_status','match_status')
 if rows:
  text+='\n\n'+'\n\n'.join(f"{i+1}. {r.get('company','')} · {r.get('title','')}\n"+'；'.join(NAMES[k]+'：'+r['labels'].get(k,'未知') for k in keys)+(('\n定制版本：'+str(len(r['resume_versions']))+'份') if r['resume_versions'] else '')+(('\n待办：'+'；'.join(label('action_kind',a['kind'])+' / '+label('action_status',a['status']) for a in r['action_records'])) if r['action_records'] else '')+(('\n附最近'+str(len(r.get('history',[])))+'条脱敏状态变动记录（详情见工具结果）') if args['include_history'] else '') for i,r in enumerate(rows[:30]))
 if len(rows)>30:text+='\n仅展示前30项，完整记录可在岗位管理查看。'
 if unknown_dates:text+=f'\n另有 {unknown_dates} 个符合状态条件的岗位缺少该口径时间，未计入日期结果。'
 text+='\n\n“本人审阅通过”不等于“HR简历初筛通过”；目前HR初筛结果未单独记录。以上为已保存状态，未知和待核验不代表已完成。'
 return {'answer':text,'tool_results':[{'tool':'jobs.status','arguments':args,'count':len(rows),'total':len(jobs),'jobs':rows,'distributions':distributions,'unknown_dates':unknown_dates,'history_limit_per_job':20,'notes':['查询不执行打招呼、发送、定制或修改状态','初始状态不等于远端实时核验','HR简历初筛结果未单独记录']}]}
