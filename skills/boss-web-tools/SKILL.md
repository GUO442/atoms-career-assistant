---
name: boss-web-tools
description: 通过 BOSS 直聘页面实抓接口实时搜索岗位、获取精选/最新职位、读取完整 JD 并返回可核验来源。用于岗位查询、逐岗状态监控和受控自动跟进；不依赖 MCP，定制简历须逐岗审阅后才能发送。
---

# BOSS 网页岗位工具

运行本技能的 `scripts/boss_tool.py`。工具根目录由 `BOSS_ASSISTANT_HOME` 指定；随助手交付时自动发现。依赖助手根目录 `requirements.txt`，需要本机 Chrome。

## 实时查询

```sh
python3 scripts/boss_tool.py catalog
python3 scripts/boss_tool.py open-login
python3 scripts/boss_tool.py status
python3 scripts/boss_tool.py expectations
python3 scripts/boss_tool.py recommend --json '{"kind":"featured","page":1}'
python3 scripts/boss_tool.py recommend --json '{"kind":"latest","page":1}'
python3 scripts/boss_tool.py search --json '{"query":"AI测试","city":"深圳","page":1}'
python3 scripts/boss_tool.py detail --json '{"job_id":"搜索返回的job_id","security_id":"搜索返回的security_id","lid":"搜索返回的lid"}'
```

`open-login` 打开独立 Chrome 用户目录，由用户完成登录。后续工具通过该页面的同源 fetch 调用实抓接口，使用浏览器持有的会话，不导出 Cookie，不使用 MCP。`status` 会请求账号接口；是否能搜索仍以实际搜索响应为准。

`search` 与 `detail` 在请求岗位接口前先检查账号会话；未登录则停止。`search` 支持城市名或 BOSS URL 的9位城市码，返回 `data.items`，包含岗位、企业、城市、薪资、经验、学历、来源链接，以及详情所需的 `security_id` 和 `lid`。后一组值必须原样传递，不得从岗位ID推算。`detail` 校验响应岗位ID后返回 `data.description` 完整JD。

`expectations` 返回当前账号的求职期望（`data.items`），包括 `expect_id`、城市、职位方向和薪资。`recommend` 的 `kind=featured` 对应精选职位（sortType=1），`kind=latest` 对应最新职位（sortType=2）；可传 `expect_id` 和 `page`（1—10）。未传expect_id时默认第一条求职期望，返回 `default_expectation=true` 和实际 `expectation`，向用户明确说明所用期望，不声称已按其他条件筛选。无期望时停止并提示先在BOSS设置。

推荐工具调用实抓的 GET `/wapi/zpgeek/recommend/job/list.json`；求职期望来自 GET `/wapi/zpgeek/recommend/conditions.json`。岗位同样位于 `data.items`，可继续交给 `detail`。响应结构异常不当作零结果；登录失效只提醒用户手动重新登录，不自动打开登录页、填手机号或发送短信。

以 `ok=true`、`live=true` 的实时返回为本轮证据。向用户展示岗位名称、企业、薪资、要求、链接和采集时间；缺失字段标记未返回，不让模型补造。用户要求完整信息时继续读取候选详情；仅搜索岗位不要求先提供简历。

失败会返回明确错误码；登录失效、验证码、账号异常、限流时停止当前任务，由用户在浏览器处理后手动继续，不自动重复请求或绕过验证。

## 助手内调用

聊天输入 `@boss-web-tools` 或选择“BOSS 网页岗位工具”插件，再给出关键词与城市，或直接说“查看精选职位”“查看最新职位”。服务端校验模型生成的工具参数后执行查询，最多一次搜索或推荐查询、五个JD。插件接口是本机 `POST /api/boss-web`，请求为 `{"tool":"search","arguments":{"query":"AI测试","city":"深圳"}}`，需使用助手会话令牌；不要把令牌写入技能或消息。

## 离线证据与其他操作

