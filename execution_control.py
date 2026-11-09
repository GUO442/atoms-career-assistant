# -*- coding: utf-8 -*-
"""Request-scoped cooperative cancellation and owned subprocess termination."""
import contextvars,os,signal,subprocess,threading,time
from contextlib import contextmanager

class TaskCancelled(RuntimeError):pass
_current=contextvars.ContextVar('career_execution',default=None)
class Control:
 def __init__(self):self.cancelled=threading.Event();self.processes=set();self.active=False;self.finished=False;self.updated=time.monotonic()
class Executions:
 def __init__(self):self.lock=threading.RLock();self.items={}
 def _prune(self):
  now=time.monotonic()
  self.items={k:v for k,v in self.items.items() if v.active or now-v.updated<120}
 @contextmanager
 def scope(self,key):
  with self.lock:
   self._prune();control=self.items.get(key)
   if control and control.active:raise ValueError('任务已在执行')
   if control is None or not control.cancelled.is_set():control=Control();self.items[key]=control
   control.active=True
  token=_current.set(control)
  try:check_cancelled();yield control;check_cancelled()
  finally:
   _current.reset(token)
   with self.lock:control.active=False;control.finished=True;control.updated=time.monotonic()
 def cancel(self,key):
  with self.lock:
   self._prune();control=self.items.get(key)
   if control is None:
    if len(self.items)>=512:raise ValueError('停止请求过多，请稍后重试')
    control=Control();self.items[key]=control
   if control.finished:return {'status':'already_finished','active':False}
   control.cancelled.set();control.updated=time.monotonic();processes=list(control.processes)
  for process in processes:terminate(process)
  return {'status':'cancel_requested','active':control.active}
TASKS=Executions()

def check_cancelled():
 control=_current.get()
 if control and control.cancelled.is_set():raise TaskCancelled('用户已停止本次任务')

def terminate(process,force=False):
 try:
  if os.name=='nt':
   if process.poll() is None:subprocess.run(['taskkill','/PID',str(process.pid),'/T','/F'],capture_output=True,timeout=3)
  else:os.killpg(process.pid,signal.SIGKILL if force else signal.SIGTERM)
 except (ProcessLookupError,PermissionError,subprocess.TimeoutExpired):pass

def managed_run(command,**kwargs):
 control=_current.get()
 if control is None:return subprocess.run(command,**kwargs)
 check_cancelled()
 options=dict(kwargs);input_data=options.pop('input',None);timeout=options.pop('timeout',None);capture=options.pop('capture_output',False);check=options.pop('check',False)
 if capture:options.update(stdout=subprocess.PIPE,stderr=subprocess.PIPE)
 if input_data is not None:options['stdin']=subprocess.PIPE
 if os.name=='nt':options['creationflags']=options.get('creationflags',0)|subprocess.CREATE_NEW_PROCESS_GROUP
 else:options['start_new_session']=True
 with TASKS.lock:
  check_cancelled();process=subprocess.Popen(command,**options);control.processes.add(process)
 # communicate() must own stdin for its entire lifetime. Re-entering it with
 # input=None after a short timeout can stop registering a partially written
 # stdin on supported Python runtimes, leaving both processes waiting forever.
 completed=threading.Event();result={}
 def exchange():
  try:result['output']=process.communicate(input=input_data,timeout=timeout)
  except BaseException as exc:result['error']=exc
  finally:completed.set()
 worker=threading.Thread(target=exchange,daemon=True)
 started=time.monotonic();worker.start()
 try:
  while not completed.wait(.05):
   check_cancelled()
   if timeout is not None and time.monotonic()-started>=timeout:raise subprocess.TimeoutExpired(command,timeout)
  check_cancelled()
  if 'error' in result:raise result['error']
  out,err=result['output']
  if check and process.returncode:raise subprocess.CalledProcessError(process.returncode,command,out,err)
  return subprocess.CompletedProcess(command,process.returncode,out,err)
 except BaseException:
  terminate(process)
  try:process.wait(timeout=.5)
  except subprocess.TimeoutExpired:
   terminate(process,True);process.wait()
  # A descendant may retain the pipes even after the direct child exits.
  terminate(process,True);worker.join(timeout=2)
  raise
 finally:
  worker.join(timeout=2)
  for stream in (process.stdin,process.stdout,process.stderr):
   if stream is not None and not stream.closed:stream.close()
  with TASKS.lock:control.processes.discard(process)

class ChatBusy(RuntimeError):pass
class ChatCapacity(RuntimeError):pass
class ChatGates:
 """One generation per conversation, bounded parallelism across conversations."""
 def __init__(self,limit=4):self.limit=limit;self.lock=threading.Lock();self.active=set()
 def acquire(self,key):
  with self.lock:
   if key in self.active:raise ChatBusy('当前会话已有进行中的请求')
   if len(self.active)>=self.limit:raise ChatCapacity('最多同时执行4个对话，请等待一个任务结束')
   self.active.add(key)
 def release(self,key):
  with self.lock:self.active.discard(key)
CHAT_GATES=ChatGates()
