# -*- coding: utf-8 -*-
"""Skill-facing local tracking API; credentials never leave loopback."""
import json,os
from urllib.request import Request,urlopen
TOOLS=[{'name':'tracking-status','description':'查看逐岗跟进状态、监控状态和待办','parameters':{}},
 {'name':'tracking-start','description':'启动已配置范围的消息监控，不发起新的打招呼','parameters':{}},
 {'name':'tracking-stop','description':'停止消息监控','parameters':{}},
 {'name':'tracking-sync','description':'只读同步已跟进岗位的回复','parameters':{}},
 {'name':'tracking-generate','description':'根据真实JD生成岗位定制简历草稿','parameters':{'job_id':'string'}},
 {'name':'tracking-review','description':'用户明确审阅指定版本后加入附件发送队列，不代表已投递','parameters':{'job_id':'string','version_id':'string','confirmed':'boolean'}}]
def call(name,args=None):
 args={} if args is None else args
 if not isinstance(args,dict):raise ValueError('工具参数必须是对象')
 base='http://127.0.0.1:'+str(int(os.environ.get('CAREER_PORT','18743')))
 with urlopen(base+'/api/state',timeout=3) as r:token=json.load(r)['token']
 action=name.removeprefix('tracking-')
 if name not in {t['name'] for t in TOOLS}:raise ValueError('未知跟进工具')
 spec=next(t for t in TOOLS if t['name']==name)
 if set(args)!=set(spec['parameters']):raise ValueError('跟进工具参数无效')
 headers={'X-App-Token':token,'Content-Type':'application/json'}
 if action=='status':req=Request(base+'/api/tracking',headers=headers)
 else:req=Request(base+'/api/tracking',data=json.dumps({'action':action,**args}).encode(),headers=headers)
 with urlopen(req,timeout=60) as r:data=json.load(r)
 return {'ok':True,'data':data}
