# -*- coding: utf-8 -*-
"""Persistent, isolated conversations with optimistic revision checks."""
import json,sqlite3,uuid
from datetime import datetime,timezone
from pathlib import Path
class Conversations:
 def __init__(self,path,legacy=None):
  self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
  with self.connect() as db:
   db.execute('CREATE TABLE IF NOT EXISTS conversations (id TEXT PRIMARY KEY,title TEXT,messages TEXT,updated TEXT,revision INTEGER)')
   if not db.execute('SELECT 1 FROM conversations LIMIT 1').fetchone():self.create(legacy or [],db)
 def connect(self):return sqlite3.connect(self.path,timeout=10)
 def create(self,messages=None,db=None):
  if db is None:
   with self.connect() as conn:return self.create(messages,conn)
  messages=messages or [];key=uuid.uuid4().hex;title=next((m['content'][:28] for m in messages if m.get('role')=='user'),'新会话');now=datetime.now(timezone.utc).isoformat()
  db.execute('INSERT INTO conversations VALUES(?,?,?,?,0)',(key,title,json.dumps(messages,ensure_ascii=False),now));return {'id':key,'title':title,'messages':messages,'updated':now,'revision':0}
 def new(self,current=None,force=False):
  if force:return self.create()
  with self.connect() as db:
   db.execute('BEGIN IMMEDIATE')
   if current:
    row=db.execute('SELECT id FROM conversations WHERE id=? AND json_array_length(messages)=0',(current,)).fetchone()
    if row:return self.get(row[0])
   row=db.execute('SELECT id FROM conversations WHERE json_array_length(messages)=0 ORDER BY updated DESC LIMIT 1').fetchone()
   if row:return self.get(row[0])
   return self.create(db=db)
 def listing(self):
  with self.connect() as db:return [dict(zip(('id','title','updated','revision','count'),r)) for r in db.execute('SELECT id,title,updated,revision,json_array_length(messages) FROM conversations ORDER BY updated DESC')]
 def get(self,key):
  with self.connect() as db:r=db.execute('SELECT id,title,messages,updated,revision FROM conversations WHERE id=?',(key,)).fetchone()
  if not r:raise ValueError('会话不存在')
  d=dict(zip(('id','title','messages','updated','revision'),r));d['messages']=json.loads(d['messages']);return d
 def save(self,key,messages,revision):
  if not isinstance(messages,list) or len(messages)>1000 or any(not isinstance(m,dict) or m.get('role') not in ('user','assistant') or not isinstance(m.get('content'),str) or len(m['content'])>200000 for m in messages):raise ValueError('无效会话内容')
  old=self.get(key);title=old['title']
  if title=='新会话':title=next((m['content'][:28] for m in messages if m['role']=='user'),title)
  with self.connect() as db:
   n=db.execute('UPDATE conversations SET messages=?,title=?,updated=?,revision=revision+1 WHERE id=? AND revision=?',(json.dumps(messages,ensure_ascii=False),title,datetime.now(timezone.utc).isoformat(),key,revision)).rowcount
   if not n:raise ValueError('此会话已在另一个页面更新，请刷新后继续；当前页面内容尚未覆盖历史记录')
  return self.get(key)
