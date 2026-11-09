---
name: official-careers
description: 通过各大互联网公司官网公开招聘接口实时搜索社招岗位、读取完整 JD，并返回可核验来源链接。用于岗位查询与匹配；不依赖浏览器登录，接口直接 HTTP 请求，仅收录经 curl 实测可用的官网接口。
---

# 官方招聘岗位工具

运行本技能的 `scripts/official_careers_tool.py`。工具根目录由 `CAREER_HOME` 指定；随助手交付时自动发现。与 BOSS 不同，官网社招搜索接口是公开的，无需登录或 Cookie。

## 实时查询

```sh
python3 scripts/official_careers_tool.py catalog
python3 scripts/official_careers_tool.py search --json '{"query":"AI测试","page":1}'
python3 scripts/official_careers_tool.py search --json '{"query":"测试开发","city":"深圳","companies":"tencent,bytedance"}'
python3 scripts/official_careers_tool.py detail --json '{"job_id":"真实岗位ID","platform":"tencent"}'
```

- `catalog`：列出已注册、已实测可用的公司及官网搜索页；`live=false`。
- `search`：跨公司搜索社招岗位。参数 `query`（必填）、`city`（可选）、`companies`（可选，公司 key 逗号分隔，缺省=全部已注册公司）、`page`（1 以上整数）。返回 `data.items`（标准化岗位：job_id、platform、title、company、city、salary、experience、education、url、jd 片段），以及 `data.per_company` 记录每家公司是否成功与失败原因。某家公司失败不阻断其它公司，但必须如实呈现在 per_company，不能冒充零结果。
- `detail`：按 `job_id` + `platform` 读取完整 JD，返回 `data.description`。

以 `ok=true`、`live=true` 的实时返回为本轮证据。向用户展示岗位名称、企业、城市、薪资、经验、链接和采集时间；缺失字段标记未返回，不让模型补造。来源链接必须来自接口真实字段，不拼接伪造详情页。

失败返回明确错误码；接口结构变化（缺少岗位列表、未返回 JSON、非 200）即停止该次查询，不自动重试、不把异常当作空列表。公开接口无需登录，故不提供登录/账号工具。

## 助手内调用

聊天输入 `@official-careers` 或选择“官方招聘岗位工具”插件，再给出关键词（可选城市、公司），例如“搜腾讯和字节的 AI测试岗”。服务端校验模型生成的工具参数后执行查询，最多一次搜索、五个 JD。插件接口是本机 `POST /api/official-web`，请求 `{"tool":"search","arguments":{"query":"AI测试"}}`，需使用助手会话令牌；不要把令牌写入技能或消息。

## 接入说明

每个公司是 `official_careers.py` 里的一个声明式适配器（`ADAPTERS`），记录搜索/详情接口的 method、URL、参数、响应路径与字段映射。只允许把 curl 实测返回真实岗位数据的接口登记为 `verified`；需要登录、CSRF 或签名而无法公开直连的官网不得登记，只能说明限制。新增公司前先在项目根目录用 curl 验证接口，再登记适配器。
