"""Resolve tailoring inputs from local evidence; never accept model-authored JDs."""
import json
from pathlib import Path

def preferences(library, original_id):
 p=library.root/'tailoring_preferences.json'
 data=json.loads(p.read_text()) if p.exists() else {}
 return data if data.get('source_resume_id')==original_id else {}

def source_version(library, source_resume_id=None):
 if source_resume_id:return library.get(source_resume_id)
 p=library.root/'base.json'
 if p.exists():return library.get(json.loads(p.read_text())['source_resume_id'])
 return next((v for v in reversed(library.load()['versions']) if v['kind']=='original'),None)

def select_job(jobs,query):
 if not isinstance(query,str) or not query.strip():raise ValueError('请指定要定制的岗位或公司')
 q=query.strip().casefold()
 unique={j['job_id']:j for j in jobs if j.get('job_id') and j.get('platform','boss')=='boss'}
 exact=[j for j in unique.values() if q in (str(j.get('job_id','')).casefold(),str(j.get('url','')).casefold())]
 rows=exact or [j for j in unique.values() if ''.join(q.split()) in ''.join((j.get('company','')+' '+j.get('title','')).casefold().split())]
 if len(rows)!=1:raise ValueError('未找到唯一岗位，请提供岗位ID或完整公司及岗位名称')
 job=rows[0]
 if not job.get('jd'):raise ValueError('该岗位缺少完整JD，请先读取岗位详情')
 return job

def tailoring_context(library,root,jobs,query):
 job=select_job(jobs,query);original=source_version(library)
 if not original or original.get('kind')!='original':raise ValueError('请先导入原始Word简历')
 prefs=preferences(library,original['id'])
 template=library.get(prefs['template_version_id']) if prefs.get('template_version_id') else original
 if template['id']!=original['id'] and template.get('source_resume_id')!=original['id']:raise ValueError('格式底稿与原始简历来源不一致')
 return {'job':job,'original':original,'template_version_id':template['id'],
         'confirmed_facts':prefs.get('confirmed_facts',[]),
         'skill':(Path(root)/'skills/boss-tailor-resume/SKILL.md').read_text()}

def start_tailoring(library,root,jobs,tracker,drafts,query):
 ctx=tailoring_context(library,root,jobs,query)
 tracker.register(ctx['job']);drafts.generate(ctx['job']['job_id'],force=True)
 return {'job_id':ctx['job']['job_id'],'status':drafts.status(),'sent':False,'reviewed':False}

def tailoring_status(tracker,drafts):
 return {**drafts.status(),'drafts':[{'job_id':j['job_id'],'version_id':j.get('draft_resume_id'),'review_status':j.get('review_status')} for j in tracker.listing()['jobs'] if j.get('draft_resume_id')],'sent':False}
