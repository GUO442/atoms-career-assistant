# -*- coding: utf-8 -*-
"""定时采集新岗位：只读推荐接口，每 10 分钟拉一页，跨天去重入库。

边界：只调用只读推荐接口；不打招呼、不定制、不投递、不联系招聘方。
遇到平台安全验证或限流（业务码 36/37）自动冷却暂停，冷却结束再继续。
"""
import json
import os
import threading
import time
from pathlib import Path

MAX_PAGE = 6


def env_interval():
    try:
        return max(60, int(os.environ.get('CAREER_COLLECT_TICK_SECONDS', '600')))
    except (TypeError, ValueError):
        return 600


class JobCollector:
    """后台定时采集器：线程永不退出，异常写状态后继续下一轮。"""

    def __init__(self, root, discovery, interval=None):
        self.root = Path(root)
        self.discovery = discovery
        self.interval = int(interval or env_interval())
        self.lock = threading.RLock()
        self.run_lock = threading.Lock()
        self.thread = None
        self.state_path = self.root / 'data' / 'collector-state.json'
        self.state = self._load_state()
        self.page = int(self.state.get('page') or 1)

    # ---------- 状态 ----------
    def _load_state(self):
        try:
            data = json.loads(self.state_path.read_text())
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return {'enabled': True, 'interval_seconds': self.interval, 'page': 1, 'cycles': 0,
                'last_run': 0, 'last_error': '', 'last_note': '',
                'totals': {'received': 0, 'new': 0, 'seen': 0}}

    def _save(self, **fields):
        with self.lock:
            self.state.update(fields)
            self.state['interval_seconds'] = self.interval
            self.state['page'] = self.page
            self.state['updated'] = time.time()
            try:
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                self.state_path.write_text(json.dumps(self.state, ensure_ascii=False))
            except Exception:
                pass

    def status(self):
        with self.lock:
            body = dict(self.state)
        try:
            body['library_total'] = self.discovery.history().get('total', 0)
        except Exception:
            body['library_total'] = None
        body['running'] = bool(self.thread and self.thread.is_alive())
        return body

    # ---------- 控制 ----------
    def start(self):
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self.loop, daemon=True, name='career-job-collector')
            self.thread.start()

    def set_enabled(self, enabled):
        self._save(enabled=bool(enabled), last_note='已' + ('启用' if enabled else '暂停') + '定时采集')
        return self.status()

    def run_now(self):
        """立即跑一轮（后台线程），返回当前状态。"""
        threading.Thread(target=self._run_once_safe, daemon=True, name='career-job-collector-now').start()
        return self.status()

    def loop(self):
        # 启动后先等一个间隔，避免与服务启动争抢 BOSS 页面
        while True:
            time.sleep(self.interval)
            try:
                self._run_once_safe()
            except Exception:
                pass

    def _run_once_safe(self):
        try:
            self.cycle()
        except Exception as exc:
            # 注意：cycle() 内部已计过一轮，这里只补记录错误，不重复计数
            self._save(last_run=time.time(), last_error=str(exc)[:500])

    # ---------- 冷却与安全 ----------
    def _cooldown_reason(self):
        if (self.root / 'data/ui-chat/security-blocked.json').exists():
            return '平台安全验证待处理，采集暂停'
        for name in ('data/collector-cooldown.json', 'data/jd-cooldown.json'):
            path = self.root / name
            try:
                data = json.loads(path.read_text())
                until = float(data.get('until') or 0)
                if until > time.time():
                    return f"BOSS 冷却中（{data.get('reason', '限流')}），剩余 {int(until - time.time())} 秒"
            except Exception:
                continue
        return None

    def _write_cooldown(self, seconds, reason):
        try:
            path = self.root / 'data/collector-cooldown.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'until': time.time() + seconds, 'reason': reason}, ensure_ascii=False))
        except Exception:
            pass

    # ---------- 单轮采集 ----------
    def cycle(self):
        """执行一轮采集；并发调用时直接跳过，保证同一时间只有一轮在跑。"""
        if not self.run_lock.acquire(blocking=False):
            return
        try:
            self._cycle_locked()
        finally:
            self.run_lock.release()

    def _cycle_locked(self):
        with self.lock:
            if not self.state.get('enabled', True):
                return
        reason = self._cooldown_reason()
        if reason:
            self._save(last_run=time.time(), last_error='', last_note='暂停：' + reason,
                       cycles=int(self.state.get('cycles', 0)) + 1)
            return

        page = max(1, self.page)
        try:
            data = self.discovery.call('recommend', {'kind': 'recommended', 'page': page})
        except ValueError as exc:
            text = str(exc)
            if '业务码 7' in text or 'AUTH_OR_RISK_REQUIRED' in text:
                self._write_cooldown(1800, 'BOSS 未登录或会话失效，请在 App 打开登录窗口扫码登录')
            elif '业务码 37' in text:
                self._write_cooldown(180, '推荐接口限流（业务码37），稍后继续')
            elif '业务码 36' in text or '验证' in text or '登录' in text:
                self._write_cooldown(1800, '需要人工处理 BOSS 安全验证/登录')
            self._save(last_run=time.time(), last_error=text[:500],
                       cycles=int(self.state.get('cycles', 0)) + 1)
            raise
        except Exception as exc:
            self._save(last_run=time.time(), last_error=str(exc)[:500],
                       cycles=int(self.state.get('cycles', 0)) + 1)
            raise

        items = (data or {}).get('items') if isinstance(data, dict) else None
        if not isinstance(items, list):
            self._save(last_run=time.time(), last_error='推荐接口结构变化，未入库',
                       cycles=int(self.state.get('cycles', 0)) + 1)
            return
        if not items:
            self.page = 1
            self._save(last_run=time.time(), last_error='', last_note=f'第{page}页没有数据，下一轮从第1页开始',
                       cycles=int(self.state.get('cycles', 0)) + 1)
            return

        result = {'jobs': [{**item} for item in items]}
        self.discovery.put(result, refresh=True)
        new = int(result.get('new_count') or 0)
        seen = int(result.get('seen_count') or 0)
        excluded = int(result.get('filtered_count') or 0)
        totals = self.state.get('totals') or {'received': 0, 'new': 0, 'seen': 0}
        totals = {'received': int(totals.get('received', 0)) + len(items),
                  'new': int(totals.get('new', 0)) + new,
                  'seen': int(totals.get('seen', 0)) + seen}
        has_more = bool((data or {}).get('has_more', True))
        self.page = page + 1 if (has_more and page < MAX_PAGE) else 1
        note = (f'第{page}页采集 {len(items)} 个，入库新增 {new}，重复 {seen}，'
                f'规则排除 {excluded}；下一轮第{self.page}页')
        self._save(last_run=time.time(), last_error='', last_note=note,
                   totals=totals, cycles=int(self.state.get('cycles', 0)) + 1)
        return result
