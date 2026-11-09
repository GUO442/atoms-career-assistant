import io,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from docx import Document
from resume_library import Library
from resume_delivery import slot_plan,plan,upload
from boss_tools import execute
class DeliveryTests(unittest.TestCase):
 def test_free_slot_does_not_schedule_deletion(self):
  self.assertEqual(slot_plan({'name':'new.docx','sha256':'new'},{'count':2,'capacity':3,'items':[{'remote_id':'a','name':'a'},{'remote_id':'b','name':'b'}]})['action'],'upload')
 def test_reuse_requires_hash_mapping_not_latest_or_same_name(self):
  snap={'count':1,'capacity':3,'items':[{'remote_id':'a','name':'new.docx'}]}
  v={'name':'new.docx','sha256':'new'}
  self.assertEqual(slot_plan(v,snap)['action'],'verify_existing')
  self.assertEqual(slot_plan(v,snap,{'a':{'sha256':'new'}})['action'],'reuse')
 def test_full_slots_exclude_unknown_and_protected_files(self):
  snap={'count':3,'capacity':3,'items':[{'remote_id':k,'name':k} for k in 'abc']}
  result=slot_plan({'name':'new.docx','sha256':'new'},snap,{'a':{'sha256':'old'},'b':{'sha256':'old2'}},protected={'a'})
  self.assertEqual([i['remote_id'] for i in result['candidates']],['b'])
 def test_read_plan_does_not_review_or_write_and_upload_checks_review_first(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(Path(tmp)/'data/resumes');d=Document();d.add_paragraph('真实简历');b=io.BytesIO();d.save(b)
   original=lib.add('base.docx',b.getvalue())
   job={'job_id':'abc','url':'https://www.zhipin.com/job_detail/abc.html','company':'公司','title':'测试','jd':'测试','source':'user','collected_at':'2026-10-30'}
   v=lib.add_tailored('tailored.docx',b.getvalue(),job,original['id'])
   result=plan(lib,'abc',v['id'],tmp,{'count':0,'capacity':3,'items':[]})
   self.assertFalse(result['reviewed']);self.assertFalse(result['sent'])
   self.assertFalse((Path(tmp)/'data/resume-delivery.json').exists())
   with patch('resume_delivery.page_session') as browser:
    with self.assertRaises(ValueError):upload(lib,'abc',v['id'],True,tmp)
    browser.assert_not_called()
   self.assertEqual(lib.load()['applications'],[])
 def test_catalog_separates_upload_from_send(self):
  names={t['name'] for t in execute('catalog',{})['tools']}
  self.assertTrue({'attachment-inventory','attachment-plan','attachment-upload'}<=names)
  self.assertFalse(execute('send-resume',{})['sent'])
