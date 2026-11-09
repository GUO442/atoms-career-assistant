let token='', state={messages:[]},busy=false;
const $=id=>document.getElementById(id);
const fields=['resume','preferences','jd','jobtitle','joburl'];
function view(id){document.querySelectorAll('.view').forEach(e=>e.classList.toggle('hidden',e.id!==id));document.querySelectorAll('.nav').forEach(e=>e.classList.toggle('active',e.dataset.view===id));$('crumb').textContent={discover:'找岗位并定制',library:'简历与投递台账',bossweb:'BOSS 网页接口',harness:'任务运行台',skills:'BOSS 技能与工具',chat:'对话助手',profile:'真实经历档案',jobs:'岗位与 JD',official:'官网招聘'}[id]}
document.querySelectorAll('.nav').forEach(b=>b.onclick=()=>view(b.dataset.view));
function collect(){fields.forEach(k=>state[k]=$(k).value);return state}
async function api(path,data,requestId=null){const r=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json','X-App-Token':token,...(requestId?{'X-Request-ID':requestId}:{})},body:JSON.stringify(data)});const d=await r.json();if(!r.ok)throw Error(d.error||'请求失败');return d}
async function save(){await api('/api/state',collect());await saveConversation();$('status').textContent='已保存在此电脑'}
function add(m){let a=document.createElement('article');a.className=m.role==='user'?'user':'assistant';let b=document.createElement('b');b.textContent=m.role==='user'?'你':'✦ 向前';let p=m.role==='user'?document.createElement('p'):renderMessage(m.content);if(m.role==='user')p.textContent=m.content;a.append(b,p);if(m.workflow_id){const task=el('button','查看 Harness 任务');task.onclick=()=>{refreshHarness();openSheet('harness','Harness 任务')};a.append(task)}if(m.trace_id)attachTrace(a,m.trace_id);$('messages').append(a);$('messages').scrollTop=$('messages').scrollHeight}
async function send(text){
 if(busy||!text.trim())return;
 busy=true;$('send').disabled=true;collect();state.messages.push({role:'user',content:text});add(state.messages.at(-1));$('input').value='';
 const requestId=crypto.randomUUID().replaceAll('-','');
 const progress=el('div',undefined,'chat-live-status');progress.setAttribute('role','status');progress.setAttribute('aria-live','polite');
 const title=el('span');const detail=el('small');progress.append(detail);$('messages').append(progress);
 const started=Date.now();let phase='正在保存消息…';let polling=false,settled=false;
 const tick=()=>{detail.textContent=phase+' · '+Math.floor((Date.now()-started)/1000)+' 秒';$('status').textContent=detail.textContent};tick();
 const tracker={finish(){}};
 const timer=setInterval(async()=>{
  if(polling)return;polling=true;
  try{const r=await fetch('/api/progress/'+requestId,{headers:{'X-App-Token':token}});if(r.ok){const d=await r.json();if(!settled){phase=d.message;tick()}}}catch{}finally{polling=false}
 },500);

 try{
  await save();phase='资料已保存，已提交模型，等待回复';tick();
  const d=await api('/api/chat',{...state,conversation_id:activeConversation,consent:true},requestId);settled=true;clearInterval(timer);phase='已收到回复，正在保存结果';tick();
  const m={role:'assistant',content:d.answer,trace_id:d.trace_id,workflow_id:d.workflow_id};state.messages.push(m);add(m);await save();title.textContent='✓ 处理完成';detail.textContent='已保存回复 · 用时 '+Math.floor((Date.now()-started)/1000)+' 秒';$('status').textContent='回复已保存';
 }catch(e){settled=true;clearInterval(timer);title.textContent='处理未完成';detail.textContent=e.message;$('status').textContent=e.message;const failure={role:'assistant',content:'请求未完成：'+e.message,trace_id:requestId};state.messages.push(failure);try{await saveConversation()}catch{}}
 finally{clearInterval(timer);progress.classList.remove('is-running');tracker.finish();busy=false;$('send').disabled=false;refreshConversations().catch(()=>{})}
}
$('composer').onsubmit=e=>{e.preventDefault();send($('input').value)};
document.querySelectorAll('[data-prompt]').forEach(b=>b.onclick=()=>{$('input').value=b.dataset.prompt;$('input').focus()});
$('saveprofile').onclick=()=>save().catch(e=>$('status').textContent=e.message);
$('savejob').onclick=()=>save().then(()=>{view('chat');$('status').textContent='当前岗位已保存'}).catch(e=>$('status').textContent=e.message);
$('analyze').onclick=async()=>{try{await save();view('chat');$('input').value='请逐条分析当前岗位JD与我的真实经历的匹配度，说明证据、硬性缺口和申请建议。'}catch(e){$('status').textContent=e.message}};
$('file').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>400000){alert('请选择小于400KB的文本文件');return}$('resume').value=await f.text();await save()};
$('export').onclick=()=>{collect();const text=['# 求职档案','## 求职偏好',state.preferences||'','## 原始简历',state.resume||'','## 当前岗位',state.jobtitle||'',state.joburl||'',state.jd||'','## 对话与定制结果',...state.messages.map(m=>(m.role==='user'?'### 你':'### 向前')+'\n'+m.content)].join('\n\n');const url=URL.createObjectURL(new Blob([text],{type:'text/markdown;charset=utf-8'}));const a=document.createElement('a');a.href=url;a.download='求职档案与定制结果.md';a.click();setTimeout(()=>URL.revokeObjectURL(url),1000)};
fetch('/api/state').then(r=>r.json()).then(async d=>{token=d.token;state={messages:[],...d.state};fields.forEach(k=>$(k).value=state[k]||'');await initConversations();$('engine').textContent=d.engine?'● Codex 引擎可用 · 尚未实测对话':'○ 未找到 Codex 引擎'}).catch(()=>{$('engine').textContent='本地服务连接失败'});

