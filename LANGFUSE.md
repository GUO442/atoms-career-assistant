# 向前助手执行进度与 Langfuse 追踪

对话等待期间显示动态加载点、实际执行阶段和计时；展开“执行记录”可查看服务端阶段、追踪 ID 及上报结果。历史消息保留追踪 ID。后台 Harness 的任务卡也可查看追踪。

当前覆盖 HTTP 请求、Codex 模型生成、MCP 调用和 Harness 工具步骤。父子 span 共享 trace ID。Codex CLI 目前以一次模型执行作为 generation 记录；没有伪造内部推理、子 Agent、模型名称、Token 用量和费用。普通聊天仍是文本模式，未新增浏览器执行能力。

## 配置

在项目的 `data/langfuse.json` 写入以下字段（密钥只填本机文件，不填前端或工作区 JSON），并设置文件权限为 600：

```json
{
  "base_url": "https://你的Langfuse地址",
  "public_key": "你的项目Public Key",
  "secret_key": "你的项目Secret Key",
  "project_id": "平台项目ID"
}
```

也可以使用环境变量 `LANGFUSE_BASE_URL`、`LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_PROJECT_ID`，优先于本地文件。环境变量须在启动服务器前设置；本地文件会在每次上报时读取。

使用官方 OTLP/HTTP JSON 端点 `/api/public/otel/v1/traces`，包含 v4 ingestion header。没有配置时只保存在 `data/activity.sqlite3`；配置后，展开原消息执行记录点击“重试上报”可补传已完成任务。

“Langfuse 已接收”表示端点接收成功，平台索引可能延迟。失败时保留本地记录并显示失败，可手动重试。配置 project_id 后，成功接收的记录提供平台链接。

当前追踪记录节点名称、父子关系、状态、耗时，以及 HTTP 请求与响应、完整模型 Prompt 与回复、MCP 工具参数与结果、Harness 工具输入与结果、执行错误。简历、JD 和对话正文会包含在模型输入中，保存在本机追踪数据库并发送至配置的 Langfuse。认证字段、常见密钥格式、Bearer 凭据、当前 Langfuse 密钥和敏感环境变量值在写入前脱敏；自由文本脱敏无法保证识别所有未知凭据格式。

每个节点开始时立即上报独立的零时长“开始”节点（包含已准备的输入），结束时上报包含最终输入输出、状态和耗时的业务节点。通过串行后台队列增量发送，每个成功发送的节点只发一次，避免重复统计；本地保留运行中业务节点。上报失败保留本地内容与脱敏错误，可重试。进程突然退出时未发送的记录需手动重试。

Codex 调用启用 `--json`，只将 agent_message 正文返回给业务，读取 turn.completed 的真实用量；input 为未缓存输入，input_cache_read 为缓存输入，output 为输出。未返回用量时不造数。模型名仅在 CLI 事件或显式 -m/--model 中提供时记录；费用和内部推理不伪造。Codex 工具完成事件可形成子节点，其采集时刻为 CLI 返回事件后，不代表工具精确起止时刻。当前链路仍使用 Codex CLI，没有引入 LangChain。

## 验证

运行 `python3 -m unittest discover -s tests -v`。测试包括并发隔离、中断恢复、父子链路、模型失败和 OTLP 接收／失败；模拟服务通过不等于已连接实际 Langfuse。接入实际平台后，执行一次对话并按同一 trace ID 核验平台记录。

## 本机部署结果

已于 2026-10-26 部署本地 Langfuse v4，网页地址 http://127.0.0.1:3000，项目 career-assistant。使用独立 Lima 虚拟机 lf（2 CPU、4 GiB 内存、18 GiB 虚拟磁盘），数据库位于虚拟机 Docker 持久卷。网页 3000 和媒体 9090 仅监听 Mac 的 127.0.0.1。

已验证：本地账号登录；合成追踪写入并从 Observations API 读回 3 个节点；运行中的求职助手成功上报并读回错误调用链。data/langfuse.json 已激活，无需重启求职助手。登录信息见 data/langfuse/admin-credentials.txt。

管理脚本：/Users/guohainan/Documents/Codex/2026-10-10/xian-zi/outputs/Langfuse管理.command，支持 start、stop、status。停止虚拟机后追踪上报会失败并保存在本地，可在重新启动后重试。未配置开机自动启动。勿删除虚拟机目录，否则其中的 Docker 数据卷也会丢失。

## 2026-10-26 完整内容追踪升级

已补齐模型 Prompt/回复、HTTP 与 MCP 输入输出、Harness 工具结果、脱敏错误、CLI JSON 真实用量；运行时增量发送开始节点与已完成节点。成功发送的 span ID 持久化，重试只补未成功发送的节点。历史追踪没有采集过的正文与用量不能补回。

验证：27 项单元测试通过，包括并发隔离、JSON 回复提取、缓存 Token 分类、失败事件、脱敏、运行中开始节点上报、最终节点与去重。真实 Codex 验收返回 LANGFUSE_TRACE_OK，trace ID `166298799fd84be0a0b69344ef921c67`，已从 Langfuse v2 Observations API（fields=core,io,usage,metadata）读回 Prompt、回复和 input=20829、output=9、input_cache_read=0。该验收先于去重策略修正，包含开发核验的重复版本；后续调用采用只发送一次的节点策略。

本地助手已重启并通过 /api/state 检查；真实 tools/list 调用成功，trace ID `ac3f4696db8c41bd9e75a67fea6c4411`，本地 HTTP 输入、工具输出均可读回且上报状态 sent。刷新助手页面以取得重启后的会话令牌。

最终平台核验：`ac3f4696db8c41bd9e75a67fea6c4411` 已从 Langfuse Observations API 读回 4 个节点、4 个唯一 ID，输入输出字段齐全，未出现重复节点。
