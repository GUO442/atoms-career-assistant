import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import boss_web_greet as G

TEXT = '看到贵司在做Agent评测体系建设，我负责过银行Agent多轮对话测试和Python自动化框架，希望交流岗位契合点。'
JOB = {'job_id': 'j1', 'platform': 'boss', 'company': '测试公司', 'title': 'AI测试',
       'recruiter': '张三', 'recruiter_id': None, 'url': 'https://www.zhipin.com/job_detail/j1.html'}
STATE = {'url': 'https://www.zhipin.com/job_detail/j1.html', 'title': 'AI测试',
         'h1': ['AI测试'], 'immediate': True, 'ongoing': False, 'editable': False,
         'body': '测试公司 AI测试 立即沟通'}


class Sender:
    def __init__(self, receipt):
        self.receipt = receipt
        self.calls = []

    def __call__(self, action):
        self.calls.append(action)
        return self.receipt


class WebGreetTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'data/ui-chat').mkdir(parents=True)

    def run_adapter(self, state, conversation, receipt):
        sender = Sender(receipt)
        who = {**conversation}
        if who:
            who.setdefault('target', {'webSocketDebuggerUrl': 'ws://local/x'})
        send_result = {'sent': True}
        with mock.patch.object(G, 'open_job_page', lambda url: '/job_detail/j1.html'), \
             mock.patch.object(G, 'wait_for', lambda *a, **k: state), \
             mock.patch.object(G, 'evaluate', lambda path, expr: {'clicked': True}), \
             mock.patch.object(G, 'wait_conversation', lambda *a, **k: who), \
             mock.patch.object(G, 'send_on', lambda *a: send_result), \
             mock.patch.object(G.WebGreetAdapter, '_wait_receipt', lambda self, *a: receipt):
            result = G.WebGreetAdapter(self.root).run(dict(JOB), TEXT)
        return result, sender

    def test_probe_never_clicks(self):
        def boom(*a, **k):
            raise AssertionError('probe must not click')
        with mock.patch.object(G, 'open_job_page', lambda url: '/job_detail/j1.html'), \
             mock.patch.object(G, 'wait_for', lambda *a, **k: STATE), \
             mock.patch.object(G, 'evaluate', boom), \
             mock.patch.object(G, 'wait_conversation', boom):
            result = G.WebGreetAdapter(self.root, dry_run=True).run(dict(JOB), TEXT)
        self.assertEqual(result['entry'], 'immediate')
        self.assertFalse(result['clicked_send'])
        self.assertNotIn('status', result)

    def test_first_contact_sends_custom_text_after_default(self):
        receipt = {'verified_sent': True, 'receipt': {'message_id': 'm1'}}
        result, sender = self.run_adapter(STATE, {'job': 'j1', 'uid': 'u1'}, receipt)
        self.assertEqual(result['status'], 'sent')
        self.assertTrue(result['first_contact_attempted'])
        self.assertEqual(result['receipt']['message_id'], 'm1')

    def test_failure_after_entry_click_is_unknown_not_blocked(self):
        result, sender = self.run_adapter(STATE, {}, {'verified_sent': False})
        self.assertEqual(result['status'], 'unknown')
        self.assertEqual(sender.calls, [])
        self.assertTrue(result['first_contact_attempted'])

    def test_unverified_receipt_stays_unknown(self):
        receipt = {'verified_sent': False, 'reason': '请求已发起，但未能从历史接口核验结果；请查看聊天，不自动重试'}
        result, _ = self.run_adapter(STATE, {'job': 'j1', 'uid': 'u1'}, receipt)
        self.assertEqual(result['status'], 'unknown')

    def test_page_mismatch_blocks_before_any_click(self):
        bad = {**STATE, 'h1': ['别的岗位']}
        with mock.patch.object(G, 'open_job_page', lambda url: '/job_detail/j1.html'), \
             mock.patch.object(G, 'wait_for', lambda *a, **k: bad):
            result = G.WebGreetAdapter(self.root).run(dict(JOB), TEXT)
        self.assertEqual(result['status'], 'blocked')
        self.assertFalse(result['first_contact_attempted'])

    def test_gate_blocks_send_but_not_probe(self):
        gate = self.root / 'data/ui-chat/security-blocked.json'
        gate.write_text('{"reason":"platform_security_verification"}')
        result = G.WebGreetAdapter(self.root).run(dict(JOB), TEXT)
        self.assertEqual(result['status'], 'blocked')
        with mock.patch.object(G, 'open_job_page', lambda url: '/job_detail/j1.html'), \
             mock.patch.object(G, 'wait_for', lambda *a, **k: STATE):
            probe = G.WebGreetAdapter(self.root, dry_run=True).run(dict(JOB), TEXT)
        self.assertEqual(probe['entry'], 'immediate')


if __name__ == '__main__':
    unittest.main()
