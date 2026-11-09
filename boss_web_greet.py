# -*- coding: utf-8 -*-
"""First-contact greeting through the user's own logged-in Chrome (CDP 18744).

The headless path in boss_ui_chat.py launches a fresh Chromium with exported
cookies; BOSS treats that fingerprint as risky (code 36 / verify page). This
adapter instead drives the persistent, already-verified browser the user is
logged into, so no cookie export and no new fingerprint is involved.

Observed page behaviour (2026-11-05): clicking 立即沟通/继续沟通 navigates the tab
to /web/geek/chat with that conversation selected. The custom text is therefore
sent by the same page SDK channel PageReplyAdapter already verifies, and the
receipt must come from the history API. A missing receipt stays unknown and is
never retried.
"""
import json
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

import boss_web
from boss_ui_chat import UIBlocked, challenge, validate_job
from runtime_paths import WORKSPACE

CHAT_PATH = '/web/geek/chat'
HISTORY = '/wapi/zpchat/geek/historyMsg'
EDITOR = '[placeholder="请简短描述您的问题"]'

STATE = """(()=>{const vis=e=>!!(e&&e.getClientRects().length);
 const el=[...document.querySelectorAll('a.btn-startchat,a[class*="startchat"]')].filter(vis)[0];
 const entry=el?(el.innerText||'').trim():'';
 const ed=document.querySelector('%s')||document.querySelector('[contenteditable="true"]');
 const body=document.body?document.body.innerText:'';
 return {url:location.href,title:document.title,h1:[...document.querySelectorAll('h1')].map(e=>e.innerText.trim()).filter(Boolean),
  immediate:entry==='立即沟通',ongoing:entry==='继续沟通',entryText:entry,editable:vis(ed),
  body:body.slice(0,800)};})()""" % EDITOR

CHAT_STATE = """(()=>{const c=window.chat&&window.chat.communicating;
 const q=[document.getElementById('wrap')&&document.getElementById('wrap').__vue__];let ed=null;
 while(q.length){const v=q.shift();if(!v)continue;if(v.$options&&v.$options.name==='Editor'){ed=v;break}q.push(...(v.$children||[]))}
 return {url:location.href,communicating:c?{job:String(c.encryptJobId||''),uid:String(c.uid||'')}:null,
  hasEditor:!!ed,canSend:!!(ed&&ed.enableSubmit)};})()"""

SEND_ON = """(async()=>{const p=PAYLOAD;
 const c=window.chat&&window.chat.communicating;
 if(!c||c.encryptJobId!==p.job||String(c.uid)!==String(p.uid))return {sent:false,reason:'会话身份不匹配'};
 if(!window._PAGE||!window._PAGE.uid)return {sent:false,reason:'未确认求职账号身份'};
 const q=[document.getElementById('wrap')&&document.getElementById('wrap').__vue__];let ed=null;
 while(q.length){const v=q.shift();if(!v)continue;if(v.$options&&v.$options.name==='Editor'){ed=v;break}q.push(...(v.$children||[]))}
 if(!ed||typeof ed.sendText!=='function'||!ed.$refs||!ed.$refs.editbox)return {sent:false,reason:'页面SDK结构变化，未发送'};
 if((ed.getInputText()||'').trim())return {sent:false,reason:'输入框有未发送草稿，未覆盖'};
 ed.$refs.editbox.textContent=p.text;
 ed.$refs.editbox.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:p.text}));
 await new Promise(r=>ed.$nextTick(r));
 if((ed.getInputText()||'')!==p.text)return {sent:false,reason:'输入内容校验失败，未发送'};
 for(let i=0;i<30&&!ed.enableSubmit;i++)await new Promise(r=>setTimeout(r,100));
 if(!ed.enableSubmit)return {sent:false,reason:'发送按钮尚不可用，未发送'};
 ed.sendText();return {sent:true,self_uid:String(window._PAGE.uid)};})()"""

CLICK = """(()=>{const n=%s;const vis=e=>!!(e&&e.getClientRects().length);
 const el=[...document.querySelectorAll('a.btn-startchat,a[class*="startchat"]')]
  .find(e=>vis(e)&&(e.innerText||'').trim()===n);if(!el)return {clicked:false,reason:'entry_missing'};
 el.click();return {clicked:true};})()"""


