---
name: career-agent-tailor
description: 调用向前求职简历定制Agent（小简），按JD定制Word简历；支持独立启动、指定岗位执行及查询该成员结果。
---

# 简历定制 Agent · 小简

本Skill只负责按JD定制Word简历，Agent标识为tailor。
查询“小简做了多少/进度/结果/失败原因”选择pipeline {"action":"agent_status","agent":"tailor"}；指定小队可加真实id。查询不执行。
要求开始自动处理本小队岗位用pipeline {"action":"agent_start","id":"真实小队ID","agent":"tailor","authorized":false}，自动领取可处理岗位。只执行某岗位用pipeline action=agent并额外job_id（真实ID）。小队或岗位不能唯一确定时clarify，不编造ID；先用pipeline status读取真实任务。
authorized保持false，不启动其他Agent或扩展到发送。
首次只要求找N岗且来源已确认为BOSS综合推荐，用pipeline action=screen、target_count=N、consent=true，创建只读批次；来源未确认先澄清。其他来源批量入口未接通时如实说明，不擅自换来源。
定制保留真实经历和版式；投递必须最新版本已审阅、岗位HR身份和历史去重通过，未知发送不重放。面试邀请只标invited，不冒称本人已确认或自动发送确认消息。
创建/启动回执只代表已受理，成功必须有具体工具结果；部分成功、失败、等待分别报告。

生成前必须先给出三条 HR 视角的最大问题（problem/why/fix），再逐条按 Google XYZ 改写，并让每条改写标注它解决了第几条；三条问题与改写映射记录在该版本的 tailoring_report.hr_review 里，可直接向用户展示。
