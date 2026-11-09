"""Read-only job dashboard: unique platform jobs and explicit metric denominators."""
import re
from collections import Counter
from urllib.parse import urlsplit
from career_tracking import STATES, LABELS

PLATFORM_NAMES = {'boss': 'BOSS直聘', '51job': '前程无忧', 'zhaopin': '智联招聘'}


def platform_label(key):
    if key in PLATFORM_NAMES:
        return PLATFORM_NAMES[key]
    try:
        from official_careers import ADAPTERS
        if key in ADAPTERS:
            return ADAPTERS[key]['name']
    except Exception:
        pass
    return key


def identity(job):
    platform = job.get('platform') or 'boss'
    key = job.get('job_id')
    if not key:
        match = re.fullmatch(r'/job_detail/([A-Za-z0-9_-]+)(?:\.html)?', urlsplit(job.get('url', '')).path)
        key = match.group(1) if match else None
    return (platform, key) if key else None


def category(title):
    """Exclusive title-based classification; ambiguous titles remain unclassified."""
    for pattern, label in [
        (r'测试|测开|评测|测评|\bqa\b|sdet', '测试与评测'),
        (r'算法|AI|人工智能|大模型|Agent|RAG|LLM', 'AI与算法'),
        (r'前端|frontend', '前端开发'),
        (r'后端|Java|Python|Golang|全栈|研发|软件开发|开发工程师|C\+\+', '后端与软件开发'),
        (r'数据|数仓', '数据工程'),
        (r'运维|DevOps|SRE|安全|网络', '运维与安全'),
        (r'产品|项目经理', '产品与项目'),
    ]:
        if re.search(pattern, title, re.I):
            return label
    return '其他或未分类'


def distribution(values, total, labels=None):
    counts = Counter(values)
    keys = list(labels or {}) + sorted(set(counts) - set(labels or {}))
    return [{'key': key, 'label': (labels or {}).get(key, key), 'count': counts[key],
             'total': total, 'percent': round(counts[key] * 100 / total, 1) if total else 0.0}
            for key in keys]


def reviewed_version(v):
    return bool(v.get('reviewed') and v.get('sha256') and v.get('reviewed_sha256') == v['sha256'])


def dashboard(history, tracking, library, chat_fields=None, preferences='', include_all=False):
    from matching_policy import assess
    from discovery import classify_job
    jobs = {}
    for source in (history.get('jobs', []), tracking.get('jobs', [])):
        for job in source:
            key = identity(job)
            if key:
                jobs[key] = {**jobs.get(key, {}), **job}
    versions = library.get('versions', [])
    applications = library.get('applications', [])
    for record in versions + applications:
        job = record.get('job') or {}
        key = identity(job)
        if key and key not in jobs:
            jobs[key] = dict(job)
    rows = []
    for key, job in jobs.items():
        related = [v for v in versions if identity(v.get('job') or {}) == key and v.get('kind') == 'tailored']
        job['recorded_states'] = {field:field in job for field in STATES}
        for field in STATES:
            # Missing observations are explicitly unknown, not inferred failures or successes.
            job.setdefault(field, 'unknown' if field in ('reply', 'greet', 'resume') else ('none' if field == 'interview' else 'open'))
        if chat_fields and key[0]=='boss':job.update(chat_fields.get(key[1],{}))
        job.setdefault('chat_phase','unknown');job.setdefault('contact_initiator','unknown');job.setdefault('needs_reply','unknown');job.setdefault('chat_qualification','unassessed')
        job['category'] = category(job.get('title', ''))
        job['platform'] = key[0]
        job['platform_name'] = platform_label(key[0])
        job['job_id'] = key[1]
        job['management_id'] = ':'.join(key)
        job['screening'] = ('excluded' if job.get('eligibility') == 'excluded' else job.get('decision', 'unassessed'))
        job['eligibility'], job['filter_reason'] = classify_job(job)
        assessment = assess(job, preferences)
        # Hybrid rule: a job the squad actually screened keeps the squad's verdict;
        # jobs the squad never screened fall back to the local rule engine.
        squad_verdict = job.get('squad_decision')
        decision = squad_verdict if squad_verdict in ('recommend', 'caution', 'reject') else assessment['decision']
        job['screening'] = 'excluded' if job.get('eligibility') == 'excluded' else decision
        job['decision'] = decision
        job['match'] = job.get('squad_match') or assessment['analysis']
        job['decision_source'] = 'squad' if decision == squad_verdict else 'rule'
        if not include_all and job['screening'] != 'recommend':
            continue
        job['resume_versions'] = len(related)
        job['resume_kinds'] = sorted(set('reviewed' if reviewed_version(v) else 'pending' for v in related) | ({'original'} if any(v.get('source_resume_id') for v in related) else set()))
        job['review'] = ('none' if not related else 'pending' if any(not reviewed_version(v) for v in related) else 'reviewed')
        job['labels'] = {field: LABELS[field].get(job[field], '状态未知') for field in STATES}
        job['labels']['review'] = {'none':'无定制简历','pending':'有待审核版本','reviewed':'版本均已审核'}[job['review']]
        rows.append(job)
    total = len(rows)
    dimensions = [{'key': 'category', 'title':'岗位类型', 'items':distribution([j['category'] for j in rows], total)},
                  {'key': 'platform', 'title':'平台来源', 'items':distribution([j['platform'] for j in rows], total, {p: platform_label(p) for p in sorted({j['platform'] for j in rows})})}]
    for field, title in [('greet','联系状态'),('reply','HR回复'),('resume','简历发送状态'),('interview','面试进度'),('outcome','最终结果')]:
        labels = dict(LABELS[field])
        if field in ('greet','resume'):labels['unknown'] = '状态未知或待核验'
        dimensions.append({'key':field,'title':title,'items':distribution([j[field] for j in rows],total,labels)})
    from chat_opportunities import PHASES,ORIGINS,QUALIFICATIONS
    for key,title,labels in [('chat_phase','聊天阶段',PHASES),('contact_initiator','沟通发起方',ORIGINS),('needs_reply','待我方回复',{'yes':'待回复','no':'无需回复','unknown':'未知'})]:
        dimensions.append({'key':key,'title':title,'items':distribution([j[key] for j in rows],total,labels)})
        for job in rows:job['labels'][key]=labels[job[key]]
    dimensions.append({'key':'review','title':'岗位简历审核','items':distribution([j['review'] for j in rows],total,{'none':'无定制简历','pending':'有待审核版本','reviewed':'版本均已审核'})})
    resume_labels = {'original':'原始简历','pending':'定制简历待审核','reviewed':'定制简历已审核'}
    resume_states = ['original' if v.get('kind') == 'original' else 'reviewed' if reviewed_version(v) else 'pending' for v in versions]
    return {'total':total, 'jobs':rows, 'dimensions':dimensions,
            'resume_total':len(versions), 'resume_distribution':distribution(resume_states,len(versions),resume_labels),
            'note':'岗位管理仅收录匹配通过的岗位。岗位按平台和岗位ID去重；岗位百分比以当前展示岗位为分母，简历百分比以文件版本数为分母。类型按岗位名称分类；未知状态不计为成功；跨平台岗位暂不自动合并。'}
