# -*- coding: utf-8 -*-
"""Durable, redacted execution payloads and incremental OTLP/HTTP export."""
import base64, contextvars, functools, inspect, json, os, queue, re, sqlite3, threading, time, uuid
from contextlib import contextmanager
from pathlib import Path
from runtime_paths import WORKSPACE
from execution_control import managed_run, TaskCancelled
from urllib.request import Request, urlopen
from urllib.parse import urlparse

_current = contextvars.ContextVar('career_trace', default=None)
_parent = contextvars.ContextVar('career_span', default=None)

def settings():
    # Local config is deliberately separate from workspace state and HTTP responses.
    path = WORKSPACE/'data'/'langfuse.json'
    try: config = json.loads(path.read_text()) if path.exists() else {}
    except (ValueError, OSError): config = {}
    get = lambda key: os.environ.get('LANGFUSE_'+key, config.get(key.lower(), ''))
    host = get('BASE_URL') or get('HOST')
    return {'host':host.rstrip('/'), 'public':get('PUBLIC_KEY'), 'secret':get('SECRET_KEY'), 'project':get('PROJECT_ID')}

# Preserve business content while removing authentication fields and common secrets.
def capture(value):
    if isinstance(value, dict):
        return {str(k): '[REDACTED]' if re.search(r'password|passwd|secret|token|cookie|authorization|api[_-]?key|credential|security[_-]?id|^lid$', str(k), re.I) else capture(v) for k,v in value.items()}
    if isinstance(value, (list, tuple)):return [capture(v) for v in value]
    if value is None or isinstance(value,(bool,int,float)):return value
    text = str(value)
    # Structured content is recursively redacted even when passed as a JSON string.
    try:
        parsed=json.loads(text)
        if isinstance(parsed,(dict,list)):return json.dumps(capture(parsed),ensure_ascii=False)
    except (ValueError,TypeError):pass
    text=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+=*',r'\1[REDACTED]',text)
    text=re.sub(r'(?i)\b(?:sk|pk)-(?:lf-)?[A-Za-z0-9_-]{8,}', '[REDACTED]', text)
    text=re.sub(r'(?i)(["\']?(?:password|passwd|secret(?:_key)?|access_token|refresh_token|api[_-]?key|authorization|cookie)["\']?\s*[:=]\s*)("[^"\n]*"|\'[^\'\n]*\'|[^\s,;}{]+)', r'\1[REDACTED]', text)
    for env_key,secret in os.environ.items():
        if len(secret)>=8 and re.search(r'SECRET|TOKEN|PASSWORD|API_KEY',env_key,re.I):text=text.replace(secret,'[REDACTED]')
    for key in ('public','secret'):
        secret=settings().get(key)
        if secret:text=text.replace(secret,'[REDACTED]')
    return text

def record(**fields):
    ctx=_current.get();sid=_parent.get()
    if ctx and sid:
        store,key=ctx
        def update(r):
            for item in r['spans']:
                if item['id']==sid:item.update(capture(fields));break
        store.update(key,update);store.schedule(key)

