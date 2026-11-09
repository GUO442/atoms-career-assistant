"""Transactional attachment workflow state, evidence journal, and application snapshots."""
import json,sqlite3
from pathlib import Path
from datetime import datetime,timezone

def connect(root):
 path=Path(root)/'data/delivery.sqlite3';path.parent.mkdir(parents=True,exist_ok=True)
 c=sqlite3.connect(path,timeout=15)
 c.execute('PRAGMA journal_mode=WAL')
 c.execute('CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY CHECK(id=1), body TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY AUTOINCREMENT, at TEXT NOT NULL, body TEXT NOT NULL)')
 c.execute('CREATE TABLE IF NOT EXISTS applications (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
 path.chmod(0o600)
 return c

def save_state(root,data):
 body=json.dumps(data,ensure_ascii=False)
 with connect(root) as c:
  prev=c.execute('SELECT body FROM state WHERE id=1').fetchone()
  c.execute('INSERT OR REPLACE INTO state VALUES(1,?)',(body,))
  if not prev or prev[0]!=body:c.execute('INSERT INTO events(at,body) VALUES(?,?)',(datetime.now(timezone.utc).isoformat(),body))

def load_state(root):
 with connect(root) as c:row=c.execute('SELECT body FROM state WHERE id=1').fetchone()
 if row:return json.loads(row[0])
 legacy=Path(root)/'data/resume-delivery.json'
 data=json.loads(legacy.read_text()) if legacy.exists() else {'bindings':{},'operations':[]}
 save_state(root,data)
 return data

def save_applications(root,applications):
 with connect(root) as c:
  for app in applications:c.execute('INSERT OR REPLACE INTO applications VALUES(?,?)',(app['id'],json.dumps(app,ensure_ascii=False)))
