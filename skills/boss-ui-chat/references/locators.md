# 来源页定位与当前证据

入口必须为https://www.zhipin.com/job_detail/{job_id}.html，ID来自已保存岗位，不从公司名拼接。

已通过2026-10-29腾讯WorkBuddy来源页可访问性观察到：岗位heading、HR heading苏女士、企业腾讯，沟通入口link“立即沟通”点击后变为link“继续沟通”；迷你聊天窗heading“苏女士 腾讯·招聘HR”，输入区placeholder“请简短描述您的问题”，发送文本“发送”。脚本使用语义locator，严格唯一匹配。用户现已接受新会话先由平台发送默认招呼、再发定制正文；脚本将两个阶段分别记录。迷你聊天输入区和发送按钮尚未在无头模式完成端到端验收，不将这些定位描述为已稳定验证。

无头聊天页曾成功加载联系人列表；后续无头试验跳转/web/passport/zp/verify.html并提示账号异常访问code36，已停止。不得重复启动、伪造环境或自动解验证码。岗位来源页路径采用用户明确要求的入口，但仍可能被同样验证拦截。

正常发送过程使用fill及click，禁止页面evaluate写入DOM、调用Editor.sendText或聊天SDK。回执使用独立HTTP只读查询，查不到时不把页面本地回显当送达。依赖本地已有patchright与Chrome，不主动改动用户可见浏览器。
