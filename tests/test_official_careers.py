import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import official_careers as oc
from official_careers import ADAPTERS, OfficialDiscovery, WebError


class AdapterEngineTests(unittest.TestCase):
    def test_fill_preserves_int_placeholder_and_nested(self):
        self.assertEqual(oc._fill({'pageNo': '{page}', 'size': 10}, {'page': 3}),
                         {'pageNo': 3, 'size': 10})
        self.assertEqual(oc._fill({'kw': '{query}'}, {'query': 'AI测试'}), {'kw': 'AI测试'})
        self.assertEqual(oc._fill({'n': {'a': '{offset}'}, 'l': [1, {'b': '{limit}'}]},
                                  {'offset': 20, 'limit': 10}),
                         {'n': {'a': 20}, 'l': [1, {'b': 10}]})

    def test_row_str_city_list_and_experience_dict(self):
        row = {'city_list': [{'name': '北京'}, {'name': '深圳'}],
               'experience': {'from': 3, 'to': None}, 'title': ' AI测试 '}
        self.assertEqual(oc._row_str(row, {'path': 'city_list', 'sub': 'name'}), '北京、深圳')
        self.assertEqual(oc._row_str(row, 'experience'), '3年以上')
        self.assertEqual(oc._row_str(row, 'title'), 'AI测试')

    def test_catalog_covers_registry(self):
        keys = [i['key'] for i in oc.catalog()['items']]
        for k in ADAPTERS:
            self.assertIn(k, keys)

    def test_every_adapter_has_required_spec(self):
        for key, ad in ADAPTERS.items():
            self.assertEqual(ad['key'], key)
            s = ad['search']
            self.assertIn('method', s)
            self.assertIn('url', s)
            self.assertIn('list_path', s)
            self.assertIn('job_id', s['fields'])
            self.assertIn('title', s['fields'])
            self.assertTrue(s['fields'].get('jd_fields') or s['fields'].get('jd'),
                            key + ' must map JD fields')


class CallTests(unittest.TestCase):
    def test_unknown_company(self):
        r = oc.call('search', {'query': 'AI测试', 'companies': 'notreal'})
        self.assertFalse(r['ok'])
        self.assertEqual(r['error']['code'], 'UNKNOWN_COMPANY')

    def test_missing_query(self):
        r = oc.call('search', {})
        self.assertFalse(r['ok'])
        self.assertEqual(r['error']['code'], 'INVALID_ARGUMENT')

    def test_search_failure_is_isolated_per_company(self):
        def boom(adapter, query, city, page):
            if adapter['key'] == 'tencent':
                raise WebError('HTTP_403', '被拦截')
            return [{'job_id': '1', 'platform': adapter['key'], 'title': '测试开发工程师',
                     'company': adapter['name'], 'city': '深圳', 'salary': '', 'experience': '',
                     'education': '', 'url': 'http://x/1', 'jd': '', 'status': 'listed',
                     'source': 'official_careers'}]
        with mock.patch.object(oc, '_search_one', side_effect=boom):
            d = oc.search({'query': '测试开发', 'page': 1})
        self.assertFalse(d['per_company']['tencent']['ok'])
        others = [k for k in d['per_company'] if k != 'tencent']
        self.assertTrue(others and all(d['per_company'][k]['ok'] for k in others))