$('useboss').onclick=()=>{view('chat');$('input').value='使用 boss-login Skill，先说明当前登录流程及所需浏览器工具。若当前环境没有浏览器连接，请明确说明，不要声称已经执行。';$('input').focus()};

const statusLabels={ready:'待执行',running:'执行中',waiting_browser:'等待浏览器连接',waiting_connection:'等待连接或登录处理',waiting_selection:'等待你选择岗位',waiting_input:'等待补充信息',budget_exceeded:'已达到执行预算',failed:'执行失败',interrupted:'运行中断',cancelled:'已取消',completed:'已完成'};
function el(tag,text,cls){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e}
function agentContext(){return {...collect(),goal:$('agent-goal').value.trim(),query:$('agent-query').value.trim(),city:$('agent-city').value.trim(),deliverable:$('agent-deliverable').value}}
async function hAction(action,id,extra={}){try{await api('/api/harness',{action,id,...extra});await refreshHarness();$('hstatus').textContent='任务状态已更新'}catch(e){$('hstatus').textContent=e.message}}
async function createRun(mode){if(!token)return;$('hstatus').textContent='正在创建任务…';await hAction('create',null,{mode,context:agentContext(),consent:$('hconsent').checked})}
$('runboss').onclick=()=>createRun('boss');$('runjd').onclick=()=>createRun('jd');
let refreshingHarness=false;
async function refreshHarness(){if(refreshingHarness)return;refreshingHarness=true;try{
 const r=await fetch('/api/harness');if(!r.ok)throw Error('运行台连接失败');const d=await r.json();
 $('agent-capabilities').textContent='模型决策 · 工具校验 · 检查点恢复 · '+(d.capabilities?.boss_query_adapter?'BOSS只读查询适配器已配置（登录另行核验）':'BOSS查询未连接');
 $('toolregistry').replaceChildren(...d.tools.map(t=>el('p',t.name+' · '+t.description)));
 $('runs').replaceChildren();if(!d.runs.length)$('runs').append(el('p','还没有任务。填写真实经历与求职目标后开始。'));
 for(const run of d.runs){
  const card=el('div',undefined,'card agent-run');card.append(el('div',statusLabels[run.status]||run.status,'engine'),el('h2',(run.goal||(run.mode==='boss'?'BOSS 全流程':'JD 匹配与简历定制'))+' · '+run.id.slice(0,8)),el('p','已保存 '+run.cursor+' 个工具检查点'+(run.runtime===2?' · 最多 '+run.max_steps+' 步':' · 旧版顺序工作流')));
  if(run.pending)card.append(el('p',run.pending,'agent-pending'));
  const actions=el('div',undefined,'actions');
  if(!['completed','cancelled','running','waiting_selection','budget_exceeded'].includes(run.status)){const b=el('button','从检查点继续');b.onclick=()=>hAction('resume',run.id,{consent:$('hconsent').checked});actions.append(b)}
  if(!['completed','cancelled','running'].includes(run.status)){const b=el('button','用当前表单更新输入');b.onclick=()=>hAction('update',run.id,{context:agentContext()});actions.append(b)}
  if(!['completed','cancelled'].includes(run.status)){const b=el('button','取消任务');b.onclick=()=>hAction('cancel',run.id);actions.append(b)}
  if(run.status==='completed'){const a=el('a','下载分析与简历草稿 ↓');a.href='/api/harness/artifact/'+run.id;actions.append(a)}
  card.append(actions);
  if(run.jobs?.length){const jobs=el('div',undefined,'agent-jobs');for(const job of run.jobs){const j=el('div',undefined,'resource-card');j.append(el('h3',job.company+' · '+job.title),el('p',[job.city,job.salary,job.experience,job.education].filter(Boolean).join(' · ')));const link=el('a','查看 BOSS 来源 ↗');link.href=job.url;link.target='_blank';link.rel='noopener';j.append(link);if(run.selected_job===job.job_id)j.append(el('small','已选择此岗位'));else if(run.status==='waiting_selection'){const b=el('button','选择并分析这个岗位');b.onclick=()=>hAction('select',run.id,{job_id:job.job_id,consent:$('hconsent').checked});j.append(b)}jobs.append(j)}card.append(jobs)}
  for(const name of ['resume.match','resume.tailor']){if(run.results?.[name]){const details=el('details');details.append(el('summary',name==='resume.match'?'查看匹配分析':'查看定制简历草稿'),renderMessage(run.results[name]));card.append(details)}}
  if(run.trace_id)attachTrace(card,run.trace_id);
  const details=el('details');details.append(el('summary','决策与执行记录'));const events=el('div',undefined,'eventlog');for(const e of run.events)events.append(el('p',new Date(e.time).toLocaleTimeString()+' · '+e.kind+' · '+e.message));details.append(events);card.append(details);$('runs').append(card);
 }
 }catch(e){$('hstatus').textContent=e.message}finally{refreshingHarness=false}}
