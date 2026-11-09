import tempfile,unittest
from pathlib import Path
from career_agents import AgentRuntime
class AgentTests(unittest.TestCase):
 def test_persistent_task_and_event(self):
  with tempfile.TemporaryDirectory() as t:
   a=AgentRuntime(Path(t)/'runs.sqlite3')
   self.assertEqual(a.execute('batch','job','read_jd',lambda:'JD'),'JD')
   row=a.status('batch')['tasks'][0]
   self.assertEqual(row['agent'],'collect');self.assertEqual(row['status'],'completed')
   with self.assertRaises(RuntimeError):a.execute('batch','job','greet',lambda:(_ for _ in ()).throw(RuntimeError()))
   self.assertEqual(a.status()['tasks'][0]['status'],'failed')
   self.assertEqual(len(AgentRuntime(a.path).status()['tasks']),2)
 def test_interview_is_invitation_not_confirmed(self):
  from career_agents import interview_signal
  self.assertIsNone(interview_signal('您好，请发简历'))
  self.assertEqual(interview_signal('邀请您明天参加面试')['status'],'invited')
  self.assertFalse(interview_signal('邀请您明天参加面试')['confirmed'])
  self.assertEqual(interview_signal('取消面试')['status'],'cancelled')
 def test_independent_agent_schema(self):
  from chat_intents import validate,IntentError
  args={'action':'agent','id':'a'*32,'agent':'interview','job_id':'job','authorized':False}
  validate({'tool':'pipeline','arguments':args})
  with self.assertRaises(IntentError):validate({'tool':'pipeline','arguments':args|{'agent':'shell'}})
 def test_reports_preserve_results_without_duplicate_updates(self):
  with tempfile.TemporaryDirectory() as t:
   a=AgentRuntime(Path(t)/'runs.sqlite3')
   a.execute('batch','job','match',lambda:{'decision':'recommend','analysis':'实际匹配证据'})
   a.report('batch');a.report('batch')
   rows=a.reports('batch');self.assertEqual(len(rows),1)
   self.assertEqual(rows[0]['agents'][0]['completed'],1)
   self.assertIn('实际匹配证据',a.status('batch')['tasks'][0]['output'])
