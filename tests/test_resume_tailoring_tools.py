import io,json,tempfile,unittest
from pathlib import Path
from docx import Document
from resume_library import Library
from resume_tailoring import tailor
from resume_tailoring_tools import select_job,preferences
from assistant_skills import SkillRuntime
from chat_intents import IntentRouter
HR_REVIEW=[{"problem":"定位偏测试","why":"JD要求开发与大模型应用经验","fix":"把开发与构建动作前置"},{"problem":"成果不可量化","why":"缺少上线与效果证据","fix":"按XYZ写做法与结果"},{"problem":"构建者视角不足","why":"只写了测试职责","fix":"突出框架、编排与工具接入"}]

JOB={'job_id':'abc','url':'https://www.zhipin.com/job_detail/abc.html','title':'测试主管','company':'示例公司','jd':'金融自动化','source':'user','collected_at':'2026-10-30'}
def doc(texts):
 d=Document()
 for t in texts:d.add_paragraph(t)
 out=io.BytesIO();d.save(out);return out.getvalue()

class TailoringIntegrationTests(unittest.TestCase):
 def test_supplement_project_fields_without_deleting_original_work(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(tmp);v=lib.add('base.docx',doc(['项目：银行测试','负责接口及账务核验。']))
   def model(i,c):
    self.assertIn('原版式',c['skill_instructions'])
    return json.dumps({'hr_review':HR_REVIEW,'replacements':[],'additions':[{'after':0,'kind':'intro','text':'项目介绍：银行接口与账务核验。','evidence':[1]},{'after':0,'kind':'role','text':'项目角色：测试执行。','evidence':[1]}],'changes':['补齐介绍和角色'],'gaps':[]})
   out=tailor(lib,model,JOB)
   self.assertIn('项目介绍：银行接口与账务核验。',out['text'])
   self.assertIn('负责接口及账务核验。',out['text'])
   self.assertLess(out['text'].index('项目介绍：'),out['text'].index('项目角色：'))
   self.assertEqual(out['tailoring_report']['layout_review'],'pending')
   self.assertFalse(out['reviewed']);self.assertEqual(lib.load()['applications'],[])
 def test_template_is_layout_only_and_confirmations_are_source_scoped(self):
  with tempfile.TemporaryDirectory() as tmp:
   lib=Library(tmp);v=lib.add('base.docx',doc(['原始：接口测试。']))
   template=lib.add_tailored('template.docx',doc(['项目角色：测试负责人。','接口测试。']),JOB,v['id'])
   (lib.root/'tailoring_preferences.json').write_text(json.dumps({'source_resume_id':v['id'],'template_version_id':template['id'],'confirmed_facts':['用户确认承担测试负责人职责。']}))
   def model(i,c):
    self.assertEqual(c['original_facts'][0]['text'],'原始：接口测试。')
    self.assertEqual(c['paragraphs'][0]['text'],'项目角色：测试负责人。')
    self.assertIn('用户确认',c['confirmed_facts'][0])
    return json.dumps({'hr_review':HR_REVIEW,'replacements':[{'paragraph':1,'text':'负责接口测试。','evidence':[0]}],'changes':[],'gaps':[]})
   out=tailor(lib,model,JOB);self.assertEqual(out['source_resume_id'],v['id'])
   other=lib.add('other.docx',doc(['别的用户经历']))
   self.assertEqual(preferences(lib,other['id']),{})
 def test_ambiguous_jobs_fail_instead_of_picking_first(self):
  self.assertEqual(select_job([JOB],'abc')['job_id'],'abc')
  with self.assertRaises(ValueError):select_job([JOB,JOB|{'job_id':'other'}],'示例公司')
 def test_skill_load_routes_to_generation_and_rejects_unregistered_parameters(self):
  root=Path(__file__).resolve().parents[1];runtime=SkillRuntime(root)
  self.assertIn('boss-tailor-resume',[s['id'] for s in runtime.catalog()])
  expected={'tool':'resume.tailor','arguments':{'query':'abc'}}
  plan,used=runtime.resolve({'tool':'skill.run','arguments':{'id':'boss-tailor-resume'}},{'messages':[{'role':'user','content':'帮我按这个岗位定制简历'}]},[],IntentRouter(lambda *a:json.dumps(expected)))
  self.assertEqual(plan,expected);self.assertEqual(used[0]['id'],'boss-tailor-resume')

class BackgroundTailoringTests(unittest.TestCase):
 def test_start_tool_creates_a_real_pending_word_and_status_links_it(self):
  import time
  from career_tracking import Tracker
  from career_automation import DraftService
  from resume_tailoring_tools import start_tailoring,tailoring_status
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);skill=root/'skills/boss-tailor-resume/SKILL.md';skill.parent.mkdir(parents=True)
   skill.write_text('保留原版式；突出有证据的岗位匹配。')
   lib=Library(root/'data/resumes');lib.add('base.docx',doc(['接口测试。']))
   tracker=Tracker(root/'tracking')
   model=lambda *_:json.dumps({'hr_review':HR_REVIEW,'replacements':[{'paragraph':0,'text':'负责接口测试。','evidence':[0]}],'changes':['岗位匹配'],'gaps':[]})
   service=DraftService(tracker,lib,model)
   result=start_tailoring(lib,root,[JOB],tracker,service,'示例公司测试主管')
   self.assertEqual(result['job_id'],'abc');self.assertFalse(result['sent'])
   deadline=time.monotonic()+3
   while service.status()['generating'] and time.monotonic()<deadline:time.sleep(.01)
   self.assertEqual(service.status()['errors'],{})
   status=tailoring_status(tracker,service)
   self.assertEqual(len(status['drafts']),1)
   version=lib.get(status['drafts'][0]['version_id'])
   self.assertFalse(version['reviewed']);self.assertEqual(version['kind'],'tailored')
   self.assertEqual(lib.load()['applications'],[])