refreshHarness();setInterval(()=>{if(!$('harness').classList.contains('hidden'))refreshHarness()},2500);view(location.pathname.startsWith('/admin')?'profile':'chat');

async function bossWebCall(tool,args={}){$('bossoutput').textContent='正在调用 '+tool+'…';try{const d=await api('/api/boss-web',{tool,arguments:args});$('bossoutput').textContent=JSON.stringify(d,null,2)}catch(e){$('bossoutput').textContent=e.message}}
$('bosslogin').onclick=()=>bossWebCall('open-login');$('bosstools').onclick=()=>bossWebCall('catalog');$('bossstatus').onclick=()=>bossWebCall('status');$('bosssearch').onclick=()=>{if(!$('bosscity').value.trim()){$('bossoutput').textContent='请先填写目标城市';return}bossWebCall('search',{query:$('bossquery').value,city:$('bosscity').value,page:1})};

async function refreshLibrary(){const d=await fetch('/api/library').then(r=>r.json());$('versions').replaceChildren();$('applications').replaceChildren();
for(const v of [...d.versions].reverse()){const c=el('div',undefined,'card');c.append(el('h2',v.name),el('p',(v.kind==='original'?'原始简历':'岗位定制版')+' · '+(v.reviewed?'已审阅':'待审阅')));const details=el('details');details.append(el('summary','展开查看完整简历及对应 JD'));const pre=el('pre',v.text,'eventlog');pre.style.whiteSpace='pre-wrap';details.append(pre);if(v.tailoring_report){const report=el('details');report.append(el('summary','修改依据与待确认事项'));for(const x of v.tailoring_report.changes)report.append(el('p',x));for(const x of v.tailoring_report.gaps)report.append(el('p','待确认：'+x));for(const x of v.tailoring_report.paragraph_changes){report.append(el('p','原文：'+x.before),el('p','改写：'+x.after))}report.append(el('p','请下载 Word 核对分页及版式。'));details.append(report)}if(v.job.jd){details.append(el('h3',v.job.title),jdTable(v.job.jd));const a=el('a','查看 BOSS 岗位 ↗');a.href=v.job.url;a.target='_blank';a.rel='noopener';details.append(a)}c.append(details);const dl=el('a','下载此版本 Word ↓');dl.href='/api/resume-file/'+v.id;const pv=el('div',undefined,'resume-preview');pv.style.display='none';const pb=el('button','在线预览 Word 版式');pb.type='button';pb.onclick=async()=>{if(pv.dataset.loaded){const show=pv.style.display==='none';pv.style.display=show?'block':'none';pb.textContent=show?'收起 Word 预览':'在线预览 Word 版式';return}pb.disabled=true;pb.textContent='正在渲染 Word…';try{const d=await fetch('/api/resume-preview/'+v.id).then(r=>r.json());if(d.error)throw Error(d.error);if(!d.pages||!d.pages.length)throw Error('未生成页面');pv.replaceChildren(...d.pages.map(u=>{const img=el('img');img.src=u;img.loading='lazy';img.alt=v.name;return img}));pv.dataset.loaded='1';pv.style.display='block';pb.textContent='收起 Word 预览'}catch(e){pb.textContent='预览失败：'+e.message}finally{pb.disabled=false}};const rw=el('div',undefined,'actions');rw.append(dl,pb);c.append(rw,pv);if(v.kind==='tailored'){const label=el('label');const check=el('input');check.type='checkbox';label.append(check,document.createTextNode('我已阅读此版本简历，确认内容真实且适用于该企业'));c.append(label);const review=el('button','确认审阅此版本');review.onclick=async()=>{try{await api('/api/library',{action:'review',id:v.id,confirmed:check.checked});await refreshLibrary()}catch(e){$('lstatus').textContent=e.message}};c.append(review);const apply=el('button','确认投递此版本到 BOSS');apply.disabled=!v.reviewed;apply.onclick=async()=>{if(!confirm('确认投递 '+v.name+' 到 '+v.job.title+'？将使用该版本；当前发送通道未连接时会进入等待，不会显示已投递。'))return;try{await api('/api/library',{action:'apply',id:v.id,confirmed:true});await refreshLibrary();$('lstatus').textContent='投递请求已保存，等待浏览器执行；尚未发送。'}catch(e){$('lstatus').textContent=e.message}};c.append(apply)}$('versions').append(c)}
if(!d.applications.length)$('applications').append(el('p','当前没有已记录的投递。'));for(const a of d.applications){const c=el('div',undefined,'card');c.append(el('h2',a.job.title),el('p',a.resume_name),el('p',a.note));$('applications').append(c)}}
$('wordfile').onchange=async e=>{const f=e.target.files[0];if(!f)return;if(f.size>8000000){$('lstatus').textContent='请选择8MB以内的Word文件';return}try{const bytes=new Uint8Array(await f.arrayBuffer());let raw='';for(let i=0;i<bytes.length;i+=8192)raw+=String.fromCharCode(...bytes.subarray(i,i+8192));const d=await api('/api/library',{action:'import',name:f.name,body:btoa(raw)});$('resume').value=d.version.text;await save();await refreshLibrary();$('lstatus').textContent='Word 原稿已保存，正文已导入经历档案'}catch(e){$('lstatus').textContent=e.message}};
$('generateword').onclick=async()=>{const b=$('generateword');b.disabled=true;$('lstatus').textContent='正在按当前 JD 生成独立 Word 版本…';try{await api('/api/library',{action:'generate',context:collect(),consent:$('wordconsent').checked});await refreshLibrary();$('lstatus').textContent='新版本已生成。请展开审阅并下载检查排版，再确认投递。'}catch(e){$('lstatus').textContent=e.message}finally{b.disabled=false}};
refreshLibrary();

