import io,sys,tempfile,unittest,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from resume_library import Library
class ReviewGate(unittest.TestCase):
 def test_review_and_duplicate_gate(self):
  with tempfile.TemporaryDirectory() as d:
   lib=Library(d);b=io.BytesIO()
   with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>真实简历</w:t></w:r></w:p></w:body></w:document>')
   v=lib.add('resume.docx',b.getvalue(),{'title':'企业岗位','url':'https://www.zhipin.com/job_detail/test.html','jd':'真实JD'},'tailored')
   self.assertEqual(v['text'],'真实简历')
   with self.assertRaises(ValueError):lib.action('apply',v['id'],True)
   with self.assertRaises(ValueError):lib.action('review',v['id'],False)
   lib.action('review',v['id'],True);r=lib.action('apply',v['id'],True)
   self.assertEqual(r['applications'][0]['status'],'waiting_browser')
   self.assertEqual(r['applications'][0]['resume_status'],'not_sent')
   with self.assertRaises(ValueError):lib.action('apply',v['id'],True)
if __name__=='__main__':unittest.main()

class TailoredRegistration(unittest.TestCase):
 def body(self,text):
  b=io.BytesIO()
  with zipfile.ZipFile(b,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
  return b.getvalue()
 def job(self):return {'job_id':'abc','url':'https://www.zhipin.com/job_detail/abc.html?securityId=private','title':'金融测试主管','company':'企业','jd':'完整JD','source':'browser_visible_page','collected_at':'2026-10-28'}
 def test_registration_preserves_original_deduplicates_and_never_applies(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(tmp);original=lib.add('original.docx',self.body('真实经历'))
   first=lib.add_tailored('tailored.docx',self.body('定制正文'),self.job(),original['id'])
   second=lib.add_tailored('tailored.docx',self.body('定制正文'),self.job(),original['id'])
   self.assertEqual(first['id'],second['id']);self.assertEqual(first['source_resume_id'],original['id'])
   self.assertFalse(first['reviewed']);self.assertEqual(first['kind'],'tailored')
   self.assertNotIn('securityId',first['job']['url'])
   self.assertEqual(lib.get(original['id'])['text'],'真实经历')
   self.assertEqual(lib.load()['applications'],[])
 def test_mismatch_and_non_original_source_are_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(tmp);original=lib.add('original.docx',self.body('真实经历'))
   bad=self.job();bad['job_id']='other'
   with self.assertRaises(ValueError):lib.add_tailored('a.docx',self.body('正文'),bad,original['id'])
   version=lib.add('prior.docx',self.body('历史定制'),kind='tailored')
   with self.assertRaises(ValueError):lib.add_tailored('a.docx',self.body('正文'),self.job(),version['id'])
