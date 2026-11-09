"""BOSS attachment slots: read inventory, bind immutable versions, explicit UI writes.

Chat attachment requests are handled by resume_delivery_workflow. Plan is read-only.
"""
import hashlib,json,re,threading
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from runtime_paths import WORKSPACE
LOCK=threading.RLock()
NS='http://schemas.openxmlformats.org/wordprocessingml/2006/main'

@contextmanager
def page_session():
 from patchright.sync_api import sync_playwright
 import boss_web
 # Use the existing browser; do not extract its credentials.
 with sync_playwright() as p:
  b=p.chromium.connect_over_cdp(boss_web.DEBUG)
  context=b.contexts[0]
  candidates=[p for p in context.pages if urlsplit(p.url).hostname=='www.zhipin.com' and urlsplit(p.url).path=='/web/geek/resume']
  owned=not candidates
  page=context.new_page() if owned else candidates[0]
  try:
   if owned:page.goto('https://www.zhipin.com/web/geek/resume',wait_until='domcontentloaded',timeout=30000)
   page.locator('.resume-attachment .resume-type-title').wait_for(timeout=15000)
   body=page.locator('body').inner_text()
   if any(s in body for s in ('请完成以下验证','访问受限','操作过于频繁')):raise ValueError('平台验证阻塞；停止，不自动重试')
   yield page
  finally:
   if owned:page.close()

def inventory(page=None):
 if page is None:
  with page_session() as p:return inventory(p)
 area=page.locator('.resume-attachment')
 m=re.search(r'文件[（(](\d+)\s*/\s*(\d+)[）)]',area.inner_text())
 if not m:raise ValueError('无法核验附件库容量')
 items=[]
 for item in area.locator('.annex-item').all():
  link=item.locator('.basis a[title]')
  download=item.locator('a[type=download]')
  if link.count()!=1 or download.count()!=1:raise ValueError('附件行结构变化，停止')
  ids=parse_qs(urlsplit(download.get_attribute('href')).query).get('resumeId',[])
  if len(ids)!=1:raise ValueError('附件标识无法核验')
  items.append({'remote_id':ids[0],'name':link.get_attribute('title')})
 if len(items)!=int(m[1]):raise ValueError('附件数量与页面不一致')
 return {'count':int(m[1]),'capacity':int(m[2]),'items':items,'source':'live_visible_resume_page'}

def slot_plan(version,snapshot,bindings=None,protected=()):
 """Unknown files are never automatically evicted; latest is not an identity."""
 bindings=bindings or {}
 same=[i for i in snapshot['items'] if bindings.get(i['remote_id'],{}).get('sha256')==version['sha256']]
 if len(same)>1:raise ValueError('同一文件绑定多个远端附件，请先核对')
 if same:return {'action':'reuse','attachment':same[0]}
 if any(i['name']==version['name'] for i in snapshot['items']):return {'action':'verify_existing','reason':'同名文件未核验指纹，不能当作目标版本'}
 if snapshot['count']<snapshot['capacity']:return {'action':'upload','delete_required':False}
 candidates=[i for i in snapshot['items'] if i['remote_id'] in bindings and i['remote_id'] not in protected]
 return {'action':'choose_replacement','delete_required':True,'candidates':candidates,'reason':'满额；仅已登记且未受保护附件可作为候选，不自动删除未知文件'}

def records(root):
 from delivery_store import load_state
 return load_state(root)

def save(root,data):
 from delivery_store import save_state
 save_state(root,data)
 # A readable compatibility export; the transactional database is authoritative.
 p=Path(root)/'data/resume-delivery.json'
 tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False));tmp.chmod(0o600);tmp.replace(p)

def version_for(library,job_id,version_id):
 v=library.get(version_id)
 if v['kind']!='tailored' or v.get('job',{}).get('job_id')!=job_id:raise ValueError('必须使用该岗位的定制版本')
 body=(library.root/(v['id']+'.docx')).read_bytes()
 if hashlib.sha256(body).hexdigest()!=v['sha256']:raise ValueError('本地文件指纹变化，停止')
 return v

def plan(library,job_id,version_id,root=WORKSPACE,snapshot=None):
 with LOCK:
  v=version_for(library,job_id,version_id);data=records(root)
  protected={o['remote_id'] for o in data['operations'] if o.get('remote_id') and o['status'] in ('pending','unknown')}
  active_versions={a.get('version_id') for a in library.load().get('applications',[]) if a.get('status') not in ('sent','cancelled','failed')}
  protected.update(remote for remote,binding in data['bindings'].items() if binding.get('version_id') in active_versions)
  snap=inventory() if snapshot is None else snapshot
  return {'job_id':job_id,'version_id':v['id'],'filename':v['name'],'sha256':v['sha256'],
          'reviewed':bool(v.get('reviewed') and v.get('reviewed_sha256')==v['sha256']),
          'inventory':snap,'slot_plan':slot_plan(v,snap,data['bindings'],protected),
          'attachment_sender':'browser_ui_request_live_verified_20261030','sent':False}

def require_review(v,confirmed):
 if confirmed is not True:raise ValueError('本次操作需要明确确认指定附件版本')
 if not v.get('reviewed') or v.get('reviewed_sha256')!=v['sha256']:raise ValueError('请先审阅并确认这个具体版本')