function jdTable(text){
 const wrap=el('div');const table=el('table',undefined,'jd-table');const head=el('thead');const hr=el('tr');['类别','序号','JD 要求'].forEach(t=>hr.append(el('th',t)));head.append(hr);table.append(head);const body=el('tbody');let category='岗位描述',n=0;
 for(const raw of text.split(/\n+/)){const line=raw.trim();if(!line)continue;
 if(/^(岗位职责|工作职责|职责描述|岗位要求|任职要求|任职资格|加分项|优先条件|福利待遇)[：:]?$/.test(line)){category=line.replace(/[：:]$/,'');continue}
 const row=el('tr');row.append(el('td',category),el('td',String(++n)),el('td',line.replace(/^\d+[、.．）)]\s*/,'')));body.append(row)}
 if(!n){const row=el('tr');const cell=el('td','尚未填写 JD');cell.colSpan=3;row.append(cell);body.append(row)}table.append(body);wrap.append(table);return wrap;
}
const preview=el('div');preview.id='jdpreview';$('jd').after(preview);
function updateJDPreview(){preview.replaceChildren(el('h2','JD 表格预览'),jdTable($('jd').value))}
$('jd').addEventListener('input',updateJDPreview);
fetch('/api/state').then(r=>r.json()).then(d=>{if(!$('jd').value)$('jd').value=d.state.jd||'';updateJDPreview()});

