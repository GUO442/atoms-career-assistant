/* 静态演示：拦截 /api/* 请求并返回示例数据，让真实前端 UI 在 GitHub Pages 上可交互展示。
   仅用于 Demo，不连接任何后端、不发送任何真实数据。 */
(function () {
  var origFetch = window.fetch ? window.fetch.bind(window) : null;
  var NOW = Date.now();

  function resp(obj, status) {
    status = status || 200;
    // 用 setTimeout 延迟到宏任务，确保所有 <script> 都已执行（真实 fetch 也是异步的）
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
    jd: '',
    jobtitle: '',
    joburl: ''
  };

  var CONVERSATIONS = [{
    id: 'demo-conv',
    title: 'BOSS 推荐 100 岗 · 小队演示',
    count: 4,
    updated: NOW,
    revision: 1,
    messages: [
      { role: 'user', content: '帮我找深圳的 AI 测试岗位，先筛一轮，匹配通过的再打招呼、定制简历。' },
      { role: 'assistant', content: '已创建「BOSS 推荐 100 岗」小队任务，流程为：采集推荐 → 读取 JD → 匹配筛选 → 打招呼 → 定制简历 → 等待回复 → 你审阅 → 投递核验。\n\n- **已采集**：130 岗\n- **已分析**：101 岗\n- **符合**：68 岗\n- **已招呼**：38 岗\n- **待审阅**：2 个版本\n\n当前在“任务运行台”可看到各业务 Agent 的独立进度；匹配通过后才会进入招呼与定制。' },
      { role: 'user', content: '现在筛到哪了？' },
      { role: 'assistant', content: '本机岗位库共 204 个岗位，其中 96 个已有匹配结论：符合 68、不匹配 33、规则排除 29。\n\n| 公司 | 岗位 | 城市 | 薪资 | 结论 |\n| --- | --- | --- | --- | --- |\n| 腾讯 | agent harness 工程师 | 深圳 | 30-60K·15薪 | 符合 |\n| 高帆破浪 | AI 应用工程师 | 深圳 | 30-60K | 符合 |\n| 字节跳动 | 大模型评测工程师 | 北京 | 25-50K | 符合 |\n| 某电商 | 自动化测试 | 广州 | 8-12K | 不匹配 |\n\n你可以让我：① 只采集筛选更多岗位；② 查看待审阅简历；③ 对某个岗位单独复核。' }
    ]
  }];

  var HARNESS = {
    runs: [{
      id: 'a1b2c3d4e5f60718293a4b5c6d7e8f90',
      status: 'monitoring',
      goal: 'BOSS 推荐 100 岗筛选与回复后投递',
      mode: 'recommended_batch',
      cursor: 6,
      max_steps: 16,
      pending: '已采集 130/130 · 已分析 101 · 符合 68 · 已招呼 38 · 已定制 68 · 待审阅 39 · 等回复 0 · 投递记录 0 · 待处理 29',
      jobs: [
        { job_id: 'demo01', company: '腾讯', title: 'agent harness 工程师', city: '深圳', salary: '30-60K·15薪', experience: '5-10年', education: '本科', url: 'https://www.zhipin.com/' },
        { job_id: 'demo02', company: '高帆破浪科技', title: 'AI 应用工程师', city: '深圳', salary: '30-60K', experience: '经验不限', education: '本科', url: 'https://www.zhipin.com/' },
        { job_id: 'demo03', company: '字节跳动', title: '大模型评测工程师', city: '北京', salary: '25-50K', experience: '3-5年', education: '硕士', url: 'https://www.zhipin.com/' }
      ],
      results: {},
      events: [
        { time: NOW / 1000, kind: 'collect', message: '推荐第 1 页已入库，本批去重后 15 岗' },
        { time: NOW / 1000, kind: 'checkpoint', message: '匹配筛选 已完成并保存检查点' },
        { time: NOW / 1000, kind: 'agent_started', message: 'collect 已独立启动，自动领取可处理岗位' },
        { time: NOW / 1000, kind: 'agent_finished', message: 'match 本轮执行结束；结果已保存' }
      ],
      trace_id: null
    }],
    tools: [
      { name: 'pipeline.status', description: '读取小队进度、Agent 汇报与工作请求' },
      { name: 'pipeline.agent_start', description: '让某个业务 Agent 独立领取岗位' },
      { name: 'jobs.status', description: '查询岗位全生命周期状态，不联网' },
      { name: 'official.query', description: '搜索公司官网社招岗位并读取 JD' }
    ],
    capabilities: { boss_query_adapter: true, browser_automation: false, send_message: false, send_resume: false, max_tool_steps: 16, max_attempts: 24 },
    browser_connected: false
  };

  var LIBRARY = {
    versions: [
      {
        id: 'demo-v1', name: '高帆破浪科技_AI应用工程师_定制简历.docx', kind: 'tailored', reviewed: true,
        text: '（演示简历正文已省略）',
        job: { title: '高帆破浪科技 · AI 应用工程师', jd: '岗位职责：负责 AI 应用及 Agent 的设计、开发与落地；参与 Prompt Engineering、RAG、Agent、工作流编排与工具调用。任职要求：Python、LLM 应用开发、主流大模型 API。', url: 'https://www.zhipin.com/' },
        tailoring_report: {
          changes: ['求职意向改为 AI 应用工程师（高帆破浪科技），与目标岗位一致。', '摘要补充 Python/FastAPI、LangChain/LangGraph、MCP、RAG 评测等原文已有技术词，未新增数字或成果。'],
          gaps: ['JD 要求计算机/软件工程/人工智能相关专业，原始简历为电气工程及其自动化，需本人确认是否补充相关课程或项目佐证。', 'JD 提到向量数据库、Embedding 经验，原始简历无明确证据，未写入正文，待本人确认。'],
          paragraph_changes: [{ before: '◆求职意向：金融测试主管（XTransfer）', after: '◆求职意向：AI 应用工程师（高帆破浪科技）' }]
        }
      },
      {
        id: 'demo-v2', name: '腾讯_agent harness 工程师_定制简历.docx', kind: 'tailored', reviewed: false,
        text: '（演示简历正文已省略）',
        job: { title: '腾讯 · agent harness 工程师', jd: '负责 Agent Harness 执行框架、工具编排与检查点恢复。', url: 'https://www.zhipin.com/' },
        tailoring_report: { changes: ['突出 Agent 运行框架、工具调用与检查点恢复的项目经历。'], gaps: ['腾讯云经验未在原始简历体现，待确认。'], paragraph_changes: [] }
      },
      {
        id: 'demo-v0', name: '原始简历（Word 导入）', kind: 'original', reviewed: true,
        text: '（演示简历正文已省略）', job: {}
      }
    ],
    applications: [
      { job: { title: '高帆破浪科技 · AI 应用工程师' }, resume_name: '高帆破浪科技_AI应用工程师_定制简历.docx', note: '已发送 · 等待 HR 回复' }
    ]
  };

  var DISCOVERY = {
    jobs: [
      { job_id: 'demo01', company: '高帆破浪科技', title: 'AI 应用工程师', city: '深圳', salary: '30-60K', experience: '经验不限', education: '本科', url: 'https://www.zhipin.com/', match: 'AI 相关、非实习非日结，月薪下限 30K 满足预期；按本人规则直接匹配通过。', source: 'boss_web_api' },
      { job_id: 'demo02', company: '腾讯', title: 'agent harness 工程师', city: '深圳', salary: '30-60K·15薪', experience: '5-10年', education: '本科', url: 'https://www.zhipin.com/', match: 'AI 相关、非实习非日结，月薪下限 30K 满足预期。', source: 'boss_web_api' },
      { job_id: 'demo03', company: '某公司', title: '测试实习生', city: '深圳', salary: '150-200元/天', experience: '经验不限', education: '大专', url: 'https://www.zhipin.com/', match: '实习/日结岗位，规则排除。', source: 'boss_web_api' }
    ],
    note: '演示数据：本次返回 10 个岗位，去重后保留 8 个明确符合方向的岗位。'
  };

  var OFFICIAL = {
    jobs: [
      { company: '腾讯', title: '测试开发工程师', city: '深圳', salary: '20-40K', experience: '3-5年', education: '本科', url: 'https://careers.tencent.com/', jd: '负责测试平台与自动化测试框架建设。' },
      { company: '字节跳动', title: '大模型评测工程师', city: '北京', salary: '25-50K', experience: '3-5年', education: '本科', url: 'https://jobs.bytedance.com/', jd: '负责大模型效果评测与数据闭环。' },
      { company: '美团', title: '测试开发', city: '北京', salary: '20-35K', experience: '3-5年', education: '本科', url: 'https://zhaopin.meituan.com/', jd: '负责业务质量保障与自动化测试。' }
    ],
    per_company: { tencent: { ok: true, name: '腾讯', count: 3 }, bytedance: { ok: true, name: '字节跳动', count: 4 }, meituan: { ok: true, name: '美团', count: 2 } },
    note: '已完成查询 8 家公司，共返回 15 个岗位；仅保留明确符合方向的非实习岗位。'
  };

  var SKILLS = {
    skills: [
      { id: 'boss-web-tools', title: 'BOSS 网页工具', note: 'BOSS 页面同源接口：status / search / detail', content: '只读查询 BOSS 页面接口，遇到登录验证、风控或限流立即停止，不自动重试。' },
      { id: 'boss-jd-greeting', title: '逐岗定制招呼', note: '引用必须逐字来自该岗位 JD 或原始简历', content: '结合 JD 核心要求与真实简历经历生成 20-200 字招呼语，不能编造事实。' },
      { id: 'boss-tailor-resume', title: '简历定制', note: '按 JD 改写简历，保留原文事实', content: '只改写真实经历的表达，不新增单位、日期、学历或成果数字；不确定项列入待确认。' },
      { id: 'job-search-screening', title: '岗位查询与筛选', note: '按公司/岗位/城市以及组合状态查询', content: '查询本地岗位库，不联网；缺失状态按未知处理。' },
      { id: 'official-careers', title: '官网招聘', note: '公司官网社招岗位搜索与 JD 读取', content: '直连公开接口，无需登录；某公司失败会如实显示。' },
      { id: 'boss-job-apply', title: '简历投递', note: '仅发送本人已审阅的最新版本', content: '投递前核对审阅状态与版本指纹，已发或未知结果不重发。' }
    ]
  };

  function mock(path, method) {
    // 统一去掉查询串
    var p = path.split('?')[0];
    if (p === '/api/state') {
      if (method === 'POST') return resp({ ok: true });
      return resp({ token: 'demo-token', state: STATE, engine: true });
    }
    if (p === '/api/conversations') {
      if (method === 'POST') {
        return resp({ id: 'demo-conv', title: '新会话', revision: 1, messages: [] });
      }
      return resp({ conversations: CONVERSATIONS.map(function (c) { return { id: c.id, title: c.title, count: c.count, updated: c.updated }; }) });
    }
    if (p.indexOf('/api/conversations/') === 0) {
      var cid = p.slice('/api/conversations/'.length);
      var c = CONVERSATIONS.filter(function (x) { return x.id === cid; })[0] || CONVERSATIONS[0];
      return resp({ id: c.id, title: c.title, revision: c.revision || 1, messages: c.messages });
    }
    if (p === '/api/harness') return resp(HARNESS);
    if (p.indexOf('/api/harness/artifact/') === 0) return resp({ error: '演示环境不提供文件下载' }, 404);
    if (p === '/api/library') return resp(LIBRARY);
    if (p === '/api/discovery') {
      if (method === 'POST') return resp(DISCOVERY);
      return resp(DISCOVERY);
    }
    if (p === '/api/official-discovery') {
      if (method === 'POST') return resp(OFFICIAL);
      return resp(OFFICIAL);
    }
    if (p === '/api/skills') return resp(SKILLS);
    if (p.indexOf('/api/progress/') === 0) return resp({ message: '演示模式：正在处理…' });
    if (p.indexOf('/api/activity/') === 0) return resp({ events: [{ time: NOW / 1000, message: '演示模式：无真实执行记录' }], export: 'not_configured', status: 'completed' });
    if (p === '/api/chat') return resp({ answer: '这是静态演示环境，不会真正调用模型或发送任何消息。完整版在本机运行时才会执行真实 Agent 流程。', trace_id: null, workflow_id: null });
    if (p === '/api/boss-web') return resp({ ok: true, live: false, data: { note: '演示环境不连接 BOSS 浏览器', tools: [] } });
    if (p === '/api/official-web') return resp({ ok: true, live: false, data: { note: '演示环境不连接官网接口' } });
    if (p === '/api/job-resume' || p === '/api/resume-file') return resp({ error: '演示环境不提供文件' }, 404);
    if (p.indexOf('/api/resume-preview/') === 0) return resp({ error: '演示环境不提供预览' }, 404);
    if (p === '/api/job-status') return resp({ answer: '演示环境仅展示示例数据。', tool_results: [] });
    if (p === '/api/tracking') return resp({ jobs: [], note: '演示环境' });
    if (p === '/api/pipeline') return resp({ id: 'a1b2c3d4e5f60718293a4b5c6d7e8f90', progress: HARNESS.runs[0].pending, status: 'monitoring' });
    return resp({});
  }

  window.fetch = function (input, init) {
    try {
      var url = typeof input === 'string' ? input : (input && input.url) || '';
      var method = ((init && init.method) || 'GET').toUpperCase();
      if (url.indexOf('/api/') === 0) {
        return mock(url, method);
      }
    } catch (e) {}
    return origFetch ? origFetch(input, init) : Promise.reject(new Error('fetch unavailable'));
  };
})();