class OfficialDiscoveryTests(unittest.TestCase):
    @staticmethod
    def _model(*a):
        return '{"decision":"recommend","analysis":"匹配"}'

    def test_search_dedup_and_filter(self):
        def fake_query(name, args):
            return {'ok': True, 'live': True, 'data': {'items': [
                {'job_id': 'a', 'platform': 'tencent', 'title': 'AI测试工程师', 'company': '腾讯',
                 'city': '深圳', 'url': 'http://x/a', 'jd': '', 'status': 'listed',
                 'source': 'official_careers'},
                {'job_id': 'b', 'platform': 'bytedance', 'title': '客服', 'company': '字节',
                 'city': '北京', 'url': 'http://x/b', 'jd': '', 'status': 'listed',
                 'source': 'official_careers'},
            ], 'per_company': {'tencent': {'ok': True, 'count': 1},
                               'bytedance': {'ok': True, 'count': 1}}, 'note': 'x'}}
        with tempfile.TemporaryDirectory() as tmp:
            d = OfficialDiscovery(tmp, self._model)
            d.query = fake_query
            r = d.search('AI测试')
        self.assertEqual([j['job_id'] for j in r['jobs']], ['a'])
        self.assertEqual(r['eligible_count'], 1)
        self.assertEqual(r['filtered_count'], 1)

    def test_invalid_job_id_is_skipped(self):
        def fake_query(name, args):
            return {'ok': True, 'data': {'items': [
                {'job_id': 'bad!id', 'platform': 'tencent', 'title': 'AI测试工程师',
                 'company': '腾讯', 'city': '深圳', 'url': '', 'jd': '', 'status': 'listed'},
                {'job_id': 'ok1', 'platform': 'tencent', 'title': '测试开发工程师',
                 'company': '腾讯', 'city': '深圳', 'url': '', 'jd': '', 'status': 'listed'},
            ], 'per_company': {}, 'note': 'x'}}
        with tempfile.TemporaryDirectory() as tmp:
            d = OfficialDiscovery(tmp, self._model)
            d.query = fake_query
            r = d.search('测试开发')
        self.assertEqual([j['job_id'] for j in r['jobs']], ['ok1'])
        self.assertEqual(r['skipped_invalid'], 1)

    def test_read_detail_without_detail_adapter_uses_search_jd(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = OfficialDiscovery(tmp, self._model)
            d.put({'jobs': [{'job_id': 'a', 'platform': 'bytedance', 'title': 'AI测试工程师',
                             'company': '字节', 'city': '北京', 'url': 'http://x/a',
                             'jd': '职责：xxx', 'status': 'listed', 'source': 'official_careers'}]})
            q = mock.Mock(return_value={'ok': False, 'error': {'code': 'X', 'message': 'y'}})
            d.query = q
            j = d.read_detail('bytedance:a')
            q.assert_not_called()
            self.assertEqual(j['jd'], '职责：xxx')
            self.assertEqual(j['status'], 'jd_ready')

    def test_read_detail_with_detail_adapter_calls_api(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = OfficialDiscovery(tmp, self._model)
            d.put({'jobs': [{'job_id': 'a', 'platform': 'tencent', 'title': 'AI测试工程师',
                             'company': '腾讯', 'city': '深圳', 'url': 'http://x/a',
                             'jd': '职责部分', 'status': 'listed', 'source': 'official_careers'}]})
            q = mock.Mock(return_value={'ok': True, 'live': True,
                                        'data': {'job_id': 'a', 'description': '完整JD',
                                                 'title': 'AI测试工程师'}})
            d.query = q
            j = d.read_detail('tencent:a')
            q.assert_called_once()
            self.assertEqual(j['jd'], '完整JD')

    def test_platform_specific_dedup(self):
        def fake_query(name, args):
            return {'ok': True, 'data': {'items': [
                {'job_id': 'same', 'platform': 'tencent', 'title': 'AI测试工程师',
                 'company': '腾讯', 'city': '深圳', 'url': '', 'jd': '', 'status': 'listed'},
                {'job_id': 'same', 'platform': 'bytedance', 'title': '测试开发工程师',
                 'company': '字节', 'city': '北京', 'url': '', 'jd': '', 'status': 'listed'},
            ], 'per_company': {}, 'note': 'x'}}
        with tempfile.TemporaryDirectory() as tmp:
            d = OfficialDiscovery(tmp, self._model)
            d.query = fake_query
            r = d.search('测试开发')
        # same raw id under different platforms must both survive
        self.assertEqual(sorted((j['platform'], j['job_id']) for j in r['jobs']),
                         [('bytedance', 'same'), ('tencent', 'same')])


if __name__ == '__main__':
    unittest.main()
