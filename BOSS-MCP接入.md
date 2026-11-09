> 历史记录：2026-10-27 已停用此方案。boss_mcp.py 与 /api/boss-mcp 已移除；当前接入见 [BOSS-网页接口接入.md](BOSS-网页接口接入.md)。

# BOSS MCP 接入

第三方项目：https://github.com/can4hou6joeng4/boss-agent-cli
已安装 PyPI 包：boss-agent-cli[mcp]==3.0.0，mcp==2.3.0。项目级虚拟环境 `.mcp-venv`；本地账户目录 `data/boss-mcp`。没有更改全局 Codex MCP 配置。

`boss_mcp.py` 是 stdio MCP 客户端适配器。`server.py` 的 POST /api/boss-mcp 在本地请求令牌校验后调用适配器。GUI 左侧“BOSS MCP”可检查工具、登录态、查询第一页。

已实测：MCP initialize、tools/list、boss_status。发现并只开放6项查询工具：boss_status、boss_search、boss_detail、boss_me、boss_recommend、boss_cities。请求其他工具由适配器拒绝。MCP服务实际依赖CLI执行平台请求，并非BOSS官方接口。

当前状态：AUTH_REQUIRED。Chrome网站登录与MCP登录分离。没有复制Chrome的Cookie，也没有读取浏览器凭据文件。岗位搜索与个人简历读取尚未完成实测。账户登录前不声称可以实际搜索或完成Harness全流程。

CLI检查示例（相对路径，需在本文件所在目录执行）：

```
.mcp-venv/bin/boss --version
.mcp-venv/bin/boss --data-dir data/boss-mcp --json status
```

后续登录需单独确认第三方工具的本地账号访问与登录态保存。不要默认执行Cookie提取或修改日常Chrome调试设置；不要把token复制到Skill、日志或聊天。独立登录完成后，应先核验一条真实搜索和岗位详情，再将通过验证的查询路径接入Harness工具。

仅完成相关入口及安装源码审阅，不代表完整安全审计。审阅源码commit：4716ee1d211533db70ac7cc1ab2322eb269b43a0；PyPI实际工具schema以运行tools/list为准，不能用仓库master覆盖已安装版本参数。
