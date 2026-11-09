# -*- coding: utf-8 -*-
"""Typed local read tools. Unsupported time semantics are never substituted."""
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
SHANGHAI=ZoneInfo("Asia/Shanghai")

def target_date(value,now=None):
 now=(now or datetime.now(SHANGHAI)).astimezone(SHANGHAI)
 if value=='all':return None
 if value in ('today','yesterday'):return now.date()-timedelta(days=value=='yesterday')
 return datetime.strptime(value,'%Y-%m-%d').date()

def on_date(value,target):
 if not target:return True
 try:
  dt=datetime.fromisoformat(value.replace('Z','+00:00'))
  if dt.tzinfo is None:return None
  return dt.astimezone(SHANGHAI).date()==target
 except (ValueError,TypeError,AttributeError):return None

def resume_list(versions,args,now=None):
 target=target_date(args['date'],now)
 if args['basis']=='screened':
  return {'answer':'你问的是简历的筛选结果。当前台账只有入库时间和审阅记录，没有“筛选完成时间”，无法可靠统计'+(str(target)+' 当天' if target else '')+'筛选过或筛选通过的简历。\n\n你是想查看已保存的简历，还是已筛选的岗位？',
          'tool_results':[{'tool':'resume.list','arguments':args,'status':'unsupported_basis','versions':[]}]}
 rows=[];unknown=0
 for v in versions:
  if args['kind']!='all' and v.get('kind')!=args['kind']:continue
  reviewed=bool(v.get('reviewed') and v.get('sha256') and v.get('reviewed_sha256')==v['sha256'])
  if args['reviewed']=='yes' and not reviewed:continue
  if args['reviewed']=='no' and reviewed:continue
  if args['basis']=='reviewed' and not reviewed:continue
  timestamp=v.get('reviewed_at' if args['basis']=='reviewed' else 'created')
  match=on_date(timestamp,target)
  if match is None:unknown+=1;continue
  if not match:continue
  rows.append({k:v.get(k) for k in ('id','name','kind','created','reviewed_at')}|{'reviewed':reviewed})
 basis='审阅确认' if args['basis']=='reviewed' else '入库保存'
 text=(f'按北京时间 {target} 的{basis}记录查询' if target else f'按本机{basis}记录查询')+f'，符合条件共 {len(rows)} 份简历。'
 if rows:text+='\n\n'+'\n'.join(f"{i+1}. {r['name']}（{'原始简历' if r['kind']=='original' else '岗位定制版'} · {'已审阅' if r['reviewed'] else '待审阅'}）" for i,r in enumerate(rows))
 elif not versions:text+='\n暂无已保存简历。'
 if unknown:text+=f'\n{unknown} 份缺少可靠的{basis}时间，未计入日期结果。'
 return {'answer':text,'tool_results':[{'tool':'resume.list','arguments':args,'date':str(target) if target else None,'timezone':'Asia/Shanghai','count':len(rows),'versions':rows,'unknown_dates':unknown}]}

def jobs_list(jobs,args,now=None):
 target=target_date(args['date'],now)
 if args['basis']=='screened' and target:
  return {'answer':f'岗位库没有筛选完成时间，无法可靠统计北京时间 {target} 当天筛选的岗位。可以查询当天首次入库的岗位，或不限定日期查看当前筛选结果。你希望按哪种口径查看？',
          'tool_results':[{'tool':'jobs.list','arguments':args,'status':'unsupported_basis','jobs':[]}]}
 rows=[];unknown=0
 labels={'unassessed':'待分析','recommend':'符合','caution':'需核实','reject':'不符合','excluded':'规则排除'}
 for j in jobs:
  if args['basis']=='screened' and j.get('screening','unassessed')=='unassessed':continue
  if args['screening']!='all' and j.get('screening')!=args['screening']:continue
  match=on_date(j.get('first_seen_at'),target)
  if match is None:unknown+=1;continue
  if not match:continue
  rows.append({k:j.get(k) for k in ('job_id','title','company','city','url','screening','first_seen_at')})
 text=(f'按北京时间 {target} 首次入库时间查询' if target else '按本机当前岗位记录查询')+f'，符合条件共 {len(rows)} 个岗位。'
 if args['basis']=='screened' and target is None:
  pending=sum(j.get('screening','unassessed')=='unassessed' for j in jobs)
  text=f'本机共有 {len(jobs)} 个岗位，其中 {len(jobs)-pending} 个已有匹配或排除结论，{pending} 个待分析。当前查询条件匹配 {len(rows)} 个已有结论的岗位。'
 text+='\n\n'+'\n'.join(f"{i+1}. {j.get('company','')} · {j.get('title','')}（{labels.get(j.get('screening'),'未知')}）" for i,j in enumerate(rows[:30])) if rows else ''
 if len(rows)>30:text+='\n仅展示前30项，完整记录可在岗位管理查看。'
 if unknown:text+=f'\n另有 {unknown} 个岗位缺少可靠入库时间，未计入。'
 return {'answer':text,'tool_results':[{'tool':'jobs.list','arguments':args,'count':len(rows),'jobs':rows,'unknown_dates':unknown}]}
