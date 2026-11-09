import json,tempfile,unittest,sqlite3
from pathlib import Path
from delivery_store import load_state,save_state,save_applications
class DeliveryStoreTests(unittest.TestCase):
 def test_migration_persistence_and_authoritative_database(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'data').mkdir()
   legacy=root/'data/resume-delivery.json';legacy.write_text(json.dumps({'bindings':{'r':{'sha256':'hash'}},'operations':[]}))
   state=load_state(root);self.assertIn('r',state['bindings'])
   state['operations'].append({'kind':'upload','status':'unknown'});save_state(root,state)
   legacy.write_text('{}')
   self.assertEqual(load_state(root)['operations'][0]['status'],'unknown')
   save_applications(root,[{'id':'a','status':'sent','message_id':'mid'}])
   with sqlite3.connect(root/'data/delivery.sqlite3') as c:
    self.assertEqual(json.loads(c.execute('SELECT body FROM applications WHERE id="a"').fetchone()[0])['message_id'],'mid')
    self.assertGreaterEqual(c.execute('SELECT count(*) FROM events').fetchone()[0],2)
