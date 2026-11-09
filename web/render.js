/* Safe DOM rendering: model output is text, never executable HTML. */
function inlineText(target,text){
 const pattern=/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|\*\*([^*]+)\*\*/g;let last=0;
 for(const m of text.matchAll(pattern)){target.append(document.createTextNode(text.slice(last,m.index)));if(m[1]){const a=document.createElement('a');a.textContent=m[1];a.href=m[2];a.target='_blank';a.rel='noopener noreferrer';target.append(a)}else{const b=document.createElement('strong');b.textContent=m[3];target.append(b)}last=m.index+m[0].length}target.append(document.createTextNode(text.slice(last)));
}
function messageTable(headers,rows){const wrap=document.createElement('div');wrap.className='chat-table-wrap';const table=document.createElement('table');table.className='jd-table chat-table';const head=document.createElement('thead');const hr=document.createElement('tr');headers.forEach(t=>{const c=document.createElement('th');inlineText(c,t);hr.append(c)});head.append(hr);table.append(head);const body=document.createElement('tbody');for(const row of rows){const tr=document.createElement('tr');headers.forEach((_,i)=>{const td=document.createElement('td');inlineText(td,row[i]||'');tr.append(td)});body.append(tr)}table.append(body);wrap.append(table);return wrap}
function renderMessage(text){const root=document.createElement('div');root.className='message-body';const lines=text.split('\n');const cells=s=>s.trim().replace(/^\||\|$/g,'').split('|').map(x=>x.trim());const labeled=s=>s.match(/^\s*[-*]\s+\*\*([^*]+)\*\*\s*[：:]\s*(.+)$/);
 for(let i=0;i<lines.length;){const line=lines[i];if(!line.trim()){i++;continue}
  if(line.includes('|')&&i+1<lines.length&&/^\s*\|?\s*:?-{3,}:?\s*\|/.test(lines[i+1])){const headers=cells(line),rows=[];i+=2;while(i<lines.length&&lines[i].includes('|')&&lines[i].trim()){rows.push(cells(lines[i++]));}root.append(messageTable(headers,rows));continue}
  if(labeled(line)){const rows=[];let j=i;while(j<lines.length){const m=labeled(lines[j]);if(!m)break;rows.push([m[1],m[2]]);j++}if(rows.length>=2){root.append(messageTable(['类别','要求内容'],rows));i=j;continue}}
  if(/^\s*[-*]\s+/.test(line)){const list=document.createElement('ul');while(i<lines.length&&/^\s*[-*]\s+/.test(lines[i])){const li=document.createElement('li');inlineText(li,lines[i++].replace(/^\s*[-*]\s+/,''));list.append(li)}root.append(list);continue}
  const node=document.createElement(/^#{1,3}\s/.test(line)?'h3':'p');inlineText(node,line.replace(/^#{1,6}\s+/,''));root.append(node);i++;
 }return root;
}
