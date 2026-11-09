import unittest
from job_management import dashboard as _dashboard

def dashboard(*args,**kwargs):
    return _dashboard(*args,**kwargs,include_all=True)


class DashboardTests(unittest.TestCase):
    def test_empty_denominators(self):
        result = dashboard({}, {}, {})
        self.assertEqual(result['total'], 0)
        self.assertTrue(all(i['percent'] == 0 for d in result['dimensions'] for i in d['items']))

    def test_merge_history_tracking_and_resume_url(self):
        history = {'jobs':[{'job_id':'a','title':'AI测试工程师','decision':'recommend'}, {'job_id':'b','title':'Java开发工程师','decision':'caution'}]}
        tracking = {'jobs':[{'job_id':'a','greet':'sent','reply':'replied','resume':'unknown'}]}
        library = {'versions':[{'id':'v','kind':'tailored','job':{'url':'https://www.zhipin.com/job_detail/a.html'},'sha256':'x','reviewed':True,'reviewed_sha256':'old'}, {'kind':'original'}], 'applications':[{'job':{'job_id':'a'}}]}
        result = dashboard(history, tracking, library)
        self.assertEqual(result['total'], 2)
        self.assertEqual(result['resume_total'], 2)
        a = next(j for j in result['jobs'] if j['job_id']=='a')
        self.assertEqual(a['category'], '测试与评测')
        self.assertEqual(a['review'], 'pending')
        self.assertEqual(a['screening'], 'caution')  # Salary is absent: old recommend is not proof of meeting the current policy.
        dimensions = {d['key']:d['items'] for d in result['dimensions']}
        self.assertEqual(next(i for i in dimensions['reply'] if i['key']=='replied')['percent'], 50)
        self.assertEqual(next(i for i in dimensions['resume'] if i['key']=='sent')['count'], 0)
        self.assertTrue(all(sum(i['count'] for i in d['items']) == 2 for d in result['dimensions']))

    def test_distinct_platforms_and_unobserved_status(self):
        r = dashboard({'jobs':[{'job_id':'a','platform':'boss'}, {'job_id':'a','platform':'51job'}]}, {}, {})
        self.assertEqual(r['total'], 2)
        self.assertTrue(all(j['greet']=='unknown' for j in r['jobs']))

    def test_resume_only_job_and_reviewed_version(self):
        r = dashboard({}, {}, {'versions':[{'kind':'tailored','job':{'job_id':'a'},'sha256':'x','reviewed':True,'reviewed_sha256':'x'}]})
        self.assertEqual(r['total'], 1)
        self.assertEqual(r['jobs'][0]['review'], 'reviewed')
        self.assertEqual(next(i for i in r['resume_distribution'] if i['key']=='reviewed')['percent'], 100)

if __name__ == '__main__':unittest.main()

class DrilldownDataTests(unittest.TestCase):
    def test_platform_names_and_observed_platform_statistics(self):
        r = dashboard({'jobs':[{'job_id':'same','platform':'boss'}, {'job_id':'same','platform':'51job'}, {'job_id':'other','platform':'zhaopin'}]}, {}, {})
        self.assertEqual(r['total'],3)
        self.assertEqual({j['platform_name'] for j in r['jobs']},{'BOSS直聘','前程无忧','智联招聘'})
        platform = next(d for d in r['dimensions'] if d['key']=='platform')
        self.assertEqual({i['key']:i['count'] for i in platform['items']},{'boss':1,'51job':1,'zhaopin':1})
        # Every chart status must drill down to exactly its displayed job count.
        for d in r['dimensions']:
            for item in d['items']:
                self.assertEqual(item['count'],sum(j[d['key']]==item['key'] for j in r['jobs']))

    def test_resume_version_filter_is_per_job_and_preserves_both_states(self):
        versions=[{'kind':'original','id':'source'},
                  {'kind':'tailored','job':{'job_id':'a'},'source_resume_id':'source','sha256':'one','reviewed':True,'reviewed_sha256':'one'},
                  {'kind':'tailored','job':{'job_id':'a'},'sha256':'two','reviewed':False}]
        r=dashboard({'jobs':[{'job_id':'a'}, {'job_id':'b'}]}, {}, {'versions':versions})
        self.assertEqual(r['jobs'][0]['resume_kinds'],['original','pending','reviewed'])
        self.assertEqual(r['jobs'][1]['resume_kinds'],[])
