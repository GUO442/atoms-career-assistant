---
name: job-search-screening
description: 查询已有岗位、回顾岗位筛选结果，或按求职条件在线找岗并推进JD核验和匹配分析。适用于岗位清单、筛选数量、打招呼、HR回复、定制/审阅/投递简历、面试、Offer及待办状态查询，也用于找新机会及选岗后的分析；简历文件清单使用简历工具，不触发新搜索。
---

# 岗位查询与筛选

在向前求职助手内使用已注册工具。先区分用户在回顾已有结果，还是要求获取新岗位、执行匹配；不能因为提到“今天”就自动联网搜索。

## 选择路径

- 查询逐岗沟通、定制、审阅、发送、面试、结果或待办状态：使用 `jobs.status`，结合公司/岗位和多维条件查询本地记录。不要用 `tracking.status` 的全量文本让模型猜条件。
- 回顾、数量、已入库机会、当前筛选结果：调用 `jobs.list`。不以聊天里有没有岗位文本判断数据库是否有记录。
- 明确获取新岗位、推荐职位、在线读取JD或检查BOSS登录：调用 `boss.query`，由查询适配器校验具体参数并执行。搜索缺少城市或方向时先澄清；精选/最新推荐可使用已核验求职期望，不编造条件。
- 明确要求“找岗位→选岗→分析/简历草稿”等多步任务：调用 `harness`。已有JD用mode=jd；在线找岗用mode=boss。当前Harness每个任务只分析一个用户选定岗位，缺少输入时暂停；不能把任务已创建说成已完成，也不能承诺批量精筛已全部执行。
- 对象不清，或日期、多个动作无法用工具参数表达：调用 `clarify`。问一个会影响执行的必要问题。
- 仅解释筛选规则或工作流原理：用 `chat.respond`，不执行任务。

## 工具参数

`jobs.list`：

```json
{"date":"all|today|yesterday|YYYY-MM-DD","basis":"collected|screened","screening":"all|unassessed|recommend|caution|reject|excluded"}
```

- 不限定日期用all；“那昨天呢”沿用上文对象、口径与筛选条件，只替换日期。
- collected是首次入库时间；screened是查询已有筛选结论。不能互换。当前库没有筛选完成时间，限定某一天的screened查询应如实返回口径不支持并澄清。
- recommend为符合，caution为需核实，reject为不符合，excluded为规则排除，unassessed为待分析。“已有结论”不等于“通过筛选”。

`boss.query` 参数为 `{}`。内部查询工具包括 `search`（query、city）、`recommend`（kind、可选expect_id）、`detail`（已返回的job_id）、`status`。一次查询最多一次搜索/推荐、五份JD；只要清单无需强制读取详情。详情标识来自真实结果，由适配器管理，不推算或输出登录凭据。

`harness` 外层参数为 `{"action":"create|status|resume|cancel|select|update","arguments":{...}}`：

- create：mode与context；context仅goal/query/city/deliverable/jd/jobtitle/joburl，deliverable为analysis或resume。真实简历与偏好由服务端提供，不重写事实。
- status：`{}` 或id；resume/cancel：id；select：id和job_id；update：id和context。
- id只取当前对话的真实任务，job_id只取对应任务候选。多任务指代不清先澄清；恢复、取消、更新需明确请求。

## 筛选结果如何解释

1. 规则初筛用于排除明确的实习或非目标岗位。仅凭岗位名称无法确认方向的结果，不应被解释成完整JD核验后的不匹配；FDE、AI Coding、测试主管等边界名称需要完整JD复核。若已被适配器排除、现有工具无法读取该条详情，说明限制并请用户提供完整JD，不声称已完成复核。
2. 个人匹配需完整JD和真实简历证据，由Harness完成来源校验、要求对照、缺口分析与保存。未知条件标“需核实”，不能补造经历或声称已满足。
3. 分开报告总岗位数、待分析、已有结论及各结论数量。不把已读取JD、规则排除、生成简历当成已通过完整精筛。
4. 只有实际成功工具结果才能作为本轮执行证据。历史缓存须标为已有记录；真实新查询须有成功响应和来源。Skill被加载不等于工具已执行。

登录失效、验证码、限流或接口异常时停止当前查询并说明恢复方法，不自动绕过或循环重试。此Skill不发送招聘方消息、不投递附件。没有注册工具时说明缺少连接，不自行改用任意shell或HTTP请求。


## 岗位状态查询工具 jobs.status

```json
{"query":"","filters":{"greet":"sent","reply":"no_reply"},"date":"all","date_basis":"collected","include_history":false}
```

query可填写公司、岗位名或ID；空格分隔多个检索词时共同匹配，例如“腾讯 WorkBuddy”；不限定填空串。filters跨维度为AND，同维度数组为OR。未提及的条件不添加；“目前”使用date=all。下列维度来自真实库和岗位/简历关联，枚举以运行时job_status_options为准：

