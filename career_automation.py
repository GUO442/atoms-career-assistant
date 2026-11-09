# -*- coding: utf-8 -*-
"""Local per-job resume drafts; approval is required before attachment dispatch."""
import io,threading,time,re,json
class DraftService:
 def __init__(self,tracker,library,model):self.tracker=tracker;self.library=library;self.model=model;self.active=set();self.lock=threading.RLock();self.errors={}
 def generate(self,job_id,force=False):
  with self.lock:
   if job_id in self.active:return
   job=next((j for j in self.tracker.listing()['jobs'] if j['job_id']==job_id),None)
   if not job or not job.get('jd'):raise ValueError('该岗位缺少完整JD，请先读取岗位详情')
   if not force and job.get('draft_resume_id') and job.get('review_status')=='pending_review':return
   self.active.add(job_id);self.errors.pop(job_id,None)
   threading.Thread(target=self.work,args=(job,),daemon=True).start()
 def work(self,job):
  try:
   from resume_tailoring import tailor
   v=tailor(self.library,self.model,job)
   self.tracker.attach_draft(job['job_id'],v['id'])
   with self.tracker.connect() as c:c.execute('UPDATE actions SET status="awaiting_review" WHERE job_id=? AND kind="tailor_resume"',(job['job_id'],))
  except Exception as exc:self.errors[job['job_id']]=str(exc)
  finally:
   with self.lock:self.active.discard(job['job_id'])
 def process(self):
  if not self.tracker.policy()['enabled']:return
  for a in self.tracker.listing()['actions']:
   if a['kind']!='tailor_resume' or a['status']!='queued':continue
   try:self.generate(a['job_id']);status='drafting';error=''
   except Exception as exc:status='needs_attention';error=str(exc)
   with self.tracker.connect() as c:c.execute('UPDATE actions SET status=? WHERE id=?',(status,a['id']))
 def status(self):return {'generating':list(self.active),'errors':dict(self.errors)}
