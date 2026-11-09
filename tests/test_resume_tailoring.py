import io,json,tempfile,unittest,zipfile
from pathlib import Path
from docx import Document
from resume_library import Library
from resume_tailoring import tailor
HR_REVIEW=[{"problem":"定位偏测试","why":"JD要求开发与大模型应用经验","fix":"把开发与构建动作前置"},{"problem":"成果不可量化","why":"缺少上线与效果证据","fix":"按XYZ写做法与结果"},{"problem":"构建者视角不足","why":"只写了测试职责","fix":"突出框架、编排与工具接入"}]

class TailoringTests(unittest.TestCase):
 def test_preserves_template_links_source_and_separates_report(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(tmp);doc=Document();doc.add_paragraph('使用 Python 开展接口测试。');doc.add_table(rows=1,cols=2).cell(0,0).text='教育经历不变'
   out=io.BytesIO();doc.save(out);body=out.getvalue();original=lib.add('base.docx',body)
   def model(instruction,ctx):
    self.assertEqual(ctx['paragraphs'][0]['text'],'使用 Python 开展接口测试。')
    return json.dumps({'hr_review':HR_REVIEW,'replacements':[{'paragraph':0,'text':'基于 Python 执行接口测试。','evidence':[0]}],'changes':['突出接口测试'],'gaps':['管理经验未确认']},ensure_ascii=False)
   job={'url':'https://www.zhipin.com/job_detail/abc.html','title':'测试','company':'公司','jd':'Python 接口测试'}
   v=tailor(lib,model,job,original['id'])
   self.assertEqual(v['source_resume_id'],original['id']);self.assertFalse(v['reviewed']);self.assertNotIn('管理经验',v['text'])
   self.assertEqual(v['tailoring_report']['gaps'],['管理经验未确认'])
   with zipfile.ZipFile(io.BytesIO(body)) as src,zipfile.ZipFile(lib.root/(v['id']+'.docx')) as dst:
    for name in src.namelist():
     if name!='word/document.xml':self.assertEqual(src.read(name),dst.read(name))
   self.assertEqual((lib.root/(original['id']+'.docx')).read_bytes(),body)
   self.assertEqual(lib.load()['applications'],[])
 def test_invalid_patches_cannot_register(self):
  for patch in [{'paragraph':0,'text':'提升90%','evidence':[0]}, {'paragraph':0,'text':'改写','evidence':[]}, {'paragraph':99,'text':'改写','evidence':[0]}]:
   with self.subTest(patch=patch),tempfile.TemporaryDirectory() as tmp:
    lib=Library(tmp);doc=Document();doc.add_paragraph('接口测试');out=io.BytesIO();doc.save(out);v=lib.add('base.docx',out.getvalue())
    with self.assertRaises(ValueError):tailor(lib,lambda *_:json.dumps({'hr_review':HR_REVIEW,'replacements':[patch],'changes':[],'gaps':[]}),{'url':'https://www.zhipin.com/job_detail/abc.html','title':'测试','company':'公司','jd':'接口测试'},v['id'])
    self.assertEqual(len(lib.load()['versions']),1)
if __name__=='__main__':unittest.main()
