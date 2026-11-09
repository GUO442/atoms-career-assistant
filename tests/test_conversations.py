import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from conversations import Conversations
class ConversationTests(unittest.TestCase):
 def test_migration_isolation_and_restart(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'chats.sqlite3';legacy=[{'role':'user','content':'old conversation'}];store=Conversations(path,legacy);old=store.listing()[0]['id'];new=store.create()
   self.assertEqual(store.get(old)['messages'],legacy);self.assertEqual(new['messages'],[])
   saved=store.save(new['id'],[{'role':'user','content':'new topic'}],0)
   self.assertEqual(saved['title'],'new topic');self.assertEqual(store.get(old)['messages'],legacy)
   reopened=Conversations(path,legacy);self.assertEqual(len(reopened.listing()),2)
   with self.assertRaises(ValueError):store.save(new['id'],[],0)
   self.assertEqual(store.get(new['id'])['messages'],saved['messages'])
 def test_reuses_empty_conversation(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Conversations(Path(tmp)/'db');first=store.listing()[0]['id']
   self.assertEqual(store.new(first)['id'],first)
   self.assertEqual(store.new()['id'],first)
   store.save(first,[{'role':'user','content':'topic'}],0)
   blank=store.new(first)
   self.assertNotEqual(blank['id'],first)
   self.assertEqual(store.new(first)['id'],blank['id'])
   self.assertEqual(len(store.listing()),2)
 def test_force_new_does_not_reuse_an_empty_running_conversation(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Conversations(Path(tmp)/'db');first=store.listing()[0]['id']
   created=store.new(first,force=True)
   self.assertNotEqual(created['id'],first)
   self.assertEqual(store.get(first)['messages'],[])
 def test_invalid_messages(self):
  with tempfile.TemporaryDirectory() as tmp:
   store=Conversations(Path(tmp)/'db');key=store.listing()[0]['id']
   with self.assertRaises(ValueError):store.save(key,[{'role':'system','content':'x'}],0)
if __name__=='__main__':unittest.main()