- `inspect-har --json '{"file":"/absolute/capture.har"}'`：提取脱敏接口元数据，不回放请求。
- `captured-search` / `captured-detail`：读取本地历史HAR，始终 `live=false`，不得作为新搜索结果。
- `prepare-application`：仅在审阅并确认指定简历后创建本地待执行记录，不发送。
- `send-resume`：明确返回未接通，不执行远端写入。

协议及核验证据见 [references/interfaces.md](references/interfaces.md)。抓包成功、适配器测试通过与实际账号实时联调成功是不同证据，不混用。

## 消息跟进与简历审阅

```sh
python3 scripts/boss_tool.py tracking-status
python3 scripts/boss_tool.py tracking-start
python3 scripts/boss_tool.py tracking-sync
python3 scripts/boss_tool.py tracking-stop
python3 scripts/boss_tool.py tracking-generate --json '{"job_id":"实际跟进岗位ID"}'
```

这组命令连接正在运行的本地客户端服务。`tracking-start` 每10秒通过实抓的会话列表和历史消息接口同步已跟进岗位；必须保持BOSS消息页可用。身份以真实岗位ID和招聘者ID匹配，不按姓名猜测，不把未跟进的联系人纳入自动发送。登录失效时停止并提示用户手动登录。

分别保留 greet（打招呼）、reply（对方回复）、resume（附件投递）、interview（面试）和 outcome（结果），每次更新附证据和事件ID。普通文本回复不等于附件投递；超时或崩溃中的发送标记结果未知，禁止自动重发。

用户当前策略：普通问候可自动回复；薪资、到岗、面试等问题提醒用户；每个岗位先生成定制简历并审阅，再发送附件。不要从“启动监控”推断用户已经审阅任何版本。只有用户明确确认指定岗位、指定版本后，才调用 `tracking-review --json '{"job_id":"实际ID","version_id":"实际定制版本ID","confirmed":true}'`。加入队列不等于附件已发送。附件发送接口尚未实抓核验时，队列停在blocked_interface，必须如实说明。

文本回复工具使用已观察的页面Editor.sendText→聊天SDK链路，并从历史消息接口核验回显；联系人未加载、输入框有用户草稿、身份不匹配时不发送。历史消息多于当前读取窗口时明确标记范围，不声称已完整导入全部历史。

`capture-greeting --json '{"timeout_seconds":600}'` 为CLI被动监听：记录下一次用户真实打招呼的请求结构，脱敏保存，不发送或重放请求。发送工具的真实性以实际核验证据为准。

## 网页推荐职位

`recommend` 的 `kind=recommended` 对应 https://www.zhipin.com/web/geek/jobs?ka=header-jobs 的综合推荐，使用 pc/recommend/expect/list.json 返回的 mixExpect 城市与期望标识，请求 pc/recommend/job/list.json，每页15条。不传 expect_id。助手内通过 Discovery 共用SQLite去重与严格IT非实习筛选。聊天可说“筛选推荐职位”或提供该页面链接。

## 独立推荐职位筛选工具

```sh
python3 scripts/boss_tool.py recommend-jobs --json '{}'
```

工具名 `recommend-jobs`，无参数，调用正在运行的助手服务。HTTP：`POST /api/boss-web`，请求 `{"tool":"recommend-jobs","arguments":{}}`，使用助手会话令牌。返回 `ok/live/data`，data 包含 jobs、received_count、duplicate_count、filtered_count、eligible_count、expectation。jobs 仅包含新增且明确属于非实习 IT 技术方向的岗位；空列表结合计数解释为去重或被排除，不代表BOSS没有推荐。失败停止，不自动重试。不发送消息或投递。


## 固定排除条件

岗位明确已关闭、已下线、过期或停止招聘时，排除出候选；日结、日薪、按日或按天计薪（例如200元/天）也排除。搜索、推荐、完整JD及聊天机会共用后端硬规则，不能由模型或缓存匹配结论覆盖。保留来源、排除理由和历史记录供审计，不删除沟通或投递证据。数值状态码未经核验不得猜测；缺少关闭状态不能宣称已核验仍在招聘。业务描述中的日结算系统不等于日结工资。
