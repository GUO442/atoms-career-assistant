import unittest
from matching_policy import assess
from job_management import dashboard
class DirectMatchingTests(unittest.TestCase):
 def test_direct_pass_without_jd(self):
  self.assertEqual(assess({'title':'AI产品经理','salary':'30-50K'})['decision'],'recommend')
 def test_exclusions(self):
  for job in [{'title':'AI实习生','salary':'30K'},{'title':'AI工程师','salary':'500元/天'},{'title':'AI工程师','salary':'25-40K'},{'title':'Java开发','salary':'40K'}]:
   self.assertEqual(assess(job)['decision'],'reject')
 def test_threshold_and_unknown(self):
  self.assertEqual(assess({'title':'Agent开发','salary':'35K'},'至少40K')['decision'],'reject')
  self.assertEqual(assess({'title':'AI测试','salary':'面议'})['decision'],'caution')
 def test_statistics_recalculate(self):
  d=dashboard({'jobs':[{'job_id':'a','title':'AI产品经理','salary':'30K','decision':'caution','eligibility':'excluded'}]}, {}, {})
  self.assertEqual(d['jobs'][0]['screening'],'recommend')

 def test_hide_nonmatching_and_unknown_salary(self):
  result=dashboard({'jobs':[
   {'job_id':'pass','title':'AI工程师','salary':'30-40K'},
   {'job_id':'reject','title':'AI工程师','salary':'20-25K'},
   {'job_id':'unknown','title':'AI工程师','salary':'面议'}]}, {}, {})
  self.assertEqual(result['total'],1)
  self.assertEqual([j['job_id'] for j in result['jobs']],['pass'])
  for dimension in result['dimensions']:
   self.assertTrue(all(item['total']==1 for item in dimension['items']))
