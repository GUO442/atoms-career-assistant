# 已核验的接口与限制

2026-10-29，仅腾讯AI智能体评测高级工程岗WorkBuddy、苏女士，单岗位验证：页面立即沟通按钮触发 POST `/wapi/zpgeek/friend/add.json`，参数位于query，名称为jobId、securityId，body为空。HTTP200且业务code=0，响应zpData有greeting、showGreeting、encBossId、securityId等字段。不得从字段存在推断支持自定义首句。

页面显示已发送“你好，可以聊聊么”，按钮变为继续沟通；后台GET `/wapi/zpchat/geek/historyMsg`读回相同文本及发送者/接收者。助手证据文件为data/boss-greeting-interface.json和data/greeting-validation-20261029.json。该测试未发送附件，也未证明独立HTTP发送可用。

已有会话自定义文本工具为助手boss_reply_tool.py的PageReplyAdapter：校验岗位ID与HR uid，在已登录Chrome消息页调用Editor.sendText → 页面聊天SDK，再通过历史消息接口回读核验。它不使用首次沟通POST，不具备附件能力。结果不确定时不自动重试。

前50个会话读取测试由独立HTTP完成，当前列表只返回36联系人、158条消息。只读成功不代表写入通道也可用。凭据同步为用户明确授权的一次操作，不因本Skill自动导出或刷新凭据。

## 常驻 Chrome 首触（2026-11-05 验收）

腾讯「智能体-全栈测试工程师（workbuddy方向）」周盼：`greeting-web-send` 在已登录的专用 Chrome（调试端口 18744）打开岗位页，核对标题与企业后点击立即沟通，平台先发默认招呼，随后在 `/web/geek/chat` 用页面 SDK 发送定制正文，`historyMsg` 读回 `mid=404400094400769`。该会话共 3 条消息（HR 卡片、默认招呼、定制正文），无重复。

页面行为：点击立即沟通后可能不跳转、仅创建联系人，也可能跳到聊天页；聊天页可能同时开多个标签，必须逐个按 `window.chat.communicating.encryptJobId + uid` 匹配后再发送。`enableSubmit` 在合成 input 事件后需要轮询约 1 至 3 秒才变 true，过早判断会误记失败并把文本留在输入框。