let found=[];let finding=false;
async function refreshDiscovery(){const d=await fetch('/api/discovery').then(r=>r.json());found=d.jobs||[];$('findstatus').textContent=d.note||'';$('foundjobs').replaceChildren();for(const j of found){const c=el('div',undefined,'card');c.append(el('h2',j.company+' · '+j.title),el('p',[j.city,j.salary,j.experience,j.education].filter(Boolean).join(' · ')));const link=el('a','打开 BOSS 原始岗位 ↗');link.href=j.url;link.target='_blank';link.rel='noopener';c.append(link);if(j.jd){const details=el('details');details.append(el('summary','查看完整 JD'),jdTable(j.jd));c.append(details)}if(j.match)c.append(renderMessage(j.match));const b=el('button',j.source==='browser_visible'?'按已保存JD生成定制Word':'读取JD、匹配并生成对应Word');b.onclick=()=>j.source==='browser_visible'?tailorSavedJob(j):oneJob(j);c.append(b);$('foundjobs').append(c)}}
async function processJob(j){if(!$('findconsent').checked)throw Error('请先同意向模型发送简历与JD');collect();$('findstatus').textContent='正在读取并匹配：'+j.company+' · '+j.title;const job=await api('/api/discovery',{action:'detail',id:j.job_id,resume:state.resume,preferences:state.preferences,consent:true});if(job.decision!=='recommend'){await refreshDiscovery();$('findstatus').textContent=job.company+'：'+(job.decision==='reject'?'硬条件不匹配，已跳过生成':'有条件待确认，已保留匹配报告，未自动生成');return}$('findstatus').textContent='正在生成对应Word：'+job.company;await api('/api/library',{action:'generate',context:{resume:state.resume,preferences:state.preferences,jobtitle:job.company+' · '+job.title,joburl:job.url,jd:job.jd},consent:true});await refreshLibrary();await refreshDiscovery();$('findstatus').textContent='已生成 '+job.company+' 的对应Word，请到简历与投递台账查看并审阅。'}
async function oneJob(j){if(finding)return;finding=true;try{await processJob(j)}catch(e){$('findstatus').textContent=e.message}finally{finding=false}}
$('findjobs').onclick=async()=>{if(finding)return;finding=true;$('findstatus').textContent='正在查询BOSS站内岗位…';try{await api('/api/discovery',{action:'search',query:$('findquery').value,city:$('findcity').value});await refreshDiscovery()}catch(e){$('findstatus').textContent=e.message}finally{finding=false}};
let offFinding=false;
async function refreshOfficial(){const d=await fetch('/api/official-discovery').then(r=>r.json());const fails=Object.entries(d.per_company||{}).filter(([k,v])=>!v.ok).map(([k,v])=>(v.name||k)+' '+(v.error||v.code||''));$('offstatus').textContent=(d.note||'')+(fails.length?' · 失败：'+fails.join('；'):'');$('offjobs').replaceChildren();for(const j of (d.jobs||[])){const c=el('div',undefined,'card');c.append(el('h2',j.company+' · '+j.title),el('p',[j.city,j.salary,j.experience,j.education].filter(Boolean).join(' · ')));if(j.url){const link=el('a','打开官网原始岗位 ↗');link.href=j.url;link.target='_blank';link.rel='noopener';c.append(link)}if(j.jd){const details=el('details');details.append(el('summary','查看完整 JD'),jdTable(j.jd));c.append(details)}$('offjobs').append(c)}}
$('offsearch').onclick=async()=>{if(offFinding)return;offFinding=true;$('offstatus').textContent='正在查询官网岗位…';try{const body={action:'search',query:$('offquery').value.trim()||'AI测试'};const cs=$('offcompanies').value.trim();if(cs)body.companies=cs;await api('/api/official-discovery',body);await refreshOfficial()}catch(e){$('offstatus').textContent=e.message}finally{offFinding=false}};
$('batchtailor').onclick=async()=>{if(finding)return;if(!found.length){$('findstatus').textContent='请先成功搜索岗位';return}finding=true;try{for(const j of [...found])await processJob(j);$('findstatus').textContent='本次匹配已完成：推荐岗位已生成Word；有缺口或待确认的岗位保留报告，未自动生成。'}catch(e){$('findstatus').textContent=e.message+' 后续岗位已停止。'}finally{finding=false}};
refreshDiscovery();

