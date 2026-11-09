# -*- coding: utf-8 -*-
"""Local job/version ledger with immutable review and dispatch snapshots."""
import base64, hashlib, io, json, threading, uuid, zipfile
from datetime import datetime, timezone
from pathlib import Path
from xml.etree import ElementTree as ET

class Library:
 def __init__(self, root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.file=self.root/'ledger.json';self.lock=threading.RLock()
 def load(self):return json.loads(self.file.read_text()) if self.file.exists() else {'versions':[],'applications':[]}
 def put(self,d):
  p=self.file.with_suffix('.tmp');p.write_text(json.dumps(d,ensure_ascii=False));p.chmod(0o600);p.replace(self.file)
 def add(self,name,body,job=None,kind='original'):
  if not name.lower().endswith('.docx'):raise ValueError('请导入 Word .docx 文件')
  if len(body)>8_000_000:raise ValueError('Word 文件不能超过 8MB')
  try:
   with zipfile.ZipFile(io.BytesIO(body)) as z:
    info=z.getinfo('word/document.xml')
    if info.file_size>5_000_000:raise ValueError('Word 正文过大')
    tree=ET.fromstring(z.read(info));ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
    text='\n'.join(''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in tree.findall('.//w:p',ns))
  except (zipfile.BadZipFile,KeyError,ET.ParseError):raise ValueError('无法读取此 Word 文件')
  if not text.strip():raise ValueError('Word 中未找到正文')
  with self.lock:
   d=self.load();key=uuid.uuid4().hex;path=self.root/(key+'.docx');path.write_bytes(body);path.chmod(0o600)
   v={'id':key,'name':Path(name).name,'text':text,'sha256':hashlib.sha256(body).hexdigest(),'kind':kind,'job':job or {},'created':datetime.now(timezone.utc).isoformat(),'reviewed':False}
   d['versions'].append(v);self.put(d);return v
 def get(self,key):
  for v in self.load()['versions']:
   if v['id']==key:return v
  raise ValueError('简历版本不存在')
 def add_tailored(self,name,body,job,source_resume_id):
  from urllib.parse import urlsplit
  import re
  if not isinstance(job,dict):raise ValueError('需要已核验的岗位资料')
  url=urlsplit(job.get('url',''))
  match=re.fullmatch(r'/job_detail/([A-Za-z0-9_-]+)\.html',url.path)
  if url.scheme!='https' or url.hostname!='www.zhipin.com' or not match or job.get('job_id')!=match.group(1):raise ValueError('岗位ID与BOSS链接不一致')
  for key in ('title','company','jd','source','collected_at'):
   if not isinstance(job.get(key),str) or not job[key].strip():raise ValueError('岗位资料缺少 '+key)
  clean={k:job[k] for k in ('job_id','title','company','jd','source','collected_at')}
  for key in ('city','salary','experience','education'):
   if isinstance(job.get(key),str):clean[key]=job[key]
  clean['url']='https://www.zhipin.com'+url.path
  with self.lock:
   original=self.get(source_resume_id)
   if original.get('kind')!='original':raise ValueError('事实来源必须是原始简历版本')
   sha=hashlib.sha256(body).hexdigest()
   for version in self.load()['versions']:
    if version.get('kind')=='tailored' and version.get('source_resume_id')==source_resume_id and version.get('sha256')==sha and version.get('job',{}).get('job_id')==clean['job_id']:return version
   version=self.add(name,body,clean,'tailored')
   data=self.load();saved=next(v for v in data['versions'] if v['id']==version['id'])
   saved['source_resume_id']=source_resume_id
   self.put(data)
   return saved
 def action(self,action,key,confirmed=False):
  with self.lock:
   d=self.load();v=next((x for x in d['versions'] if x['id']==key),None)
   if not v:raise ValueError('简历版本不存在')
   if action=='review':
    if not confirmed:raise ValueError('请阅读简历后勾选审阅确认')
    v['reviewed']=True;v['reviewed_sha256']=v['sha256'];v['reviewed_at']=datetime.now(timezone.utc).isoformat()
   elif action=='apply':
    if not confirmed or not v['reviewed'] or v.get('reviewed_sha256')!=v['sha256']:raise ValueError('必须先审阅该版本，再明确确认投递')
    if not v['job'].get('url','').startswith('https://www.zhipin.com/job_detail/') or not v['job'].get('jd'):raise ValueError('该简历未关联有效 BOSS 岗位和 JD')
    if any(a['version_id']==key for a in d['applications']):raise ValueError('该版本已有投递请求，请先查看台账，避免重复')
    d['applications'].append({'id':uuid.uuid4().hex,'version_id':key,'resume_name':v['name'],'sha256':v['sha256'],'job':v['job'],'status':'waiting_browser','greet_status':'not_requested','resume_status':'not_sent','created':datetime.now(timezone.utc).isoformat(),'note':'用户已审阅并确认；等待 BOSS 浏览器执行通道。尚未联系或发送附件。'})
   else:raise ValueError('未知操作')
   self.put(d);return d
