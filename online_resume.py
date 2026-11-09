# -*- coding: utf-8 -*-
"""Prepare full BOSS online-resume fields locally; browser save requires verified UI."""
import argparse,hashlib,json,re,threading,zipfile
from pathlib import Path
from datetime import datetime,timezone
from xml.etree import ElementTree as ET
ROOT=Path(__file__).resolve().parent
ENTRY='https://www.zhipin.com/web/geek/resume'
NS={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}

def paragraphs(cell):return [''.join(t.text or '' for t in p.findall('.//w:t',NS)).strip() for p in cell.findall('./w:p',NS)]
def parse_docx(path):
 path=Path(path).expanduser().resolve()
 if path.suffix.lower()!='.docx':raise ValueError('请选择真实简历 DOCX')
 raw=path.read_bytes()
 if len(raw)>8_000_000:raise ValueError('文件超过 8MB')
 with zipfile.ZipFile(path) as z:
  info=z.getinfo('word/document.xml')
  if info.file_size>5_000_000:raise ValueError('正文过大')
  root=ET.fromstring(z.read(info))
 rows=root.findall('./w:body/w:tbl/w:tr',NS)
 if not rows or any(len(row.findall('./w:tc',NS))!=2 for row in rows):raise ValueError('当前支持双栏简历；其他结构需显式映射，不自动猜测')
 sidebar=paragraphs(rows[0].findall('./w:tc',NS)[0]);work=[];projects=[];company=None;current=None;summary='';intent=''
 for row in rows:
  for line in paragraphs(row.findall('./w:tc',NS)[1]):
   if not line:continue
   if '求职意向：' in line:intent=line.split('求职意向：',1)[1].strip();continue
   if line.startswith('7 年'):summary=line;continue
   if '项目经历' in line and re.match(r'^0[12]',line.strip()):continue
   match=re.match(r'^(.+?)\s*\|\s*(\d{4}(?:\.\d{2})?)[—-](\d{4}(?:\.\d{2})?)$',line)
   if match:
    key=match.group(1).strip()
    company=next((x for x in work if x['company']==key),None)
    if company is None:
     company={'company':key,'start':match.group(2),'end':match.group(3),'role':'','projects':[]};work.append(company)
    current=None;continue
   if line.startswith('角色：'):
    if company:company['role']=line.split('：',1)[1]
    continue
   if not company:continue
   if line.startswith('项目') and re.match(r'^项目[一二三四]\s',line) or (not line.startswith(('项目介绍','工作职责','工作内容')) and not re.match(r'^\d',line)):
    current={'name':re.sub(r'^项目[一二三四]\s+','',line),'company':company['company'],'start':company['start'],'end':company['end'],'lines':[]};projects.append(current);company['projects'].append(current)
   elif current:current['lines'].append(line)
 for p in projects:
  p['description']='\n'.join(p['lines']);p['character_count']=len(p['description'])
 for w in work:
  w['description']='\n\n'.join(p['name']+'\n'+p['description'] for p in w['projects'])
  w['month_precision_known']='.' in w['start'] and '.' in w['end']
 return {'source':str(path),'source_sha256':hashlib.sha256(raw).hexdigest(),'entry_url':ENTRY,'target_role':intent,'summary':summary,'sidebar_lines':sidebar,'work_experience':work,'projects':projects,'status':'prepared_not_saved','remote_updated':False,'created':datetime.now(timezone.utc).isoformat(),'field_rules':{'工作经历':'公司、任职时间、角色及职责；已有记录原位修改，缺失记录新增','项目经历':'按源简历顺序逐项新增或匹配更新，保留所有编号与正文','个人优势':'源简历概述与技能，不能写入未确认能力','教育经历':'只按明确事实修改，不编造月份、专业或学历','字段长度':'先读页面限制；超限停下报告，不静默截断','时间精度':'仅年份的旧经历保留已核实月份或询问用户，不补造月份'}}

class OnlineResume:
 def __init__(self,root):
  self.root=Path(root);self.root.mkdir(parents=True,exist_ok=True);self.root.chmod(0o700);self.file=self.root/'plan.json';self.lock=threading.RLock()
 def prepare(self,source=None):
  with self.lock:
   pointer=self.root/'source.json'
   if source is None:
    if not pointer.exists():raise ValueError('尚未指定最新简历，请先提供 DOCX 路径')
    source=json.loads(pointer.read_text())['path']
   plan=parse_docx(source)
   if self.file.exists():
    old=json.loads(self.file.read_text());(self.root/('plan-'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.json')).write_text(json.dumps(old,ensure_ascii=False))
   self.file.write_text(json.dumps(plan,ensure_ascii=False,indent=2));self.file.chmod(0o600)
   pointer.write_text(json.dumps({'path':plan['source'],'sha256':plan['source_sha256']},ensure_ascii=False));pointer.chmod(0o600)
   return plan
 def status(self):
  if not self.file.exists():return {'status':'not_prepared','entry_url':ENTRY,'remote_updated':False}
  return json.loads(self.file.read_text())

def main():
 p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','status']);p.add_argument('--source');a=p.parse_args();store=OnlineResume(ROOT/'data/online-resume')
 print(json.dumps(store.prepare(a.source) if a.action=='prepare' else store.status(),ensure_ascii=False,indent=2))
if __name__=='__main__':main()
