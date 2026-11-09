import os,sys,tempfile,threading,time,unittest,uuid
from pathlib import Path
from execution_control import TASKS,TaskCancelled,check_cancelled,managed_run

class CancellationTests(unittest.TestCase):
 def key(self):return 'test:'+uuid.uuid4().hex
 def test_early_cancel_prevents_process_launch(self):
  key=self.key();TASKS.cancel(key)
  with self.assertRaises(TaskCancelled):
   with TASKS.scope(key):self.fail('Cancelled execution must never enter')
 def test_stops_running_process_and_allows_next_task(self):
  key=self.key();entered=threading.Event();done=threading.Event();out=[]
  def work():
   try:
    with TASKS.scope(key):entered.set();managed_run([sys.executable,'-c','import time;time.sleep(30)'],capture_output=True,text=True,timeout=40)
   except TaskCancelled:out.append('cancelled')
   finally:done.set()
  t=threading.Thread(target=work);t.start();self.assertTrue(entered.wait(2));time.sleep(.15);TASKS.cancel(key)
  self.assertTrue(done.wait(3));t.join();self.assertEqual(out,['cancelled'])
  with TASKS.scope(self.key()):self.assertEqual(managed_run([sys.executable,'-c','print("next")'],capture_output=True,text=True,timeout=2).stdout.strip(),'next')
 def test_scope_isolation(self):
  with TASKS.scope(self.key()):TASKS.cancel(self.key());check_cancelled()
 def test_timeout_reaps_process(self):
  import subprocess
  with TASKS.scope(self.key()):
   with self.assertRaises(subprocess.TimeoutExpired):managed_run([sys.executable,'-c','import time;time.sleep(30)'],capture_output=True,text=True,timeout=.2)
 def test_large_stdin_and_output_are_not_deadlocked(self):
  with TASKS.scope(self.key()):
   r=managed_run([sys.executable,'-c','import sys;v=sys.stdin.read();print(len(v));sys.stderr.write("x"*100000)'],input='a'*300000,capture_output=True,text=True,timeout=3)
   self.assertEqual(r.stdout.strip(),'300000');self.assertEqual(len(r.stderr),100000)
 def test_stdin_survives_multiple_poll_intervals(self):
  with TASKS.scope(self.key()):
   r=managed_run([sys.executable,'-c','import sys,time;v=sys.stdin.read();time.sleep(.4);print(v)'],input='original input',capture_output=True,text=True,timeout=3)
   self.assertEqual(r.stdout.strip(),'original input')
 @unittest.skipIf(os.name=='nt','POSIX descendant process check')
 def test_descendant_is_terminated(self):
  key=self.key();done=threading.Event()
  with tempfile.TemporaryDirectory() as temp:
   file=Path(temp)/'child.pid'
   script='import subprocess,sys,time;p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(30)"]);open(sys.argv[1],"w").write(str(p.pid));time.sleep(30)'
   def work():
    try:
     with TASKS.scope(key):managed_run([sys.executable,'-c',script,str(file)],capture_output=True,text=True,timeout=40)
    except TaskCancelled:pass
    finally:done.set()
   t=threading.Thread(target=work);t.start()
   for _ in range(100):
    if file.exists() and file.read_text():break
    time.sleep(.02)
   self.assertTrue(file.exists());pid=int(file.read_text());TASKS.cancel(key);self.assertTrue(done.wait(3));t.join()
   # A dead orphan may briefly remain as a zombie; it must not be executing.
   import subprocess
   status=subprocess.run(['ps','-o','stat=','-p',str(pid)],capture_output=True,text=True).stdout.strip()
   self.assertTrue(not status or status.startswith('Z'),status)

 def test_stopping_a_finished_task_does_not_mark_it_cancelled(self):
  key=self.key()
  with TASKS.scope(key):check_cancelled()
  self.assertEqual(TASKS.cancel(key)['status'],'already_finished')

class ConversationGateTests(unittest.TestCase):
 def test_conversations_are_independent_and_capacity_is_bounded(self):
  from execution_control import ChatGates,ChatBusy,ChatCapacity
  gates=ChatGates(limit=2);gates.acquire('A');gates.acquire('B')
  with self.assertRaises(ChatBusy):gates.acquire('A')
  with self.assertRaises(ChatCapacity):gates.acquire('C')
  gates.release('A');gates.acquire('C');gates.release('B');gates.release('C')

class SlowStdinTests(unittest.TestCase):
 def test_delayed_reader_receives_entire_unicode_prompt(self):
  import hashlib,json
  payload='完整的长提示词，必须全部发送。\n'*30000
  script='import sys,time,json,hashlib;time.sleep(.35);v=sys.stdin.read();sys.stderr.write("x"*100000);print(json.dumps({"sha":hashlib.sha256(v.encode()).hexdigest(),"length":len(v)}))'
  with TASKS.scope('slow-input:'+uuid.uuid4().hex):
   result=managed_run([sys.executable,'-c',script],input=payload,capture_output=True,text=True,timeout=4)
  value=json.loads(result.stdout)
  self.assertEqual(value['sha'],hashlib.sha256(payload.encode()).hexdigest())
  self.assertEqual(value['length'],len(payload));self.assertEqual(len(result.stderr),100000)
 def test_cancel_while_child_has_not_started_reading_input(self):
  key='cancel-input:'+uuid.uuid4().hex;entered=threading.Event();done=threading.Event();values=[]
  def work():
   try:
    with TASKS.scope(key):
     entered.set();managed_run([sys.executable,'-c','import time;time.sleep(30)'],input='x'*2000000,capture_output=True,text=True,timeout=35)
   except TaskCancelled:values.append('cancelled')
   finally:done.set()
  thread=threading.Thread(target=work);thread.start();self.assertTrue(entered.wait(1));time.sleep(.15);TASKS.cancel(key)
  self.assertTrue(done.wait(3));thread.join();self.assertEqual(values,['cancelled'])
