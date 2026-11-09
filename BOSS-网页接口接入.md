# BOSS 网页岗位工具

当前链路：助手对话 / 任务运行台 / boss-web-tools Skill → boss_web.py → 专用Chrome页面同源fetch → BOSS页面实抓搜索、详情接口。

不使用MCP；旧适配器与服务端入口已移除。历史MCP账户数据与旧安装产物没有删除，不参与当前运行。

首次在“专家·技能·连接器”或网页后台打开BOSS登录窗口，在专用Chrome完成登录后检查连接。会话保存在本机 data/boss-browser，不导出Cookie。此专用目录也符合Chrome对远程调试使用独立用户目录的要求：[Chrome官方说明](https://developer.chrome.com/blog/remote-debugging-port)。

工具命令（在本目录运行）：

```sh
python3 -m pip install -r requirements.txt
python3 skills/boss-web-tools/scripts/boss_tool.py open-login
python3 skills/boss-web-tools/scripts/boss_tool.py status
python3 skills/boss-web-tools/scripts/boss_tool.py search --json '{"query":"AI测试","city":"深圳"}'
```

详情调用 detail 时原样传回搜索结果中的 job_id、security_id、lid。搜索POST /wapi/zpgeek/search/joblist.json，详情GET /wapi/zpgeek/job/detail.json。详情返回的岗位ID必须匹配。响应HTTP200且业务code=0才可解析，结构异常不能冒充空列表。

本机POST /api/boss-web 接受tool与arguments，需X-App-Token。注册工具为catalog、open-login、status、search、detail。聊天@boss-web-tools或@boss-web-api后说明城市和关键词，由服务端调度搜索并按需读取最多5个JD；岗位结果保存在discovery.json。工具原始结果同时通过/api/chat的tool_results返回。工具错误、账号验证和限流立即停止，不自动重试。

截至实现验证：51项测试通过，覆盖真实响应字段映射、POST/GET参数、岗位身份校验、错误停止、聊天搜索后读取JD、无简历查询。macOS客户端构建成功。真实账号联调停在登录检查，尚不能声明实时岗位查询验收通过；登录后应验证搜索和详情两步。旧安装包未重新发布。

## 岗位定制招呼 Skill 与工具

2026-10-29新增boss-jd-greeting技能，安装在个人技能目录，并复制到本助手skills目录。规则为逐岗结合完整JD与真实原始简历，优先展示核心匹配经历，不发泛泛问候，不虚构基准经验和成果。greeting_tools.py提供greeting-context、greeting-plan、greeting-send、greeting-status，已接入boss_tools目录及本机/api/boss-web。计划保存至data/greetings/plans.sqlite3，含JD与原稿快照、证据引用、授权执行记录及回执，执行需要明确岗位数量，默认不追加已联系HR。

首次沟通接口已在腾讯WorkBuddy单岗页面实测：POST /wapi/zpgeek/friend/add.json，jobId和securityId位于query，body为空；平台默认招呼已由页面及后台历史消息双重核验。自定义首句和独立HTTP发送未验证，工具对未绑定联系人的首次定制招呼返回blocked_first_contact，不能降级为默认问候。已绑定会话的自定义文本使用现有PageReplyAdapter，仅在用户明确授权跟进时执行；没有消息ID回执时记为unknown并停止，后续不自动重试。工具不发送简历附件。

验证：技能两处均通过quick_validate；107项后端测试通过，其中8项覆盖招呼计划事实证据、授权、身份变更、首次通道阻塞、未知结果与跨计划去重；已验证实时技能发现和只读context API。本次封装未产生新的HR消息。

## 无头浏览器 UI 发送工具

boss-ui-chat技能已安装到个人技能目录并复制到助手skills。boss_ui_chat.py使用本机Chrome无头实例与已安装patchright同步API，从每个岗位的保存来源URL进入，按标题、HR与企业核验，点击继续沟通后用fill与click发送，不调用页面SDK或消息写接口。新会话按用户明确的新规则允许立即沟通产生平台默认问候，随后再发定制正文，两个阶段分别留痕。首次会话仍须已有可核验HR姓名；新会话通过独立联系人查询补齐uid后才发定制文本。查询与发送分离，只有历史读回近期正文、接收者和消息ID一致才记录成功。

工具为greeting-ui-probe、greeting-ui-send、greeting-ui-resume，复用greeting-plan与greeting-status，已注册到本机API与CLI。每次保存截图及result.json到data/ui-chat独立目录；已有草稿、重复消息、身份或定位不唯一时停止。code36安全验证写入暂停标记，后续不启动浏览器，需用户人工完成验证并明确解除。可选运行依赖见requirements-ui.txt。

验收状态：无头只读试验首次成功读取联系人列表，后续被BOSS要求安全验证code36，已停止线上尝试，未新增发送真实HR消息。7项UI专项测试通过（包含4项真实无头浏览器本地fixture测试，所有请求被本地拦截）；常规114项回归通过，其中4项可选浏览器测试在系统Python中跳过，已通过上述专项环境单独验证。真实岗位无头发送及迷你聊天定位仍待平台验证后验收，不将模拟页面成功当成真实发送成功。