async function tailorSavedJob(job){if(finding)return;if(!$('findconsent').checked){$('findstatus').textContent='请先同意将简历与JD发送模型';return}finding=true;try{collect();$('findstatus').textContent='正在按已核验JD生成Word，待确认经验不会写成既有事实…';await api('/api/library',{action:'generate',context:{resume:state.resume,preferences:state.preferences,jobtitle:job.company+' · '+job.title,joburl:job.url,jd:job.jd},consent:true});await refreshLibrary();$('findstatus').textContent='已生成对应Word，请在“我的简历与投递”查看；未投递。'}catch(e){$('findstatus').textContent=e.message}finally{finding=false}}

// Only backend execution milestones are shown; no simulated reasoning.
function attachTrace(container,id,onUpdate){
 const box=el('details',undefined,'trace-details');box.append(el('summary','查看执行记录'));
 const code=el('small','追踪 ID：'+id);const list=el('ol');const delivery=el('small','正在读取追踪状态…');box.append(code,list,delivery);container.append(box);
 let stopped=false,inflight=false,timer=null;
 async function refresh(){if(inflight)return;inflight=true;try{
  const r=await fetch('/api/activity/'+id,{headers:{'X-App-Token':token}});if(r.status===404){delivery.textContent='等待服务端接收请求';return}if(!r.ok)throw Error('记录读取失败');const d=await r.json();
  list.replaceChildren(...d.events.map(e=>el('li',new Date(e.time*1000).toLocaleTimeString()+' · '+e.message)));
  const labels={not_configured:'Langfuse 未配置 · 记录已保存在本机',pending:'Langfuse 正在上报',sent:'Langfuse 已接收 · 平台索引可能稍有延迟',failed:'Langfuse 上报失败 · 本地记录保留，可重试'};
  delivery.textContent=labels[d.export]||d.export;
  if(d.langfuse_url){try{const url=new URL(d.langfuse_url);if(['http:','https:'].includes(url.protocol)){const link=el('a','在 Langfuse 查看 ↗');link.href=url.href;link.target='_blank';link.rel='noopener';delivery.append(' · ',link)}}catch{}}
  if(d.export==='failed'||(d.export==='not_configured'&&d.status!=='running')){const retry=el('button','重试上报');retry.type='button';retry.onclick=async()=>{retry.disabled=true;try{await api('/api/activity-export',{id});await refresh()}catch(e){delivery.textContent=e.message}finally{retry.disabled=false}};delivery.append(' · ',retry)}
  if(onUpdate)onUpdate(d);
  if(d.status!=='running'&&d.export!=='pending'){clearInterval(timer);stopped=true}
 }catch{delivery.textContent='暂时无法读取执行记录'}finally{inflight=false}}
 refresh();timer=setInterval(refresh,1200);
 return {finish(){setTimeout(()=>{if(!stopped)refresh()},100);setTimeout(()=>clearInterval(timer),15000)}};
}