def upload(library,job_id,version_id,confirmed=False,root=WORKSPACE):
 with LOCK:
  v=version_for(library,job_id,version_id);require_review(v,confirmed);data=records(root)
  # Serialize the whole slot transaction, including outcome persistence.
  if any(o['status'] in ('pending','unknown') for o in data['operations']):raise ValueError('上次附件变更结果未确认，请先核对，不重复上传')
  with page_session() as page:
   snap=inventory(page);choice=slot_plan(v,snap,data['bindings'])
   if choice['action']=='reuse':return {'status':'already_uploaded','attachment':choice['attachment'],'sent':False}
   if choice['action']!='upload':raise ValueError(choice.get('reason','需要先释放附件槽位'))
   op={'kind':'upload','version_id':v['id'],'sha256':v['sha256'],'status':'pending'}
   data['operations'].append(op);save(root,data)
   try:
    area=page.locator('.resume-attachment')
    dialog=page.locator('.upload-resume-dialog:visible')
    if dialog.count()==0:
     area.locator('.sider-title-operate').hover()
     area.get_by_text('上传简历',exact=True).click()
     dialog.wait_for(timeout=10000)
    file_input=dialog.locator('input[ka=user-resume-upload-file]')
    if file_input.count()!=1:raise ValueError('上传文件入口不唯一')
    file_input.set_input_files({'name':v['name'],'mimeType':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','buffer':(library.root/(v['id']+'.docx')).read_bytes()})
    confirmation=page.locator('.dialog-wrap:visible').filter(has_text='附件确认')
    confirmation.get_by_text('确定添加',exact=True).wait_for(timeout=15000)
    if v['name'] not in confirmation.inner_text():raise ValueError('附件确认文件名不匹配')
    confirmation.get_by_text('确定添加',exact=True).click()
    page.wait_for_function('(name)=>[...document.querySelectorAll(".resume-attachment .basis a[title]")].some(a=>a.title===name)',arg=v['name'],timeout=30000)
    after=inventory(page);new=[i for i in after['items'] if i['name']==v['name'] and i['remote_id'] not in {x['remote_id'] for x in snap['items']}]
    if len(new)!=1:raise ValueError('上传回显无法唯一核验')
    item=new[0]
    # Read back actual downloaded bytes, not only the filename.
    row=area.locator('.annex-item').filter(has=page.get_by_title(v['name'],exact=True))
    href=row.locator('a[type=download]').get_attribute('href')
    response=page.context.request.get(href,timeout=20000)
    if not response.ok or hashlib.sha256(response.body()).hexdigest()!=v['sha256']:raise ValueError('附件已出现，但远端文件指纹未核验；不要重复上传')
    data['bindings'][item['remote_id']]={'version_id':v['id'],'job_id':job_id,'sha256':v['sha256'],'name':v['name']}
    op.update(status='uploaded',remote_id=item['remote_id']);save(root,data)
    return {'status':'uploaded','attachment':item,'sha256_verified':True,'sent':False}
   except Exception:
    op['status']='unknown';save(root,data);raise ValueError('附件上传结果待核验；已停止，不自动重试')

def delete(library,job_id,version_id,remote_id,confirmed=False,root=WORKSPACE):
 """Delete only an explicitly selected, locally recoverable, unprotected slot."""
 with LOCK:
  v=version_for(library,job_id,version_id);require_review(v,confirmed);data=records(root)
  if any(o['status'] in ('pending','unknown') for o in data['operations']):raise ValueError('存在待核验操作，不能删除')
  with page_session() as page:
   snap=inventory(page)
   check=plan(library,job_id,version_id,root,snap)
   choice=check['slot_plan']
   if choice['action']!='choose_replacement' or remote_id not in {i['remote_id'] for i in choice['candidates']}:raise ValueError('不是本次满额计划中的可删除附件')
   binding=data['bindings'][remote_id];old=library.get(binding['version_id'])
   backup=library.root/(old['id']+'.docx')
   if not backup.exists() or hashlib.sha256(backup.read_bytes()).hexdigest()!=binding['sha256']:raise ValueError('旧附件缺少可恢复本地备份，停止')
   target=next(i for i in snap['items'] if i['remote_id']==remote_id)
   op={'kind':'delete','remote_id':remote_id,'replacement_version_id':version_id,'status':'pending'}
   data['operations'].append(op);save(root,data)
   try:
    area=page.locator('.resume-attachment')
    row=area.locator('.annex-item').filter(has=page.get_by_title(target['name'],exact=True))
    if row.count()!=1:raise ValueError('附件行不唯一')
    href=row.locator('a[type=download]').get_attribute('href')
    if parse_qs(urlsplit(href).query).get('resumeId')!=[remote_id]:raise ValueError('附件ID发生变化')
    row.locator('.annex-item-operate').hover()
    row.locator('.annex-operate-delete').click()
    dialog=page.locator('.dialog-container:visible,.dialog:visible,.dialog-wrap:visible').filter(has_text='确认删除该附件简历吗？').last
    dialog.wait_for(timeout=5000)
    sure=dialog.locator('[ka=dialog_sure]')
    if sure.count()!=1:raise ValueError('删除确认界面变化')
    sure.click()
    page.wait_for_function('(id)=>![...document.querySelectorAll(".resume-attachment a[type=download]")].some(a=>new URL(a.href).searchParams.get("resumeId")===id)',arg=remote_id,timeout=15000)
    after=inventory(page)
    if after['count']!=snap['count']-1:raise ValueError('删除后数量不一致')
    op['status']='deleted';data['bindings'].pop(remote_id,None);save(root,data)
    return {'status':'deleted','remote_id':remote_id,'remaining':after['count'],'local_backup_retained':True,'sent':False}
   except Exception:
    op['status']='unknown';save(root,data);raise ValueError('删除结果待核验，停止，不自动重试')
