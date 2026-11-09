# 接口核验记录

2026-10-23：已通过Chrome Network导出HAR并核验搜索和JD响应，HTTP200且业务code=0。原始HAR仅保存在本机work目录。其他路径仍来自第三方源码，不代表实抓。抓包页后来异常重复加载，已关闭以停止额外请求。未发送消息或简历。

|用途|方法和路径|关键参数|状态|
|---|---|---|---|
|条件搜索|POST /wapi/zpgeek/search/joblist.json|form-urlencoded：query、city、page、pageSize、salary、experience、degree等|实抓成功，HTTP200且code=0；独立实时调用未验证|
|JD详情|GET /wapi/zpgeek/job/detail.json|securityId、lid、时间戳|实抓成功，HTTP200且code=0；不能只传岗位ID|
|岗位卡片|GET /wapi/zpgeek/job/card.json|securityId、lid|源码候选；现有MCP详情可能使用此请求|
|立即沟通|POST /wapi/zpgeek/friend/add.json|securityId、jobId等|仅建立沟通，不是发送简历附件|
|投递历史|GET /wapi/zprelation/resume/geekDeliverList|待实抓确认|未绑定调用|
|附件发送|尚未识别|需观察实际发送流程，可能包含聊天协议|不具备发送工具|

签名、Cookie和动态令牌由专用Chrome浏览器管理，不在技能中硬编码或输出。路径和参数可能随平台变化。本记录不构成官方API文档。

2026-10-27：运行实现已迁移为 boss_web.py 的页面同源 fetch；不依赖 MCP。POST 搜索保留 securityId 与 lid，GET 详情校验岗位身份。需要专用 Chrome 会话，账号实时可用性以实际联调为准。

2026-10-27 推荐工具：GET /wapi/zpgeek/recommend/conditions.json 读取expectList；GET /wapi/zpgeek/recommend/job/list.json 的sortType=1为精选、2为最新。参数含expectId、pk、page与空筛选字段。页面正常加载实抓两组各15条，HTTP200且code=0；封装工具支持expectations/recommend及后续detail。证据在助手data/boss-job-tabs-capture.json。
