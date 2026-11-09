---
name: boss-ui-chat
description: 从已保存的BOSS岗位来源网页进入对应HR聊天，以无头浏览器UI定位、填写并点击发送定制话术，独立查询历史消息核验回执。用于无头UI发送、岗位沟通自动化及批量调用；不使用页面SDK发送，不发送附件。
---

# BOSS 无头 UI 消息

发送路径：岗位来源URL → 核对岗位与HR → 继续沟通 → 输入定制文本 → 点击发送。独立历史接口只做回执查询，发送不调用页面SDK、隐藏接口或WebSocket。无头不代表不运行浏览器。

先读取 [实际定位与验收状态](references/locators.md)。页面元素会变化，不把“固定元素”当作永久保证；匹配不唯一或身份变化时停止，不用相似姓名兜底。

## 工具与调用

脚本`scripts/ui_chat_tool.py`定位向前助手，优先使用BOSS_ASSISTANT_HOME，也支持本机路径提示。运行环境为助手`.mcp-venv/bin/python`，使用已安装patchright同步API及本机Chrome。未安装依赖时先报告，禁止无提示安装浏览器或改变系统Chrome配置。

- `greeting-ui-probe --json '{"job_id":"已入库岗位ID"}'`：检查来源页、HR、输入框及发送按钮，不填写、不发送。
- 先用boss-jd-greeting的greeting-context及greeting-plan准备有JD和原稿证据的定制话术。
- `greeting-ui-send --json '{"plan_id":"计划ID","authorized":true,"max_jobs":1,"allow_existing":true}'`：仅在已有本轮目标与数量授权时执行。allow_existing=true要求用户明确向已联系HR补发这条定制文本；默认跳过已有会话，不把创建Skill当发送授权。
- `greeting-status --json '{"plan_id":"计划ID"}'`：查看计划与回执。
- `greeting-ui-resume --json '{"verification_completed":true}'`：仅用户明确表示已人工完成安全验证后调用，解除本地暂停；不自动解决验证码、登录或重发。

脚本支持--stdin，传递正文时使用JSON文件或stdin，避免shell拼接。

## 首次沟通与去重

用户已明确接受平台不可取消的默认问候：新岗位先点击“立即沟通”，平台自动发送默认招呼，随后填写并发送基于JD与真实经历的定制正文。已有会话直接点击“继续沟通”，不重复触发默认问候。分别记录default_greeting_triggered与定制消息sent，默认招呼不能冒充定制消息成功。

只接受平台、岗位ID、来源URL一致的记录，核对HR姓名与企业。首次沟通后通过独立只读联系人查询确认岗位与HR uid绑定，再发定制正文。缺少可靠HR信息、已有输入草稿或元素不唯一时停止。新岗位尚未保存HR姓名时先核对并补齐来源页HR信息，不猜测。

发送前保存pending，首次沟通点击也有外部效果，须在点击前保存执行意图。默认问候触发后若定制失败，记录阶段及unknown；继续执行时先核验已有会话与历史，不重复点击立即沟通。定制正文只有近期历史消息中的正确接收HR、相同正文及消息ID均匹配才算sent。

## 平台验证与证据

2026-10-29无头只读试验第一次加载了联系人列表，后续被BOSS转至安全验证code36。当前已保存本地暂停标记；不得自动循环启动或切换通道来绕过验证。等用户人工完成，再做单岗位验收。实现和离线测试不等于真实发送成功。

每次运行在助手data/ui-chat生成独立目录，保存来源页、聊天准备、发送回显或失败截图和result.json。目录与文件仅本机用户可读。登录态只读取此前明确授权同步的加密会话，不导出当前浏览器凭据，也不记录Cookie。报告实际成功/跳过/阻塞/未知数，并明确未发送附件。
