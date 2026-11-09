/* 静态演示：拦截 /api/* 请求，返回从本机客户端快照的示例数据（已脱敏），
   让真实前端 UI 在 GitHub Pages 上以与客户端一致的方式展示。不连接任何后端。 */
(function () {
  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  var D = window.DEMO_DATA || { conversations: [], messages: {}, harness: { runs: [], tools: [], capabilities: {} }, discovery: { jobs: [], note: '' }, official: { jobs: [], per_company: {}, note: '' }, skills: { skills: [] } };
  var NOW = Date.now();

  function resp(obj, status) {
    status = status || 200;
    return new Promise(function (resolve) {
      setTimeout(function () {
        resolve({
          ok: status >= 200 && status < 300,
          status: status,
          json: function () { return Promise.resolve(obj); },
          text: function () { return Promise.resolve(JSON.stringify(obj)); },
          headers: { get: function () { return 'application/json'; } }
        });
      }, 40);
    });
  }

  var STATE = {
    messages: [],
    preferences: '目标城市：深圳 / 杭州\n岗位方向：AI 测试、测试开发、Agent 工程\n月薪下限：30K\n不接受：实习、日结、非技术岗',
    resume: '（演示环境不加载真实简历。完整版在本机运行，简历只保存在本地。）',
    jd: '', jobtitle: '', joburl: ''
  };

  var LIBRARY = {
    versions: [
      { id: 'demo-v1', name: '示例公司_AI应用工程师_定制简历.docx', kind: 'tailored', reviewed: true, text: '（演示环境已省略简历正文）',
        job: { title: '示例公司 · AI 应用工程师', jd: '岗位职责：负责 AI 应用及 Agent 的设计、开发与落地；参与 Prompt Engineering、RAG、Agent、工作流编排与工具调用。任职要求：Python、LLM 应用开发、主流大模型 API。', url: 'https://www.zhipin.com/' },
        tailoring_report: { changes: ['求职意向改为 AI 应用工程师，与目标岗位一致。', '摘要补充 Python/FastAPI、LangChain/LangGraph、MCP、RAG 评测等原文已有技术词，未新增数字或成果。'], gaps: ['JD 要求计算机/软件工程相关专业，原始简历为电气工程及其自动化，需本人确认是否补充佐证。'], paragraph_changes: [{ before: '◆求职意向：金融测试主管', after: '◆求职意向：AI 应用工程师' }] } },
      { id: 'demo-v2', name: '示例公司_大模型评测工程师_定制简历.docx', kind: 'tailored', reviewed: false, text: '（演示环境已省略简历正文）',
        job: { title: '示例公司 · 大模型评测工程师', jd: '负责大模型效果评测与数据闭环。', url: 'https://www.zhipin.com/' },
        tailoring_report: { changes: ['突出评测、RAG 效果评估与自动化闭环经历。'], gaps: ['主流 Benchmark 经验待确认。'], paragraph_changes: [] } },
      { id: 'demo-v0', name: '原始简历（Word 导入）', kind: 'original', reviewed: true, text: '（演示环境已省略简历正文）', job: {} }
    ],
    applications: [{ job: { title: '示例公司 · AI 应用工程师' }, resume_name: '示例公司_AI应用工程师_定制简历.docx', note: '已发送 · 等待 HR 回复' }]
  };

  function conversationsList() {
    return (D.conversations || []).map(function (c) {
      return { id: c.id, title: c.title, count: c.count, updated: c.updated, revision: c.revision || 1 };
    });
  }
  function conversation(id) {
    var c = (D.conversations || []).filter(function (x) { return x.id === id; })[0];
    if (!c) return null;
    return { id: c.id, title: c.title, revision: c.revision || 1, messages: (D.messages && D.messages[id]) || [] };
  }

  function mock(path, method) {
    var p = path.split('?')[0];
    if (p === '/api/state') {
      if (method === 'POST') return resp({ ok: true });
      return resp({ token: 'demo-token', state: STATE, engine: true });
    }
    if (p === '/api/conversations') {
      if (method === 'POST') {
        // create / save
        return resp({ id: 'demo-conv', title: '新会话', revision: 1, messages: [] });
      }
      return resp({ conversations: conversationsList() });
    }
    if (p.indexOf('/api/conversations/') === 0) {
      var cid = p.slice('/api/conversations/'.length);
      var c = conversation(cid) || conversation((D.conversations && D.conversations[0] && D.conversations[0].id) || '');
      return resp(c || { id: 'demo-conv', title: '演示会话', revision: 1, messages: [] });
    }
    if (p === '/api/harness') return resp(D.harness || { runs: [], tools: [], capabilities: {}, browser_connected: false });
    if (p.indexOf('/api/harness/artifact/') === 0) return resp({ error: '演示环境不提供文件下载' }, 404);
    if (p === '/api/library') return resp(LIBRARY);
    if (p === '/api/discovery') return resp(D.discovery || { jobs: [], note: '' });
    if (p === '/api/official-discovery') return resp(D.official || { jobs: [], per_company: {}, note: '' });
    if (p === '/api/skills') return resp(D.skills || { skills: [] });
    if (p.indexOf('/api/progress/') === 0) return resp({ message: '演示模式：正在处理…' });
    if (p.indexOf('/api/activity/') === 0) return resp({ events: [{ time: NOW / 1000, message: '演示模式：无真实执行记录' }], export: 'not_configured', status: 'completed' });
    if (p === '/api/chat') return resp({ answer: '这是静态演示环境，不会真正调用模型或发送任何消息。完整版在本机运行时才会执行真实 Agent 流程。', trace_id: null, workflow_id: null });
    if (p === '/api/boss-web') return resp({ ok: true, live: false, data: { note: '演示环境不连接 BOSS 浏览器', tools: [] } });
    if (p === '/api/official-web') return resp({ ok: true, live: false, data: { note: '演示环境不连接官网接口' } });
    if (p === '/api/job-resume' || p === '/api/resume-file') return resp({ error: '演示环境不提供文件' }, 404);
    if (p.indexOf('/api/resume-preview/') === 0) return resp({ error: '演示环境不提供预览' }, 404);
    if (p === '/api/job-status') return resp({ answer: '演示环境仅展示示例数据。', tool_results: [] });
    if (p === '/api/tracking') return resp({ jobs: [], note: '演示环境' });
    if (p === '/api/pipeline') return resp({ id: (D.harness && D.harness.runs && D.harness.runs[0] && D.harness.runs[0].id) || 'demo', progress: (D.harness && D.harness.runs && D.harness.runs[0] && D.harness.runs[0].pending) || '', status: 'monitoring' });
    return resp({});
  }

  window.fetch = function (input, init) {
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var method = ((init && init.method) || 'GET').toUpperCase();
      if (url.indexOf('/api/') === 0) return mock(url, method);
    } catch (e) {}
    return origFetch ? origFetch(input, init) : Promise.reject(new Error('fetch unavailable'));
  };
})();