class TraceStore:
    def __init__(self, path):
        self.path=Path(path); self.path.parent.mkdir(parents=True, exist_ok=True); self.lock=threading.RLock(); self.export_lock=threading.Lock(); self.outbox=queue.Queue(); self.scheduled=set(); self.exporter=None
        with self.db() as c:
            c.execute('CREATE TABLE IF NOT EXISTS traces (id TEXT PRIMARY KEY, body TEXT NOT NULL)')
            for key, raw in c.execute('SELECT id,body FROM traces').fetchall():
                r=json.loads(raw)
                if r['status']=='running':
                    r['status']='interrupted';r['events'].append({'message':'服务已重启，运行中断','time':time.time()});self.put(r,c)
        self.path.chmod(0o600)
    def db(self):return sqlite3.connect(self.path,timeout=10)
    def put(self,r,c=None):
        if c is not None:c.execute('INSERT OR REPLACE INTO traces VALUES (?,?)',(r['id'],json.dumps(r,ensure_ascii=False)))
        else:
            with self.db() as db:self.put(r,db)
    def get(self,key):
        with self.db() as c:row=c.execute('SELECT body FROM traces WHERE id=?',(key,)).fetchone()
        if not row:raise ValueError('追踪记录尚未创建')
        return json.loads(row[0])
    def update(self,key,fn):
        with self.lock:
            r=self.get(key);fn(r);self.put(r)
    def create(self,name,key=None):
        key=key or uuid.uuid4().hex
        if not re.fullmatch(r'[a-f0-9]{32}',key):raise ValueError('无效追踪 ID')
        with self.lock:
            with self.db() as c:
                if c.execute('SELECT 1 FROM traces WHERE id=?',(key,)).fetchone():raise ValueError('追踪 ID 已存在')
                self.put({'id':key,'name':name,'status':'running','started':time.time(),'events':[],'spans':[], 'export':'not_configured'},c)
        return key
    def event(self,key,message):
        self.update(key,lambda r:r['events'].append({'message':message,'time':time.time()}))
    def public(self,key):
        r=self.get(key);cfg=settings();r['langfuse_url']=None
        if cfg['host'] and cfg['project'] and r['export']=='sent':
            r['langfuse_url']=cfg['host']+'/project/'+cfg['project']+'/traces/'+key
        return r
    def schedule(self,key):
        if not all(settings()[k] for k in ('host','public','secret')):return
        with self.lock:
            if key not in self.scheduled:
                self.scheduled.add(key);self.outbox.put(key)
            self.update(key,lambda r:r.update(export='pending'))
            if self.exporter is None:
                self.exporter=threading.Thread(target=self._deliver,daemon=True);self.exporter.start()
    def _deliver(self):
        while True:
            key=self.outbox.get()
            try:
                with self.lock:self.scheduled.discard(key)
                self.export(key)
            finally:self.outbox.task_done()
    def flush(self):
        self.outbox.join()
    def export(self,key):
        # Serialize snapshots so an older snapshot cannot overwrite a newer one.
        with self.export_lock:self._export(key)
    def _export(self,key):
        cfg=settings()
        if not all(cfg[k] for k in ('host','public','secret')):return
        parsed=urlparse(cfg['host'])
        if parsed.scheme not in ('http','https') or not parsed.netloc or parsed.username or parsed.password:
            self.update(key,lambda r:r.update(export='failed'));return
        r=self.get(key);spans=[]
        delivered=set(r.get('delivered_spans',[]))
        pending=[s for s in r['spans'] if s.get('end') and s['id'] not in delivered]
        if not pending:
            self.update(key,lambda r:r.update(export='pending' if key in self.scheduled else 'sent'))
            return
        for s in pending:
            attrs={'langfuse.observation.type':s['kind'],'langfuse.trace.name':r['name'],'langfuse.session.id':key,
                   'langfuse.observation.metadata.trace_id':key, 'langfuse.observation.metadata.status':s['status']}
            for field,attribute in (('input','input'),('output','output'),('error','status_message'),('model','model.name'),('usage','usage_details')):
                if field in s:attrs['langfuse.observation.'+attribute]=json.dumps(s[field],ensure_ascii=False) if field in ('input','output','usage') else str(s[field])
            if s['status']=='error':attrs['langfuse.observation.level']='ERROR'
            span={'traceId':key,'spanId':s['id'],'name':s['name'],'kind':1,'startTimeUnixNano':str(s['start']),
                  'endTimeUnixNano':str(s.get('end') or time.time_ns()),'attributes':[{'key':k,'value':{'stringValue':v}} for k,v in attrs.items()],
                  'status':{'code':2 if s['status']=='error' else (0 if s['status']=='running' else 1)}}
            if s['parent']:span['parentSpanId']=s['parent']
            spans.append(span)
        payload={'resourceSpans':[{'resource':{'attributes':[{'key':'service.name','value':{'stringValue':'career-assistant'}}]},'scopeSpans':[{'scope':{'name':'career-assistant'},'spans':spans}]}]}
        auth=base64.b64encode((cfg['public']+':'+cfg['secret']).encode()).decode()
        request=Request(cfg['host']+'/api/public/otel/v1/traces',data=json.dumps(payload).encode(),headers={'Content-Type':'application/json','Authorization':'Basic '+auth,'x-langfuse-ingestion-version':'4'})
        try:
            with urlopen(request,timeout=8) as response:result=json.loads(response.read() or b'{}')
            if int(result.get('partialSuccess',{}).get('rejectedSpans',0)):raise ValueError('partial rejection')
            self.update(key,lambda r:r.update(export='pending' if key in self.scheduled else 'sent',export_error=None,delivered_spans=list(set(r.get('delivered_spans',[]))|{s['id'] for s in pending})))
        except Exception as exc:self.update(key,lambda r:r.update(export='failed',export_error=capture(type(exc).__name__+': '+str(exc))))
    @contextmanager
    def trace(self,name,key=None):
        key=self.create(name,key);token=_current.set((self,key));parent=_parent.set(None)
        try:
            with span(name,'agent'):yield key
            self.update(key,lambda r:r.update(status='completed',ended=time.time()))
        except BaseException as exc:
            self.update(key,lambda r:r.update(status='cancelled' if isinstance(exc,TaskCancelled) else 'failed',ended=time.time()));raise
        finally:
            _current.reset(token);_parent.reset(parent)
            self.schedule(key)