| 维度 | 含义和查询口径 |
|---|---|
| greet | 打招呼：未发送not_sent、处理中pending、已发送sent、失败failed、待核验unknown |
| reply | HR回复：未知unknown、尚未回复no_reply、已回复replied |
| customized | 是否已关联岗位定制简历：yes/no；不把只有原始简历视为已定制 |
| review | 本人审阅：none无定制版、pending至少一份待审阅、reviewed关联定制版均通过有效审阅 |
| review_status | 当前草稿流程：none无记录、pending_review待审阅、approved本人已批准、unknown未知；与全部版本审阅维度不同 |
| resume_kinds | 可分别筛选关联原始来源original、有待审阅版pending、有有效审阅版reviewed；同岗位可同时满足多种 |
| resume | 简历发送：not_sent未发、waiting待发、pending发送中、sent已发、failed失败、unknown待核验 |
| interview | 面试：unknown未知、none未约、invited收到邀请、scheduled已约、completed已面、cancelled取消 |
| outcome | 求职结果：unknown未知、open跟进中、rejected已拒绝、offer收到Offer、accepted已接受Offer、closed结束 |
| screening | 匹配/规则结论：unassessed待分析、recommend符合、caution需核实、reject不符合、excluded规则排除 |
| jd_status / match_status | 是否已保存完整JD/匹配分析：available或missing |
| action_kind / action_status | 待办类型reply_text、send_resume、tailor_resume、notify及其队列/执行/待审阅/阻塞/完成状态。两项组合须命中同一待办，不能拼接不同记录 |
| platform / category / job_id / city | 按平台、岗位类型、真实岗位ID或城市限定 |
| resume_acceptance | 目前只有unknown：库中没有“HR简历初筛通过”字段，不能编造passed/rejected |

例：已打招呼但没回复→greet=sent且reply=no_reply；已定制但还没发→customized=yes且resume=not_sent；已约面试→interview=scheduled（收到邀请invited不等于已约）；腾讯岗位全部状态→query=腾讯且filters={}。

“通过简历”不明确时先问是本人审阅通过，还是招聘方初筛通过。本人审阅依据review及文件指纹；HR初筛未建字段应明确未记录，不能用已发送、HR回复或面试邀请替代。

日期支持all/today/yesterday/明确日期，统一北京时间。date_basis=collected按首次入库；greet/reply/resume/interview/outcome按当前状态最近记录时间；customized按关联定制版创建时间；reviewed按有效审阅时间。缺少对应时间不使用updated_at或其他日期代替。查询某天全部历史事件不等于当前状态日期过滤；需要历史时include_history=true仅附最近20条脱敏记录，不声称覆盖无限历史。

输出应说明各岗位当前状态、相关简历版本、待办及统计数量。unknown不等于“没有做过”；初始默认状态也不代表远端实时核验。查状态不触发新的发送、定制、审阅或面试状态修改。

助手内语义工具名为 `jobs.status`；同一后端还提供受本机会话令牌保护的 `POST /api/job-status`，请求体使用上述参数。`GET /api/job-status/schema` 可读取当前支持的状态枚举。两者共用同一查询函数，不另建统计口径；令牌只用于请求头，不写入Skill或聊天。


## 固定排除条件

岗位明确已关闭、已下线、过期或停止招聘时，排除出候选；日结、日薪、按日或按天计薪（例如200元/天）也排除。搜索、推荐、完整JD及聊天机会共用后端硬规则，不能由模型或缓存匹配结论覆盖。保留来源、排除理由和历史记录供审计，不删除沟通或投递证据。数值状态码未经核验不得猜测；缺少关闭状态不能宣称已核验仍在招聘。业务描述中的日结算系统不等于日结工资。


## 岗位来源与本次执行口径

岗位来源分为：BOSS综合推荐、精选职位、最新职位、关键词搜索、聊天机会、用户指定岗位链接或录入JD、本地岗位库重筛。详情页是获取完整JD的依据，不作为另一份岗位清单重复计数。

- 综合推荐：recommend kind=recommended，读取账号综合求职期望；精选featured、最新latest按返回的实际expectation说明。
- 关键词搜索：search，必须有关键词和城市；不能悄悄把推荐改成搜索。
- 聊天机会：chat.scan，已同步记录查询chat.list；说明平台联系人范围，不能称为永久历史。
- 指定链接/JD：核验唯一岗位并读取真实正文；只有录入JD时说明user_import，不能声称实时网页采集。
- 本地重筛：查询已有岗位库，说明使用历史数据，不算本轮新增采集。

来源选择：本轮明确指定优先，其次沿用同一任务中已经确认的来源；二者都没有时先澄清来源，不自行推断。找100岗等数量要求不能丢失；现有boss.query只支持一轮一次列表查询，不能假装完成批量任务。没有已注册的对应来源只读批量工具时明确能力限制，不把只读找岗位改成带招呼/投递授权的完整流程。只要筛选不发送消息、不定制、不投递。

执行回执必须说明：来源、实际查询条件/求职期望、目标数量、实际获取/去重/规则排除/已分析数量、使用实时数据还是历史记录、任务ID（仅真实创建后）。失败说明具体接口和可用业务码，不能仅凭数字码猜测登录或风控原因。多个来源合并时保留各自来源、按平台+岗位ID去重，同一岗位的来源证据不覆盖。

## 来源澄清的固定边界
用户只说“帮我找100个岗位”且本对话未确认来源，必须选择clarify，只问：“这100个岗位从哪里获取：BOSS综合推荐、关键词搜索，还是聊天机会？”不能询问是否打招呼、定制或投递，不能把“只筛选”和“完整自动流程”作为本次来源问题的选项。先确认来源；只读找岗不需要发送授权。只有本轮明确要求发送或完整自动跟进，才讨论对应动作。

## 已接通的只读100岗入口
用户确认来源“BOSS综合推荐”后，沿用本对话数量，通过pipeline {"action":"screen","target_count":100,"consent":true}启动只读批次。只采集推荐、读取JD、按当前规则筛选，不需要发送授权，不执行招呼/定制/投递。此入口已注册，应优先于boss.query单页查询，不再声称缺少该来源批量工具。

## 小队与工作分离（优先于旧的创建说明）
只有用户明确说新建小队才创建小队。pipeline screen不再新建小队，而是向现有小队的采集与筛选Agent派发只读工作；可传真实id指定小队，未指定且有多个小队先澄清，没有小队先询问是否新建。同小队复用已有记录并补足数量，不冒称全部是本轮新获取。agent_start只启动成员工作，agent_status只查询。
