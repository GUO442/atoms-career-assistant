# -*- coding: utf-8 -*-
import subprocess, sys, time, urllib.request, webbrowser
from pathlib import Path
ROOT=Path(__file__).resolve().parent
URL='http://127.0.0.1:18743'
def ready():
 try:
  with urllib.request.urlopen(URL+'/api/state',timeout=1) as r: return r.status==200
 except Exception: return False
if not ready():
 log=open(ROOT/'data'/'server.log','a')
 subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdout=log,stderr=log,start_new_session=True)
 for _ in range(50):
  if ready(): break
  time.sleep(.1)
if ready(): webbrowser.open(URL)
else: raise SystemExit('本地服务启动失败，请检查 data/server.log')
