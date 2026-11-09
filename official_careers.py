# -*- coding: utf-8 -*-
"""Official company career-site job search over public HTTP APIs.

Unlike BOSS (which needs the user's logged-in Chrome), the official social
recruitment search endpoints of most Chinese internet companies are public:
they can be queried directly with a normal HTTP client, no login or cookie.

Each company is a declarative adapter. Only endpoints that were verified with a
real curl response are registered; a company that needs login / CSRF / signing
beyond a stateless double-submit token is reported as NOT_AVAILABLE and never
faked as an empty or fabricated list.
"""
import json
import re
import time
import uuid
from datetime import datetime, timezone
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from discovery import Discovery, classify_job, policy_metadata

UA = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
      'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36')
JOB_ID_RE = re.compile(r'[A-Za-z0-9._:-]{1,128}')
MAX_PER_COMPANY = 10
MAX_COMPANIES = 14


class WebError(ValueError):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


# --------------------------------------------------------------------------- #
# Declarative company adapters.  `url` and `params`/`json_body` support the
# placeholders {query}, {city}, {page}, {offset}, {limit}, {job_id},
# {timestamp}.  A whole-string placeholder preserves the raw type (int page).
# `fields` maps the raw JSON field name -> normalized key; `jd_fields` are
# concatenated (with newlines) into the JD text.  A field may be a dict
# {'path':..., 'sub':..., 'join':...} for list-of-object values.
# `csrf` marks a stateless double-submit token: {'cookie':..., 'header':...}.
# --------------------------------------------------------------------------- #
ADAPTERS = {
    'tencent': {
        'key': 'tencent',
        'name': '腾讯',
        'careers_url': 'https://careers.tencent.com/search.html',
        'origin': 'https://careers.tencent.com',
        'search': {
            'method': 'GET',
            'url': 'https://careers.tencent.com/tencentcareer/api/post/Query',
            'params': {'keyword': '{query}', 'pageIndex': '{page}', 'pageSize': '10'},
            'headers': {'Referer': 'https://careers.tencent.com/search.html'},
            'list_path': 'Data.Posts',
            'fields': {
                'job_id': 'PostId', 'title': 'RecruitPostName', 'company': None,
                'city': 'LocationName', 'salary': None,
                'experience': 'RequireWorkYearsName', 'education': None,
                'url': 'PostURL', 'url_template': None,
                'department': 'BGName', 'post_time': 'LastUpdateTime',
                'jd': None, 'jd_fields': ['Responsibility'],
            },
        },
        'detail': {
            'method': 'GET',
            'url': 'https://careers.tencent.com/tencentcareer/api/post/ByPostId',
            'params': {'postId': '{job_id}', 'timestamp': '{timestamp}'},
            'headers': {'Referer': 'https://careers.tencent.com/search.html'},
            'data_path': 'Data',
            'jd_fields': ['Requirement', 'Responsibility'],
            'fields': {'title': 'RecruitPostName', 'city': 'LocationName',
                       'salary': None, 'company': None},
        },
    },
    'bytedance': {
        'key': 'bytedance',
        'name': '字节跳动',
        'careers_url': 'https://jobs.bytedance.com/experienced/positions',
        'origin': 'https://jobs.bytedance.com',
        'search': {
            'method': 'POST',
            'url': 'https://jobs.bytedance.com/api/v1/search/job/posts',
            'json_body': {'limit': '{limit}', 'offset': '{offset}', 'keyword': '{query}'},
            'headers': {'Referer': 'https://jobs.bytedance.com/',
                        'Content-Type': 'application/json'},
            'list_path': 'data.job_post_list',
            'fields': {
                'job_id': 'id', 'title': 'title', 'company': None,
                'city': {'path': 'city_list', 'sub': 'name'},
                'salary': None, 'experience': None, 'education': None,
                'url': None,
                'url_template': 'https://jobs.bytedance.com/experienced/position/{job_id}/detail',
                'jd': None, 'jd_fields': ['description', 'requirement'],
            },
        },
    },
    'alibaba': {
        'key': 'alibaba',
        'name': '阿里巴巴',
        'careers_url': 'https://talent.alibaba.com/off-campus/position-list',
        'origin': 'https://talent.alibaba.com',
        'search': {
            'method': 'POST',
            'url': 'https://talent.alibaba.com/position/search',
            'json_body': {
                'channel': 'group_official_site', 'language': 'zh', 'key': '{query}',
                'pageIndex': '{page}', 'pageSize': 10, 'batchId': '', 'categories': '',
                'deptCodes': [], 'regions': '', 'subCategories': '',
            },
            'headers': {'Referer': 'https://talent.alibaba.com/off-campus/position-list',
                        'Content-Type': 'application/json'},
            'csrf': {'cookie': 'XSRF-TOKEN', 'header': 'x-xsrf-token'},
            'list_path': 'content.datas',
            'fields': {
                'job_id': 'id', 'title': 'name', 'company': None,
                'city': {'path': 'workLocations'},
                'salary': None, 'experience': 'experience', 'education': 'degree',
                'url': None,
                'url_template': 'https://talent.alibaba.com/off-campus/position-detail?positionId={job_id}',
                'jd': None, 'jd_fields': ['description', 'requirement'],
            },
        },
    },
    'baidu': {
        'key': 'baidu',
        'name': '百度',
        'careers_url': 'https://talent.baidu.com/jobs/social-list',
        'origin': 'https://talent.baidu.com',
        'search': {
            'method': 'POST',
            'url': 'https://talent.baidu.com/httservice/getPostListNew',
            'params': {
                'recruitType': 'SOCIAL', 'curPage': '{page}', 'pageSize': '10',
                'keyWord': '{query}', 'projectType': '', 'workPlace': '', 'postType': '',
            },
            'headers': {'Referer': 'https://talent.baidu.com/jobs/social-list',
                        'Content-Type': 'application/x-www-form-urlencoded;charset=utf-8'},
            'list_path': 'data.list',
            'fields': {
                'job_id': 'postId', 'title': 'name', 'company': None,
                'city': 'workPlace', 'salary': None, 'experience': 'workYears',
                'education': 'education',
                'url': None,
                'url_template': 'https://talent.baidu.com/jobs/detail/social/{job_id}',
                'jd': None, 'jd_fields': ['workContent', 'serviceCondition'],
            },
        },
    },
    'meituan': {
        'key': 'meituan',
        'name': '美团',
        'careers_url': 'https://zhaopin.meituan.com/web/social',
        'origin': 'https://zhaopin.meituan.com',
        'search': {
            'method': 'POST',
            'url': 'https://zhaopin.meituan.com/api/official/job/getJobList',
            'json_body': {
                'keywords': '{query}',
                'page': {'pageNo': '{page}', 'pageSize': 10},
                'jobShareType': '1',
                'jobType': [{'code': '3', 'subCode': []}],
                'cityList': [], 'department': [], 'jfJgList': [], 'typeCode': [],
                'specialCode': [],
            },
            'headers': {'Referer': 'https://zhaopin.meituan.com/web/social',
                        'Content-Type': 'application/json'},
            'list_path': 'data.list',
            'fields': {
                'job_id': 'jobUnionId', 'title': 'name', 'company': None,
                'city': {'path': 'cityList', 'sub': 'name'},
                'salary': None, 'experience': 'workYear', 'education': None,
                'url': None,
                'url_template': 'https://zhaopin.meituan.com/web/position/detail?jobUnionId={job_id}',
                'jd': None, 'jd_fields': ['jobDuty', 'jobRequirement'],
            },
        },
    },
    'antgroup': {
        'key': 'antgroup',
        'name': '蚂蚁集团',
        'careers_url': 'https://talent.antgroup.com/off-campus',
        'origin': 'https://talent.antgroup.com',
        'search': {
            'method': 'POST',
            'url': 'https://hrcareersweb.antgroup.com/api/social/position/search',
            'json_body': {
                'key': '{query}', 'regions': '', 'categories': '', 'subCategories': '',
                'bgCode': '', 'socialQrCode': '', 'pageIndex': '{page}', 'pageSize': 10,
                'channel': 'group_official_site',
            },
            'headers': {'Referer': 'https://talent.antgroup.com/off-campus',
                        'Content-Type': 'application/json'},
            'list_path': 'content',
            'fields': {
                'job_id': 'id', 'title': 'name', 'company': None,
                'city': {'path': 'workLocations'},
                'salary': None, 'experience': 'experience', 'education': 'degree',
                'url': None,
                'url_template': 'https://talent.antgroup.com/off-campus-position?positionId={job_id}',
                'jd': None, 'jd_fields': ['description', 'requirement'],
            },
        },
    },
    'didi': {
        'key': 'didi',
        'name': '滴滴',
        'careers_url': 'https://talent.didiglobal.com/social/',
        'origin': 'https://talent.didiglobal.com',
        'search': {
            'method': 'GET',
            'url': 'https://talent.didiglobal.com/recruit-portal-service/api/job/front/list',
            'params': {'page': '{page}', 'size': '10', 'jobName': '{query}'},
            'headers': {'Referer': 'https://talent.didiglobal.com/social/'},
            'list_path': 'data.items',
            'fields': {
                'job_id': 'jdId', 'title': 'jobName', 'company': None,
                'city': 'workArea', 'salary': None, 'experience': None, 'education': None,
                'url': None,
                'url_template': 'https://talent.didiglobal.com/social/jobDetail?jdId={job_id}',
                'department': 'deptName',
                'jd': None, 'jd_fields': ['jobDuty', 'jobQualification'],
            },
        },
    },
    'jd': {
        'key': 'jd',
        'name': '京东',
        'careers_url': 'https://zhaopin.jd.com/web/job/job_info_list/3',
        'origin': 'https://zhaopin.jd.com',
        'search': {
            'method': 'POST',
            'url': 'https://zhaopin.jd.com/web/job/job_list',
            'params': {
                'pageIndex': '{page}', 'pageSize': '10',
                'workCityJson': '[]', 'jobTypeJson': '[]', 'depTypeJson': '[]',
                'jobSearch': '{query}',
            },
            'headers': {'Referer': 'https://zhaopin.jd.com/web/job/job_info_list/3',
                        'X-Requested-With': 'XMLHttpRequest',
                        'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
            'list_path': None,
            'fields': {
                'job_id': 'id', 'title': 'positionNameOpen', 'company': None,
                'city': 'workCity', 'salary': None, 'experience': None, 'education': None,
                'url': None,
                'url_template': 'https://zhaopin.jd.com/web/job/job_info_detail/{job_id}',
                'department': 'positionDeptName',
                'post_time': 'formatPublishTime',
                'jd': None, 'jd_fields': ['workContent', 'qualification'],
            },
        },
    },
}


def _fill(template, ctx):
    if template is None:
        return None
    if isinstance(template, dict):
        return {k: _fill(v, ctx) for k, v in template.items()}
    if isinstance(template, list):
        return [_fill(v, ctx) for v in template]
    if isinstance(template, str):
        m = re.fullmatch(r'\{(\w+)\}', template)
        if m and m.group(1) in ctx:
            return ctx[m.group(1)]
        for key, val in ctx.items():
            template = template.replace('{' + key + '}', str(val))
        return template
    return template


def _resolve(obj, path):
    if not isinstance(path, str) or not path:
        return obj
    cur = obj
    for part in path.split('.'):
        if isinstance(cur, dict):
            cur = cur.get(part)
        else:
            return None
        if cur is None:
            return None
    return cur


def _csrf(spec):
    cs = spec.get('csrf')
    if not cs:
        return {}, {}
    token = uuid.uuid4().hex
    return {cs.get('header'): token}, {cs.get('cookie'): token}


def _request(method, url, params=None, json_body=None, headers=None, cookies=None,
             timeout=15):
    method = (method or 'GET').upper()
    req_headers = {'User-Agent': UA, 'Accept': 'application/json, text/plain, */*'}
    if headers:
        req_headers.update(headers)
    if cookies:
        req_headers['Cookie'] = '; '.join(k + '=' + v for k, v in cookies.items())
    data = None
    if params:
        if method == 'GET':
            url = url + ('&' if '?' in url else '?') + urlencode(params)
        else:
            req_headers.setdefault('Content-Type', 'application/x-www-form-urlencoded; charset=UTF-8')
            data = urlencode(params).encode('utf-8')
    if json_body is not None:
        req_headers.setdefault('Content-Type', 'application/json; charset=UTF-8')
        data = json.dumps(json_body, ensure_ascii=False).encode('utf-8')
    req = Request(url, data=data, headers=req_headers, method=method)
    try:
        with urlopen(req, timeout=timeout) as r:
            raw = r.read().decode('utf-8', 'replace')
    except HTTPError as e:
        raise WebError('HTTP_' + str(e.code), '官方接口返回 HTTP ' + str(e.code))
    except URLError as e:
        raise WebError('NETWORK_ERROR', '无法连接官方招聘接口：' + str(getattr(e, 'reason', e)))
    try:
        return json.loads(raw)
    except Exception:
        raise WebError('INVALID_JSON', '官方接口未返回JSON，可能接口已变更')


def _fmt_scalar(v):
    if v is None:
        return ''
    if isinstance(v, dict):
        if 'from' in v or 'to' in v:
            fr, to = v.get('from'), v.get('to')
            if fr is not None and to is not None:
                return str(fr) + '-' + str(to) + '年'
            if fr is not None:
                return str(fr) + '年以上'
            if to is not None:
                return str(to) + '年以内'
        return str(v)
    if isinstance(v, str):
        return v.strip()
    return str(v)


def _row_str(row, key):
    if not isinstance(row, dict) or not key:
        return ''
    if isinstance(key, dict):
        path = key.get('path')
        sub = key.get('sub')
        sep = key.get('join', '、')
        v = _resolve(row, path) if (isinstance(path, str) and '.' in path) else row.get(path)
        if isinstance(v, list):
            parts = []
            for e in v:
                if isinstance(e, dict) and sub:
                    e = e.get(sub)
                if e not in (None, ''):
                    parts.append(str(e).strip())
            return sep.join(parts)
        return _fmt_scalar(v)
    v = _resolve(row, key) if (isinstance(key, str) and '.' in key) else row.get(key)
    if isinstance(v, list):
        return '、'.join(str(e).strip() for e in v if e not in (None, ''))
    return _fmt_scalar(v)


def _search_one(adapter, query, city, page):
    spec = adapter.get('search') or {}
    ctx = {'query': query.strip(), 'city': city or '', 'page': page,
           'offset': (page - 1) * 10, 'limit': 10,
           'timestamp': str(int(time.time() * 1000))}
    url = _fill(spec.get('url'), ctx)
    params = _fill(spec.get('params'), ctx)
    body = _fill(spec.get('json_body'), ctx)
    csrf_headers, csrf_cookies = _csrf(spec)
    headers = {**(spec.get('headers') or {}), **csrf_headers}
    raw = _request(spec.get('method', 'GET'), url, params=params, json_body=body,
                   headers=headers, cookies=csrf_cookies)
    rows = _resolve(raw, spec.get('list_path'))
    if not isinstance(rows, list):
        raise WebError('INVALID_RESPONSE', '搜索响应缺少岗位列表，不能当作零结果')
    fields = spec.get('fields') or {}
    jobs = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        jid = _row_str(row, fields.get('job_id'))
        if not jid or not JOB_ID_RE.fullmatch(jid):
            continue
        jd_parts = [p for p in (_row_str(row, f) for f in (fields.get('jd_fields') or [])) if p]
        jd = '\n'.join(jd_parts) or _row_str(row, fields.get('jd'))
        url = _row_str(row, fields.get('url')) or ''
        if not url and fields.get('url_template'):
            url = str(fields['url_template']).replace('{job_id}', jid)
        job = {
            'job_id': jid,
            'platform': adapter['key'],
            'title': _row_str(row, fields.get('title')),
            'company': _row_str(row, fields.get('company')) or adapter['name'],
            'city': _row_str(row, fields.get('city')),
            'salary': _row_str(row, fields.get('salary')),
            'experience': _row_str(row, fields.get('experience')),
            'education': _row_str(row, fields.get('education')),
            'url': url,
            'source': 'official_careers',
            'collected_at': datetime.now(timezone.utc).isoformat(),
            'jd': jd,
            'status': 'listed',
        }
        for extra in ('department', 'post_time'):
            val = _row_str(row, fields.get(extra))
            if val:
                job[extra] = val
        jobs.append(job)
        if len(jobs) >= MAX_PER_COMPANY:
            break
    return jobs


def _detail_one(adapter, job_id):
    spec = adapter.get('detail') or {}
    ctx = {'job_id': job_id, 'timestamp': str(int(time.time() * 1000))}
    url = _fill(spec.get('url'), ctx)
    params = _fill(spec.get('params'), ctx)
    body = _fill(spec.get('json_body'), ctx)
    csrf_headers, csrf_cookies = _csrf(spec)
    headers = {**(spec.get('headers') or {}), **csrf_headers}
    raw = _request(spec.get('method', 'GET'), url, params=params, json_body=body,
                   headers=headers, cookies=csrf_cookies)
    obj = _resolve(raw, spec.get('data_path')) if spec.get('data_path') else raw
    jd_parts = []
    for f in (spec.get('jd_fields') or []):
        v = _resolve(obj, f) if isinstance(f, str) and '.' in f else (obj.get(f) if isinstance(obj, dict) else None)
        if isinstance(v, str) and v.strip():
            jd_parts.append(v.strip())
    description = '\n'.join(jd_parts)
    if not description:
        raise WebError('INVALID_RESPONSE', '未返回完整JD')
    fields = spec.get('fields') or {}
    return {
        'job_id': job_id,
        'platform': adapter['key'],
        'description': description,
        'title': _row_str(obj, fields.get('title')),
        'company': _row_str(obj, fields.get('company')) or adapter['name'],
        'city': _row_str(obj, fields.get('city')),
        'salary': _row_str(obj, fields.get('salary')),
        'url': adapter.get('origin', '') + '/',
        'source': 'official_careers',
    }


def catalog(args=None):
    items = [{'key': a['key'], 'name': a['name'], 'careers_url': a['careers_url'],
              'verified': True} for a in ADAPTERS.values()]
    return {'items': items, 'transport': 'direct public HTTP', 'source': 'official_careers',
            'note': '已注册 ' + str(len(items)) + ' 家公司官方招聘接口；仅收录经 curl 实测可用的接口。'}


def _selected_keys(companies):
    if companies in (None, '', 'all'):
        return list(ADAPTERS.keys())[:MAX_COMPANIES]
    if isinstance(companies, str):
        companies = [c.strip() for c in companies.split(',') if c.strip()]
    if not isinstance(companies, list):
        raise WebError('INVALID_ARGUMENT', 'companies 须为公司key列表或 all')
    unknown = [c for c in companies if c not in ADAPTERS]
    if unknown:
        raise WebError('UNKNOWN_COMPANY', '未注册的公司：' + ','.join(unknown))
    return companies


def search(args=None):
    args = args or {}
    query = args.get('query')
    if not isinstance(query, str) or not query.strip():
        raise WebError('INVALID_ARGUMENT', '请填写关键词')
    city = args.get('city') or ''
    page = args.get('page', 1)
    if not isinstance(page, int) or page < 1:
        raise WebError('INVALID_ARGUMENT', 'page 须为1以上整数')
    keys = _selected_keys(args.get('companies'))
    per = {}
    items = []
    for key in keys:
        adapter = ADAPTERS[key]
        try:
            jobs = _search_one(adapter, query, city, page)
            per[key] = {'ok': True, 'name': adapter['name'], 'count': len(jobs)}
            items.extend(jobs)
        except WebError as e:
            per[key] = {'ok': False, 'name': adapter['name'], 'code': e.code, 'error': str(e)}
        except Exception:
            per[key] = {'ok': False, 'name': adapter['name'],
                        'code': 'COMPANY_SEARCH_FAILED', 'error': '该公司接口执行失败'}
    ok = sum(1 for v in per.values() if v.get('ok'))
    failed = [(v['name'], v.get('error') or v.get('code')) for v in per.values() if not v.get('ok')]
    note = '已查询 ' + str(ok) + ' 家公司，共返回 ' + str(len(items)) + ' 个岗位'
    if failed:
        note += '；失败：' + '；'.join(n + ' ' + str(e) for n, e in failed)
    return {'items': items, 'query': query.strip(), 'city': city, 'page': page,
            'per_company': per, 'note': note, 'source': 'official_careers'}


def detail(args=None):
    args = args or {}
    job_id = args.get('job_id')
    platform = args.get('platform')
    if not isinstance(job_id, str) or not job_id.strip():
        raise WebError('INVALID_ARGUMENT', '需要 job_id')
    adapter = ADAPTERS.get(platform)
    if not adapter:
        raise WebError('UNKNOWN_COMPANY', '未注册的公司：' + str(platform))
    if not adapter.get('detail'):
        raise WebError('NO_DETAIL', '该公司的搜索接口已含完整JD，无需单独详情')
    return _detail_one(adapter, job_id)


def call(name, args=None):
    args = {} if args is None else args
    try:
        if not isinstance(args, dict):
            raise WebError('INVALID_ARGUMENT', '参数须为对象')
        if name == 'catalog':
            data = catalog(args)
        elif name == 'search':
            data = search(args)
        elif name == 'detail':
            data = detail(args)
        else:
            raise WebError('UNKNOWN_TOOL', '未注册的官方招聘工具')
        return {'ok': True, 'live': name in ('search', 'detail'), 'data': data}
    except WebError as e:
        return {'ok': False, 'live': False, 'error': {'code': e.code, 'message': str(e)}}
    except Exception:
        return {'ok': False, 'live': False,
                'error': {'code': 'OFFICIAL_TOOL_FAILED', 'message': '官方招聘工具执行失败，未自动重试'}}


class OfficialDiscovery(Discovery):
    """Discovery specialized for official careers: raw job ids + company platform,
    multi-company search, and composite `platform:job_id` detail handles."""

    def __init__(self, root, model):
        super().__init__(root, call, model, platform='official')

    @staticmethod
    def _find(d, handle):
        platform = None
        jid = handle
        if isinstance(handle, str) and ':' in handle:
            platform, jid = handle.split(':', 1)
        for j in d.get('jobs', []):
            if j.get('job_id') == jid and (platform is None or j.get('platform') == platform):
                return j
        return None

    def search(self, query, city='', companies=None, page=1):
        if not isinstance(query, str) or not query.strip():
            raise ValueError('请填写关键词')
        with self.lock:
            d = self.load()
            try:
                data = self.call('search', {'query': query, 'city': city or '',
                                            'companies': companies, 'page': page})
                items = (data or {}).get('items') or []
                if not isinstance(items, list):
                    raise ValueError('未识别查询结果格式')
                valid, skipped = [], 0
                for it in items:
                    jid = it.get('job_id', '')
                    if not isinstance(jid, str) or not JOB_ID_RE.fullmatch(jid):
                        skipped += 1
                        continue
                    valid.append(it)
                d = {'jobs': valid, 'status': 'searched', 'query': query.strip(),
                     'city': city or '', 'note': (data or {}).get('note') or '',
                     'per_company': (data or {}).get('per_company', {}),
                     'skipped_invalid': skipped}
                self.put(d, refresh=True)
                return d
            except ValueError as e:
                d.update(status='blocked', note=str(e))
                self.put(d)
                raise

    def read_detail(self, handle):
        with self.lock:
            d = self.load()
            job = self._find(d, handle)
            if not job:
                raise ValueError('未找到本次查询的岗位')
            platform = job.get('platform')
            if not platform:
                raise ValueError('岗位缺少来源公司标识')
            adapter = ADAPTERS.get(platform)
            if adapter and adapter.get('detail'):
                data = self.call('detail', {'job_id': job['job_id'], 'platform': platform})
                if not isinstance(data, dict) or not data.get('description'):
                    raise ValueError('未获得完整JD，不能生成简历')
                job.update(policy_metadata(data))
                if data.get('salary'):
                    job['salary'] = data['salary']
                job['jd'] = data['description']
            elif not job.get('jd'):
                raise ValueError('该岗位接口未返回JD')
            job['status'] = 'matched' if job.get('match') else 'jd_ready'
            self.put(d)
            eligibility, reason = classify_job(job)
            if eligibility == 'excluded':
                raise ValueError('岗位已排除：' + reason)
            return job

    def detail(self, handle, resume, preferences, consent):
        if not consent:
            raise ValueError('请同意将简历与JD发送模型')
        if not resume.strip():
            raise ValueError('请先导入真实简历')
        with self.lock:
            self.read_detail(handle)
            d = self.load()
            job = self._find(d, handle)
            from matching_policy import assess
            parsed = assess(job, preferences)
            job['match'] = parsed['analysis']
            job['decision'] = parsed['decision']
            job['status'] = 'matched'
            self.put(d)
            return job
