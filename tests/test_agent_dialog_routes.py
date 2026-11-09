import unittest,tempfile
from pathlib import Path
from assistant_skills import SkillRuntime,SKILLS
from chat_intents import validate,IntentError
from career_agents import AGENTS
class AgentDialogTests(unittest.TestCase):
 def test_all_agents_have_skills_and_valid_routes(self):
  catalog={r['id'] for r in SkillRuntime(Path(__file__).resolve().parents[1]).catalog()}
  for agent in AGENTS:
   self.assertIn('career-agent-'+agent,catalog)
   self.assertIn('pipeline',SKILLS['career-agent-'+agent]['tools'])
   validate({'tool':'pipeline','arguments':{'action':'agent_status','agent':agent}})
   validate({'tool':'pipeline','arguments':{'action':'agent_start','id':'a'*32,'agent':agent,'authorized':agent in ('greet','deliver')}})
 def test_unknown_agent_and_extra_actions_rejected(self):
  for args in ({'action':'agent_status','agent':'shell'},{'action':'agent_status','agent':'match','send':True}):
   with self.assertRaises(IntentError):validate({'tool':'pipeline','arguments':args})