@contextmanager
def span(name,kind='tool',input=None):
    ctx=_current.get()
    if ctx is None:yield None;return
    store,key=ctx;s={'id':uuid.uuid4().hex[:16],'parent':_parent.get(),'name':name,'kind':kind,'start':time.time_ns(),'status':'running'}
    if input is not None:s['input']=capture(input)
    token=_parent.set(s['id'])
    started={'id':uuid.uuid4().hex[:16],'parent':s['id'],'name':'开始：'+name,'kind':'span','start':s['start'],'end':s['start'],'status':'ok'}
    if input is not None:started['input']=capture(input)
    store.update(key,lambda r:r['spans'].extend([dict(s),started]));store.event(key,'开始：'+name);store.schedule(key)
    try:yield s
    except BaseException as exc:
        s['status']='cancelled' if isinstance(exc,TaskCancelled) else 'error';s['error']=capture(type(exc).__name__+': '+str(exc));raise
    finally:
        _parent.reset(token);s['end']=time.time_ns()
        if s['status']=='running':s['status']='ok'
        def finish(r):
            for i,item in enumerate(r['spans']):
                if item['id']==s['id']:
                    # record() may have added input/output during the operation.
                    r['spans'][i]={**item,**capture(s)};break
        store.update(key,finish);store.event(key,('失败：' if s['status']=='error' else '完成：')+name);store.schedule(key)

def event(message):
    if _current.get():_current.get()[0].event(_current.get()[1],capture(message))
def traced(name,kind='tool'):
    def decorate(fn):
        @functools.wraps(fn)
        def wrapped(*a,**kw):
            arguments=inspect.signature(fn).bind(*a,**kw);arguments.apply_defaults()
            with span(name,kind,input=arguments.arguments) as observation:
                result=fn(*a,**kw)
                if observation is not None:
                    observation['output']=capture(result)
                    if isinstance(result,dict) and result.get('ok') is False:
                        observation['status']='error';observation['error']=capture(result.get('error','Tool returned ok=false'))
                return result
        return wrapped
    return decorate

def model_process(args,**kwargs):
    import subprocess
    command=list(args)
    if 'exec' in command and '--json' not in command:command.insert(command.index('exec')+1,'--json')
    with span('Codex 模型生成','generation',input=kwargs.get('input')) as observation:
        if observation is not None:
            for i,arg in enumerate(command[:-1]):
                if arg in ('-m','--model'):observation['model']=command[i+1]
        event('模型处理中，等待生成结果…')
        result=managed_run(command,**kwargs)
        messages=[];usage={};errors=[];json_mode='--json' in command
        if json_mode:
            for line in result.stdout.splitlines():
                try:payload=json.loads(line)
                except ValueError:continue
                if not isinstance(payload,dict):continue
                item=payload.get('item') or {}
                if payload.get('type')=='item.completed' and item.get('type')=='agent_message':messages.append(item.get('text',''))
                if payload.get('type')=='turn.completed':
                    for k,v in (payload.get('usage') or {}).items():
                        if isinstance(v,int) and not isinstance(v,bool) and v>=0:usage[k]=usage.get(k,0)+v
                if payload.get('type') in ('error','turn.failed'):errors.append(payload.get('error') or payload.get('message') or 'Codex execution failed')
                if observation is not None and payload.get('model'):observation['model']=capture(payload['model'])
                if observation is not None and payload.get('type')=='item.completed' and item.get('type') in ('command_execution','mcp_tool_call','web_search'):
                    with span('Codex '+item['type'],'tool',input=item.get('arguments',item.get('command',item.get('query')))) as tool:
                        if tool is not None:
                            tool['output']=capture(item.get('result',item.get('aggregated_output')))
                            if item.get('status')=='failed' or item.get('exit_code') not in (None,0):tool.update(status='error',error=capture(item.get('error','Codex tool failed')))
            result.stdout='\n'.join(messages)
        if observation is not None:
            observation['output']=capture(result.stdout)
            if usage:
                cached=usage.get('cached_input_tokens',0);total_input=usage.get('input_tokens',0)
                observation['usage']={'input':max(0,total_input-cached),'input_cache_read':cached,'output':usage.get('output_tokens',0)}
            if result.returncode or errors:observation['error']=capture({'events':errors,'stderr':result.stderr,'returncode':result.returncode})
        if result.returncode or errors or not result.stdout.strip():
            raise RuntimeError(capture(json.dumps({'message':'model_failed','errors':errors,'stderr':result.stderr,'returncode':result.returncode},ensure_ascii=False)))
        return result

STORE=TraceStore(WORKSPACE/'data'/'activity.sqlite3')
