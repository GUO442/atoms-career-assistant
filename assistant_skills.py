# -*- coding: utf-8 -*-
"""Discoverable assistant skills with bounded loading and existing-tool execution."""
import hashlib
from pathlib import Path
from chat_intents import IntentError
from chat_workflows import recent_messages
from observability import span,event

SKILLS={
 'boss-recommend-pipeline':{'title':'推荐岗位自动跟进','description':'启动最多100个BOSS推荐岗位的后台批次任务，分批分析，符合后先招呼再定制，HR回复且最新简历审阅后投递；查询、暂停、恢复与取消整批任务。','tools':{'pipeline','jobs.status','resume.tailor_status','resume.delivery_status','clarify','chat.respond'}},
 'boss-chat-opportunities':{'title':'聊天机会筛选','description':'同步BOSS聊天企业及岗位，去重已有岗位和简历，识别企业主动联系待回复、我方联系未投简历、投简历后HR回复，筛选真实匹配机会；不发送。','tools':{'chat.scan','chat.list','jobs.status','clarify','chat.respond'}},
 'boss-job-apply':{'title':'简历附件投递','description':'对明确岗位执行已审阅附件简历的上传、来源页进入聊天、精确选择、发送回读和状态同步；也支持只读计划及进度查询。编写Skill不等于发送授权。','tools':{'resume.deliver','resume.delivery_status','resume.delivery_plan','jobs.status','clarify','chat.respond'}},
 'boss-tailor-resume':{'title':'岗位定制简历','description':'按目标岗位或JD定制Word简历，保留原格式和完整项目，补齐项目介绍与角色，突出实际负责人职责及兼任开发；不发送。','tools':{'resume.tailor','resume.tailor_status','profile.read','jobs.status','harness','clarify','chat.respond'}},
 'job-search-screening':{'title':'岗位查询与筛选','description':'查询岗位清单、筛选和打招呼/回复/定制/审阅/投递/面试/Offer/待办状态，或在线找岗推进匹配；不处理独立简历文件清单。',
                        'tools':{'pipeline','jobs.list','jobs.status','boss.query','harness','clarify','chat.respond'}}
}
from career_agents import AGENTS
for _agent,_meta in AGENTS.items():
 SKILLS['career-agent-'+_agent]={'title':_meta['title'],'description':_meta['title']+'独立启动、指定岗位执行、查询该Agent工作量/进度/结果/失败；不自动扩展其他动作。','tools':{'pipeline','jobs.status','clarify','chat.respond'}}

class SkillRuntime:
 def __init__(self,root):self.root=Path(root)
 def catalog(self):
  return [{'id':key,'title':v['title'],'description':v['description']} for key,v in SKILLS.items() if (self.root/'skills'/key/'SKILL.md').is_file()]
 def resolve(self,plan,data,runs,router):
  if plan['tool']!='skill.run':return plan,[]
  key=plan['arguments']['id']
  if key not in SKILLS:raise IntentError('Skill未注册，本轮未执行工具')
  path=self.root/'skills'/key/'SKILL.md'
  event('正在加载 Skill · '+SKILLS[key]['title'])
  with span('skill.load · '+key,'tool',input={'id':key}) as obs:
   try:
    raw=path.read_bytes()
    if len(raw)>32000:raise IntentError('Skill内容超过加载上限')
    content=raw.decode('utf-8')
   except (OSError,UnicodeError) as exc:raise IntentError('Skill加载失败，本轮未执行工具') from exc
   metadata={'id':key,'sha256':hashlib.sha256(raw).hexdigest()}
   if obs is not None:obs['output']=metadata
  event('正在按 Skill 选择工具 · '+SKILLS[key]['title'])
  planning_data={**data,'messages':recent_messages(data['messages'],2500)}
  resolved=router.plan(planning_data,runs,loaded_skill={'id':key,'instructions':content})
  if resolved['tool'] not in SKILLS[key]['tools']:raise IntentError('Skill选择了职责范围外的工具，本轮未执行')
  return resolved,[metadata]
