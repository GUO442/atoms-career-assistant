import json
import tempfile
import time
import unittest
from pathlib import Path

from job_collector import JobCollector


def item(i):
    return {'job_id': f'job{i}', 'title': 'AI测试开发', 'company': '真实公司',
            'city': '深圳', 'salary': '30-40K', 'url': f'https://www.zhipin.com/job_detail/job{i}.html'}


class FakeDiscovery:
    def __init__(self, batches):
        self.batches = list(batches)
        self.calls = []
        self.saved = []

    def call(self, name, args):
        self.calls.append((name, dict(args)))
        if not self.batches:
            raise ValueError('BOSS 接口返回业务码 37：访问过于频繁')
        return self.batches.pop(0)

    def put(self, d, refresh=False):
        self.saved.extend(d['jobs'])
        d['new_count'] = len(d['jobs'])
        d['seen_count'] = 0
        d['filtered_count'] = 0
        return d

    def history(self):
        return {'jobs': self.saved, 'total': len(self.saved)}


class CollectorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / 'data').mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_interval_is_ten_minutes(self):
        c = JobCollector(self.root, FakeDiscovery([]))
        self.assertEqual(c.interval, 600)
        self.assertEqual(c.status()['interval_seconds'], 600)

    def test_cycle_persists_new_jobs_and_paginates(self):
        fake = FakeDiscovery([{'items': [item(1), item(2)], 'has_more': True}])
        c = JobCollector(self.root, fake)
        c.cycle()
        self.assertEqual(fake.calls[0][0], 'recommend')
        self.assertEqual(fake.calls[0][1], {'kind': 'recommended', 'page': 1})
        self.assertEqual(len(fake.saved), 2)
        self.assertEqual(c.page, 2)
        state = json.loads((self.root / 'data/collector-state.json').read_text())
        self.assertEqual(state['cycles'], 1)
        self.assertEqual(state['totals'], {'received': 2, 'new': 2, 'seen': 0})
        self.assertIn('第1页', state['last_note'])
        self.assertEqual(state['last_error'], '')

    def test_last_page_resets_to_first(self):
        fake = FakeDiscovery([{'items': [item(1)], 'has_more': False}])
        c = JobCollector(self.root, fake)
        c.cycle()
        self.assertEqual(c.page, 1)

    def test_security_blocked_pauses_without_querying(self):
        (self.root / 'data/ui-chat').mkdir()
        (self.root / 'data/ui-chat/security-blocked.json').write_text('{}')
        fake = FakeDiscovery([{'items': [item(1)], 'has_more': True}])
        c = JobCollector(self.root, fake)
        c.cycle()
        self.assertEqual(fake.calls, [])
        state = json.loads((self.root / 'data/collector-state.json').read_text())
        self.assertIn('暂停', state['last_note'])

    def test_code_37_writes_cooldown_and_stops_next_cycle(self):
        fake = FakeDiscovery([])
        c = JobCollector(self.root, fake)
        with self.assertRaises(ValueError):
            c.cycle()
        cooldown = json.loads((self.root / 'data/collector-cooldown.json').read_text())
        self.assertGreater(cooldown['until'], time.time())
        self.assertIn('限流', cooldown['reason'])
        calls = len(fake.calls)
        c.cycle()  # 冷却期内不再发起请求
        self.assertEqual(len(fake.calls), calls)

    def test_disabled_skips_work(self):
        fake = FakeDiscovery([{'items': [item(1)], 'has_more': True}])
        c = JobCollector(self.root, fake)
        c.set_enabled(False)
        c.cycle()
        self.assertEqual(fake.calls, [])
        self.assertFalse(c.status()['enabled'])

    def test_error_is_recorded_without_killing_thread_state(self):
        fake = FakeDiscovery([])
        c = JobCollector(self.root, fake)
        c._run_once_safe()
        state = json.loads((self.root / 'data/collector-state.json').read_text())
        self.assertTrue(state['last_error'])
        self.assertEqual(state['cycles'], 1)