def _page_for(path):
    return next((t for t in boss_web.targets() if urlsplit(t.get('url', '')).path == path), None)


def open_job_page(url):
    """Reuse an existing job tab or open exactly one new one; returns its path."""
    path = urlsplit(url).path
    if _page_for(path):
        return path
    target = f'{boss_web.DEBUG}/json/new?' + quote(url, safe='')
    for method in ('PUT', 'GET'):
        try:
            urlopen(Request(target, method=method), timeout=5).read()
            break
        except Exception:
            continue
    deadline = time.monotonic() + 15
    while time.monotonic() < deadline:
        if _page_for(path):
            return path
        time.sleep(0.3)
    raise UIBlocked('无法在专用浏览器中打开岗位页；请确认登录窗口仍打开')


def evaluate(path, expression):
    return boss_web.evaluate(expression, target_path=path)


def wait_for(path, expression, accept, timeout=20, interval=0.4):
    deadline = time.monotonic() + timeout
    last = {}
    while time.monotonic() < deadline:
        last = evaluate(path, expression)
        if accept(last):
            return last
        time.sleep(interval)
    return last


def _chat_targets():
    return [t for t in boss_web.targets() if urlsplit(t.get('url', '')).path == CHAT_PATH]


def _eval_target(wsurl, expression, timeout=35):
    """Evaluate on one exact tab; boss_web.evaluate picks only the first chat tab."""
    import websocket
    ws = websocket.create_connection(wsurl, timeout=timeout, suppress_origin=True)
    try:
        ws.send(json.dumps({'id': 1, 'method': 'Runtime.evaluate',
                            'params': {'expression': expression, 'awaitPromise': True, 'returnByValue': True}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = json.loads(ws.recv())
            if data.get('id') != 1:
                continue
            result = data.get('result') or {}
            if data.get('error') or result.get('exceptionDetails'):
                return {}
            value = (result.get('result') or {}).get('value')
            return value if isinstance(value, dict) else {}
        return {}
    finally:
        ws.close()


DIALOG = """(()=>{const d=document.querySelector('.startchat-dialog');if(!d||!d.getClientRects().length)return {open:false};
 const ta=d.querySelector('textarea.input-area')||d.querySelector('[contenteditable="true"]');
 const b=d.querySelector('.send-message');
 return {open:true,editable:!!ta,text:ta?((ta.value!==undefined?ta.value:ta.innerText)||''):'',
  disabled:b?b.classList.contains('disable'):true,name:(d.innerText||'').slice(0,80)};})()"""

FILL_INLINE = """(()=>{const t=TEXT;const d=document.querySelector('.startchat-dialog');
 const ta=d.querySelector('textarea.input-area')||d.querySelector('[contenteditable="true"]');
 if(!ta)return {filled:false,reason:'no_editor'};
 if(ta.value!==undefined){ta.value=t;ta.dispatchEvent(new Event('input',{bubbles:true}));ta.dispatchEvent(new Event('change',{bubbles:true}));}
 else{ta.focus();document.execCommand('insertText',false,t);ta.dispatchEvent(new InputEvent('input',{bubbles:true,inputType:'insertText',data:t}));}
 const cur=ta.value!==undefined?ta.value:ta.innerText;
 return {filled:(cur||'').trim()===t};})()"""

SEND_INLINE = """(()=>{const d=document.querySelector('.startchat-dialog');
 const b=d&&d.querySelector('.send-message');if(!b)return {clicked:false,reason:'send_missing'};
 if(b.classList.contains('disable'))return {clicked:false,reason:'send_disabled'};
 b.click();return {clicked:true};})()"""


def _cdp_target(wsurl, method, params=None, timeout=35):
    import websocket
    ws = websocket.create_connection(wsurl, timeout=timeout, suppress_origin=True)
    try:
        ws.send(json.dumps({'id': 1, 'method': method, 'params': params or {}}))
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            data = json.loads(ws.recv())
            if data.get('id') == 1:
                return data.get('result') or {}
        return {}
    finally:
        ws.close()


def inline_dialog(path):
    return evaluate(path, DIALOG)


def send_inline(path, job, text):
    """Type into the in-page chat dialog with real key input, then submit it.

    Setting textarea.value does not reach the component model, so the page keeps
    an empty draft and the send button never enables. CDP Input.insertText does.
    """
    state = inline_dialog(path)
    if not state.get('open'):
        return {'opened': False}
    if not state.get('editable'):
        raise UIBlocked('聊天弹窗无输入框，未发送')
    if (state.get('text') or '').strip():
        raise UIBlocked('聊天弹窗已有草稿，未覆盖')
    target = _page_for(path)
    if not target:
        raise UIBlocked('岗位页已关闭，未发送')
    focused = evaluate(path, """(()=>{const d=document.querySelector('.startchat-dialog');
 const ta=d&&(d.querySelector('textarea.input-area')||d.querySelector('[contenteditable="true"]'));
 if(!ta)return {ok:false};ta.focus();return {ok:true};})()""")
    if not focused.get('ok'):
        raise UIBlocked('弹窗输入框无法聚焦，未发送')
    _cdp_target(target['webSocketDebuggerUrl'], 'Input.insertText', {'text': text})
    for _ in range(30):
        state = inline_dialog(path)
        if (state.get('text') or '').strip() == text.strip() and not state.get('disabled'):
            break
        time.sleep(0.1)
    if (state.get('text') or '').strip() != text.strip():
        raise UIBlocked('弹窗输入内容校验失败，未发送')
    if state.get('disabled'):
        raise UIBlocked('弹窗发送按钮尚不可用，未发送')
    clicked = evaluate(path, SEND_INLINE)
    if not clicked.get('clicked'):
        raise UIBlocked('弹窗发送按钮不可用，未发送')
    return {'opened': True, 'sent': True}


def send_on(target, job, uid, text):
    """Send through the page SDK of exactly this tab, never a different chat tab."""
    expr = SEND_ON.replace('PAYLOAD', json.dumps({'job': job['job_id'], 'uid': str(uid), 'text': text}, ensure_ascii=False))
    return _eval_target(target['webSocketDebuggerUrl'], expr)


OPEN_CHAT = """(()=>{const p=PAYLOAD;const c=window.chat&&window.chat.communicating;
 if(c&&c.encryptJobId===p.job&&String(c.uid)===String(p.uid))return {already:true};
 const q=[document.getElementById('wrap')&&document.getElementById('wrap').__vue__];let t=null;
 while(q.length){const v=q.shift();if(!v)continue;
  if(v.$options&&v.$options.name==='boss-item'&&v.source&&v.source.encryptJobId===p.job&&String(v.source.uid)===String(p.uid)){t=v;break}
  q.push(...(v.$children||[]))}
 if(!t||typeof t.handleOpenChat!=='function')return {opened:false};
 t.handleOpenChat();return {opened:true};})()"""


def ensure_conversation(job, uid, timeout=15):
    """Open the contact in a chat tab, then prove the tab holds that conversation."""
    payload = json.dumps({'job': job['job_id'], 'uid': str(uid)}, ensure_ascii=False)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for target in _chat_targets():
            state = _eval_target(target['webSocketDebuggerUrl'], OPEN_CHAT.replace('PAYLOAD', payload))
            if state.get('already') or state.get('opened'):
                deadline2 = time.monotonic() + 6
                while time.monotonic() < deadline2:
                    check = _eval_target(target['webSocketDebuggerUrl'], CHAT_STATE)
                    who = check.get('communicating') or {}
                    if who.get('job') == job['job_id'] and str(who.get('uid')) == str(uid):
                        return target
                    time.sleep(0.3)
        time.sleep(0.4)
    return None


def wait_conversation(job, path=None, timeout=25):
    """After the entry click, find the tab that holds exactly this conversation.

    The click may navigate to the chat page, or add the contact without
    navigating (observed 2026-11-05). Several chat tabs may be open, so every
    candidate is checked and a created contact is accepted as evidence.
    """
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for target in _chat_targets():
            state = _eval_target(target['webSocketDebuggerUrl'], CHAT_STATE)
            who = state.get('communicating') or {}
            if who.get('job') == job['job_id'] and who.get('uid'):
                return {**who, 'hasEditor': state.get('hasEditor'), 'via': 'tab', 'target': target}
        if path and _page_for(path):
            try:
                dialog = inline_dialog(path)
            except Exception:
                dialog = {}
            name = (job.get('recruiter') or '').split(' · ')[0].strip()
            if dialog.get('open') and (not name or name in (dialog.get('name') or '')):
                return {'job': job['job_id'], 'uid': '', 'inline': True, 'hasEditor': dialog.get('editable'), 'via': 'inline'}
        contact = contact_of(job)
        if contact.get('uid'):
            return {'job': job['job_id'], 'uid': contact['uid'], 'hasEditor': False, 'via': 'contact'}
        time.sleep(0.4)
    return {}


def contact_of(job):
    """Look the conversation up in every chat tab's store, then in the friend list."""
    expr = """(()=>{const j=%s;const fs=Object.values((window.chatStore&&window.chatStore.friendInfos)||{});
 const c=fs.find(x=>x.encryptJobId===j);return c?{uid:String(c.uid),encryptBossId:c.encryptBossId,securityId:c.securityId}:{uid:''};})()""" % json.dumps(job['job_id'], ensure_ascii=False)
    for target in _chat_targets():
        found = _eval_target(target['webSocketDebuggerUrl'], expr)
        if found.get('uid'):
            return found
    try:
        data = boss_web.request('/wapi/zprelation/friend/getGeekFriendList.json', 'GET', {'page': 1},
                                target_path=CHAT_PATH if _chat_targets() else None)
    except Exception:
        return {}
    for row in data.get('result') or []:
        if isinstance(row, dict) and row.get('encryptJobId') == job['job_id'] and row.get('uid'):
            return {'uid': str(row['uid']), 'encryptBossId': row.get('encryptBossId'), 'securityId': row.get('securityId')}
    return {}


class WebGreetAdapter:
    """Opens the verified entry in the persistent browser, then reuses the page SDK sender."""

    verified = True
    supported_kinds = {'reply_text'}
    supports_first_contact = True

    def __init__(self, root=WORKSPACE, dry_run=False, allow_existing=False):
        self.root = Path(root)
        self.dry_run = dry_run
        self.allow_existing = allow_existing

    def __call__(self, action):
        if action.get('kind') != 'reply_text':
            raise UIBlocked('仅支持文本，不发送附件')
        job = next((j for j in self._listing() if j.get('platform') == 'boss' and j.get('job_id') == action.get('job_id')), None)
        if not job:
            raise UIBlocked('岗位未入库')
        if action.get('recruiter_id') and str(job.get('recruiter_id')) != str(action.get('recruiter_id')):
            raise UIBlocked('岗位或HR身份不匹配')
        return self.run(job, action.get('reply_text', ''))

    def _listing(self):
        from greeting_tools import Greetings
        return Greetings(self.root).listing()

    def _save(self, folder, result, label):
        record = folder / (label + '.json')
        record.write_text(json.dumps(result, ensure_ascii=False, indent=2))
        record.chmod(0o600)

    def run(self, job, text):
        gate = self.root / 'data/ui-chat/security-blocked.json'
        # The gate belongs to the send path; a read-only probe must still be able
        # to tell the operator whether the live browser is healthy.
        if gate.exists() and not self.dry_run:
            return {'verified_sent': False, 'status': 'blocked',
                    'reason': 'SECURITY_VERIFICATION_REQUIRED：请先人工完成平台验证，再明确解除暂停；未启动浏览器'}
        url, name = validate_job(job)
        if not isinstance(text, str) or not 20 <= len(text) <= 200:
            raise UIBlocked('定制消息须为20至200字')
        folder = self.root / 'data/ui-chat' / uuid.uuid4().hex
        folder.mkdir(parents=True, exist_ok=True)
        folder.chmod(0o700)
        result = {'verified_sent': False, 'dry_run': self.dry_run, 'job_id': job['job_id'],
                  'transport': 'persistent_chrome', 'evidence_dir': str(folder),
                  'clicked_send': False, 'first_contact_attempted': False}
        path = open_job_page(url)
        try:
            state = wait_for(path, STATE, lambda s: (bool(s.get('h1')) and bool(s.get('entryText')))
                             or '安全验证' in (s.get('body') or '') or '职位已关闭' in (s.get('body') or ''))
            if challenge(state.get('url', ''), state.get('body', '')):
                raise UIBlocked('SECURITY_VERIFICATION_REQUIRED：页面要求安全验证，停止且不重试')
            if not any(job['title'] == h for h in state.get('h1') or []):
                raise UIBlocked('岗位标题未在页面唯一出现，停止操作')
            if job.get('company') and job['company'] not in state.get('body', ''):
                raise UIBlocked('页面企业与岗位记录不一致')
            body = state.get('body') or ''
            if '职位已关闭' in body or '该职位已下线' in body:
                raise UIBlocked('职位已关闭，无法打招呼')
            if not (state.get('immediate') or state.get('ongoing')):
                raise UIBlocked('未找到立即沟通或继续沟通入口，页面结构可能变化')
            result['entry'] = 'immediate' if state.get('immediate') else 'ongoing'
            result['stage'] = 'job-verified'
            self._save(folder, result, 'result')
            if self.dry_run:
                result.update({'reason': '已核对岗位页与沟通入口；仅检查，未点击、未填写、未发送'})
                return result
            if result['entry'] == 'ongoing' and not self.allow_existing:
                result.update({'status': 'skipped_existing',
                               'reason': '页面显示“继续沟通”（已有会话），未获准跟进该会话，未点击'})
                return result
            clicked = evaluate(path, CLICK % json.dumps('立即沟通' if state.get('immediate') else '继续沟通', ensure_ascii=False))
            if not clicked.get('clicked'):
                raise UIBlocked('沟通入口点击失败，未发送')
            result['first_contact_attempted'] = bool(state.get('immediate'))
            self._save(folder, result, 'result')
            who = wait_conversation(job, path)
            if not who:
                raise UIBlocked('点击后未确认该岗位会话建立，未发送')
            result.update({'stage': 'conversation-open', 'recruiter_uid': who.get('uid'), 'conversation_via': who.get('via')})
            self._save(folder, result, 'result')
            if who.get('target'):
                outcome = send_on(who['target'], job, who['uid'], text)
                if not outcome.get('sent'):
                    raise UIBlocked(outcome.get('reason') or '页面SDK未发送')
                result['clicked_send'] = True
                result['stage'] = 'send-click'
                self._save(folder, result, 'result')
                receipt = self._wait_receipt(job, text, time.time())
            elif who.get('inline'):
                outcome = send_inline(path, job, text)
                if not outcome.get('sent'):
                    raise UIBlocked('聊天弹窗未发送')
                result['clicked_send'] = True
                result['stage'] = 'inline-sent'
                self._save(folder, result, 'result')
                contact = {}
                for _ in range(25):
                    contact = contact_of(job)
                    if contact.get('uid'):
                        break
                    time.sleep(0.8)
                if contact.get('uid'):
                    result['recruiter_uid'] = contact['uid']
                    try:
                        from career_tracking import Tracker
                        Tracker(self.root / 'data/tracking').register({**job, 'recruiter_id': contact['uid']})
                    except Exception:
                        pass
                    receipt = self._wait_receipt(job, text, time.time())
                else:
                    receipt = {'verified_sent': False, 'status': 'unknown',
                               'reason': '请求已发起，但未能从历史接口核验结果；请查看聊天，不自动重试'}
            else:
                target = ensure_conversation(job, who['uid'])
                if not target:
                    raise UIBlocked('未能在聊天页打开该会话，未发送')
                outcome = send_on(target, job, who['uid'], text)
                if not outcome.get('sent'):
                    raise UIBlocked(outcome.get('reason') or '页面SDK未发送')
                result['clicked_send'] = True
                result['stage'] = 'send-click'
                self._save(folder, result, 'result')
                receipt = self._wait_receipt(job, text, time.time())
            # send() reads this shape: top-level verified_sent plus receipt.message_id.
            result['receipt'] = receipt.get('receipt')
            result['clicked_send'] = bool(receipt.get('verified_sent'))
            result['verified_sent'] = receipt.get('verified_sent') is True
            if result['verified_sent']:
                result['status'] = 'sent'
            elif receipt.get('verified_sent') is False and receipt.get('reason'):
                result['status'] = 'unknown' if '未能从历史接口核验' in str(receipt.get('reason')) else 'blocked'
                result['reason'] = receipt['reason']
            else:
                result['status'] = 'unknown'
        except Exception as exc:
            result['reason'] = str(exc)[:250] if isinstance(exc, UIBlocked) else type(exc).__name__
            # Clicking 立即沟通 already has an external effect (platform default
            # greeting). Any failure after that click must stay unknown so a
            # retry cannot trigger a second default greeting.
            result['status'] = 'unknown' if result['clicked_send'] or result.get('first_contact_attempted') else 'blocked'
            self._save(folder, result, 'blocked' if result['status'] != 'unknown' else 'unknown')
        self._save(folder, result, 'result')
        return result

    def _wait_receipt(self, job, text, since, timeout=15):
        """Poll the history API after a page-SDK send; never retry the send itself."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            contact = contact_of(job)
            if contact:
                try:
                    data = boss_web.request(HISTORY, 'GET',
                                            {'bossId': contact['encryptBossId'], 'securityId': contact['securityId'],
                                             'maxMsgId': '0', 'c': '20', 'page': '1', 'src': '0'},
                                            target_path=CHAT_PATH)
                except Exception:
                    data = {}
                for message in data.get('messages') or []:
                    at = message.get('time', 0)
                    at = at / 1000 if at > 100000000000 else at
                    if at < since - 2:
                        continue
                    if (message.get('body') or {}).get('text') == text and str(((message.get('to') or {}).get('uid')) or '') == str(contact['uid']):
                        return {'verified_sent': True, 'status': 'sent',
                                'receipt': {'message_id': str(message.get('mid')), 'source': 'history_api_persistent_chrome', 'at': time.time()}}
            time.sleep(0.8)
        return {'verified_sent': False, 'status': 'unknown',
                'reason': '请求已发起，但未能从历史接口核验结果；请查看聊天，不自动重试'}

    def _contact(self, job):
        return contact_of(job)

    def recheck(self, job, text, since):
        """Read-only: decide whether an earlier unknown send actually landed."""
        if not _page_for(CHAT_PATH):
            raise UIBlocked('聊天页未打开，无法复核')
        contact = self._contact(job)
        if not contact:
            return {'verified_sent': False, 'reason': '联系人未出现在列表，需人工核验'}
        data = boss_web.request('/wapi/zpchat/geek/historyMsg', 'GET',
                                {'bossId': contact['encryptBossId'], 'securityId': contact['securityId'],
                                 'maxMsgId': '0', 'c': '20', 'page': '1', 'src': '0'}, target_path=CHAT_PATH)
        for message in data.get('messages') or []:
            at = message.get('time', 0)
            at = at / 1000 if at > 100000000000 else at
            if at < since - 2:
                continue
            if (message.get('body') or {}).get('text') == text and str(((message.get('to') or {}).get('uid')) or '') == str(contact['uid']):
                return {'verified_sent': True, 'status': 'sent',
                        'receipt': {'message_id': str(message.get('mid')), 'source': 'history_api_persistent_chrome', 'at': time.time()}}
        return {'verified_sent': False, 'reason': '历史消息中未找到该文本，未送达'}


def probe(job_id, root=WORKSPACE):
    from greeting_tools import Greetings
    job = next((j for j in Greetings(root).listing() if j.get('platform') == 'boss' and j.get('job_id') == job_id), None)
    if not job:
        raise UIBlocked('岗位未入库')
    return WebGreetAdapter(root, dry_run=True).run(job, '仅用于定位校验的占位内容，不会填写或发送给招聘者。')
