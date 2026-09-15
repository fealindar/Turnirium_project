// --------------------------- Публичный экран ---------------------------
const publicTimers=new Map();
function setPublicTimer(m){
  if(!m)return;
  const existing=publicTimers.get(m.id), incoming=Math.max(0,m.remaining_ms||0), running=!!m.timer_running;
  if(existing && existing.revision===m.timer_revision && existing.running===running){
    const local=publicRemaining(m.id);
    // Периодический HTTP-опрос — только страховка. Не дёргаем таймер
    // из-за малой сетевой задержки, корректируем только заметное расхождение.
    if(Math.abs(local-incoming)<650)return;
  }
  publicTimers.set(m.id,{remaining:incoming,running,basePerf:performance.now(),revision:m.timer_revision});
}
function publicRemaining(id){const t=publicTimers.get(id);if(!t)return 0;return t.running?Math.max(0,t.remaining-(performance.now()-t.basePerf)):t.remaining;}
function publicGroupTableHtml(name,rows){return `<div class="public-table-box"><h4>Группа ${esc(name)}</h4><table><thead><tr><th>#</th><th>Участник</th><th>Поб</th><th>Н</th><th>Очки</th><th>Разн.</th></tr></thead><tbody>${rows.map(r=>`<tr class="${r.disqualified||r.participant_status==='withdrawn'?'muted-row':''}"><td>${r.place}</td><td>${esc(r.name)}</td><td>${r.wins}</td><td>${r.draws??0}</td><td><b>${r.points}</b></td><td>${r.diff>0?'+':''}${r.diff}</td></tr>`).join('')}</tbody></table></div>`;}
function publicBracketHtml(matches,categoryId){
  const stage=matches.some(m=>m.stage==='playoff')?'playoff':matches.some(m=>m.stage==='knockout')?'knockout':null;if(!stage)return '';
  const all=matches.filter(m=>m.stage===stage), bronze=all.find(m=>m.is_third_place), ms=all.filter(m=>!m.is_third_place);
  const rounds=[...new Set(ms.map(m=>m.round_no))].sort((a,b)=>a-b),last=rounds.at(-1);if(!last)return '';
  const card=m=>m?`<div class="public-bracket-card" data-public-bracket-match="${m.id}"><div class="${m.winner_cp_id===m.red?.cp_id?'winner':''}"><span>${esc(m.red?.name||'BYE')}</span><b>${m.red_score}</b></div><div class="${m.winner_cp_id===m.blue?.cp_id?'winner':''}"><span>${esc(m.blue?.name||'BYE')}</span><b>${m.blue_score}</b></div>${m.reason?`<small>${esc(reasonText(m.reason))}</small>`:''}</div>`:'';
  const column=(r,side)=>{const rows=ms.filter(m=>m.round_no===r).sort((a,b)=>a.match_no-b.match_no),half=Math.ceil(rows.length/2),show=side==='left'?rows.slice(0,half):rows.slice(half);return `<div class="public-mirror-round ${side}"><h4>${roundLabel(r,rounds.length)}</h4><div>${show.map(card).join('')}</div></div>`};
  const left=rounds.filter(r=>r<last).map(r=>column(r,'left')).join(''),right=rounds.filter(r=>r<last).sort((a,b)=>b-a).map(r=>column(r,'right')).join(''),final=ms.find(m=>m.round_no===last);
  return `<div class="public-mirror-bracket" data-public-bracket="${categoryId}:${stage}"><svg class="public-bracket-lines" aria-hidden="true"></svg>${left}<div class="public-final-column"><h4>Финал</h4>${card(final)}${bronze?`<div class="public-third"><h4>За 3-е место</h4>${card(bronze)}</div>`:''}</div>${right}</div>`;
}
function drawPublicBracketLines(root,matches){
  const svg=$('.public-bracket-lines',root);if(!svg)return;
  const bounds=root.getBoundingClientRect();if(!bounds.width||!bounds.height)return;
  svg.setAttribute('viewBox',`0 0 ${bounds.width} ${bounds.height}`);svg.setAttribute('width',bounds.width);svg.setAttribute('height',bounds.height);
  const paths=[];
  for(const match of matches){
    if(!match.next_match_id)continue;
    const source=$(`[data-public-bracket-match="${match.id}"]`,root),target=$(`[data-public-bracket-match="${match.next_match_id}"]`,root);if(!source||!target)continue;
    const a=source.getBoundingClientRect(),b=target.getBoundingClientRect(),leftToRight=a.left<b.left;
    const sx=(leftToRight?a.right:a.left)-bounds.left,sy=a.top+a.height/2-bounds.top;
    const tx=(leftToRight?b.left:b.right)-bounds.left,ty=b.top+b.height/2-bounds.top,mx=(sx+tx)/2;
    paths.push(`<path d="M ${sx.toFixed(1)} ${sy.toFixed(1)} H ${mx.toFixed(1)} V ${ty.toFixed(1)} H ${tx.toFixed(1)}"/>`);
  }
  svg.innerHTML=paths.join('');
}
function redrawPublicBrackets(data){
  for(const row of data?.categories||[]){
    const matches=row.matches||[],stage=matches.some(m=>m.stage==='playoff')?'playoff':matches.some(m=>m.stage==='knockout')?'knockout':null;if(!stage)continue;
    const root=$(`[data-public-bracket="${row.category.id}:${stage}"]`);if(root)drawPublicBracketLines(root,matches.filter(m=>m.stage===stage));
  }
}
function renderPublicDashboard(data){
  for(const r of data.areas) if(r.current)setPublicTimer(r.current);
  const areas=data.areas.map(r=>{const m=r.current;return `<div class="public-area"><div class="public-area-title"><h2>${esc(r.area.name)}</h2><span>${m?esc(statusText(m.status)):'свободна'}</span></div>${m?`<div class="public-fight"><span class="public-red-name">${esc(m.red?.name||'—')}</span><b>—</b><span class="public-blue-name">${esc(m.blue?.name||'—')}</span></div><div class="public-category">${esc(m.category_name)} · ${esc(stageName(m))}</div><div class="public-score-line"><b>${m.red_score}</b><span class="public-timer" data-public-timer="${m.id}">${fmtTime(m.remaining_ms)}</span><b>${m.blue_score}</b></div>`:'<div class="public-idle">Площадка свободна</div>'}<div class="public-next">Следующий: ${r.next?`${esc(r.next.red?.name||'—')} — ${esc(r.next.blue?.name||'—')} · ${esc(r.next.category_name)}`:'—'}</div></div>`}).join('')||'<div class="public-idle">Нет площадок</div>';
  const details=data.categories.map(c=>{const cat=c.category;let body='';const groupNames=Object.keys(c.group_tables||{});if(groupNames.length)body+=`<div class="public-group-tables">${groupNames.map(g=>publicGroupTableHtml(g,c.group_tables[g])).join('')}</div>`;if(['swiss','round_robin'].includes(cat.format)&&c.standings?.length)body+=`<div class="public-group-tables">${publicGroupTableHtml(cat.format==='swiss'?'Swiss':'Все со всеми',c.standings)}</div>`;body+=publicBracketHtml(c.matches||[],cat.id);return body?`<section class="public-category-panel"><div class="public-category-head"><h3>${esc(cat.name)}</h3><span>${esc(formatName(cat.format))}</span></div>${body}</section>`:''}).join('');
  $('#publicAreas').innerHTML=areas;$('#publicDetails').innerHTML=details||'<div class="public-idle">Сетки и таблицы появятся после жеребьевки.</div>';
  requestAnimationFrame(()=>requestAnimationFrame(()=>redrawPublicBrackets(data)));
}
async function initPublic(tournamentId){
  document.body.className='public-body'; ensureBranding(); $('#app').innerHTML=`<div class="public-screen"><div class="public-head"><div><h1 id="publicTitle">Турнир</h1><span>Текущие поединки, таблицы и сетки</span></div><div class="public-clock" id="publicClock"></div></div><div id="publicAreas" class="public-grid"></div><div id="publicDetails" class="public-details"></div></div>`;
  let latest=null;
  const load=async()=>{try{latest=await api(`/api/tournaments/${tournamentId}/public-dashboard`);$('#publicTitle').textContent=latest.tournament.name;renderPublicDashboard(latest)}catch(e){}};
  await load();wsConnect(()=>load());setInterval(load,10000);
  let resizeTimer=null;window.addEventListener('resize',()=>{clearTimeout(resizeTimer);resizeTimer=setTimeout(()=>redrawPublicBrackets(latest),80)});
  clearInterval(window.__publicTimerPaint);window.__publicTimerPaint=setInterval(()=>{$$('[data-public-timer]').forEach(el=>el.textContent=fmtTime(publicRemaining(Number(el.dataset.publicTimer))))},80);
  const paintClock=()=>{const el=$('#publicClock');if(el)el.textContent=new Date().toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})};paintClock();setInterval(paintClock,1000);
}
