// --------------------------- Экран секретаря ---------------------------
let timerView={matchId:null,remaining:0,running:false,basePerf:0,warningSec:10};
function setTimerSnapshot(m){timerView={matchId:m?.id||null,remaining:m?.remaining_ms||0,running:!!m?.timer_running,basePerf:performance.now(),warningSec:m?.timer_warning_sec??10};}
function timerNow(){return timerView.running?Math.max(0,timerView.remaining-(performance.now()-timerView.basePerf)):timerView.remaining;}
function startTimerPainter(selector){clearInterval(window.__timerPaint);window.__timerPaint=setInterval(()=>{const el=$(selector);if(el)el.textContent=fmtTime(timerNow());},100);}
async function initSecretary(areaId){
  document.body.className='secretary'; ensureBranding();
  $('#app').innerHTML=`<div class="topbar"><div class="brand secretary-brand">${brandIconHtml()}<div><div class="brand-title">${esc(BRANDING.app_name)}</div><div class="brand-sub" id="areaTitle">Площадка</div></div></div><a href="/admin">Организатор</a><a href="/board/${areaId}" target="_blank">Табло ↗</a></div><div class="container" id="secretaryContent"></div>`;
  const load=async()=>{try{const st=await api(`/api/areas/${areaId}/state`);const cm=st.current?await api(`/api/categories/${st.current.category_id}/matches`):[];renderSecretary(st,areaId,cm);setTimerSnapshot(st.current);startTimerPainter('#fightTimer')}catch(e){toast(e.message,true)}};
  await load(); wsConnect(e=>{if(!e.area_id||Number(e.area_id)===Number(areaId)||['schedule_changed','bracket_changed'].includes(e.type)) load();});
  setInterval(load,5000);
}
let secretaryInfoTab='queue';
function secretaryStageLabel(match, categoryMatches=[]) {
  if (match.is_third_place) return 'Бой за 3-е место';
  if (match.stage === 'group') return `Группа ${match.group_name || '—'}`;
  if (match.stage === 'swiss') return `Тур ${match.round_no}`;
  if (match.stage === 'round_robin') return 'Круговой этап';
  if (['knockout','playoff'].includes(match.stage)) {
    const rounds = categoryMatches.filter(row => row.stage === match.stage && !row.is_third_place).map(row => row.round_no);
    const total = Math.max(match.round_no, ...rounds, 1);
    return roundLabel(match.round_no, total);
  }
  return stageName(match);
}

function renderSecretary(st,areaId,categoryMatches=[]){
  $('#areaTitle').textContent=st.area.name; const m=st.current;
  if(!m){$('#secretaryContent').innerHTML=`<div class="empty-state compact"><h2>Нет выбранного поединка</h2><p>Если бой уже назначен на площадку, выберите следующий.</p><button id="nextFight" class="primary">Выбрать следующий</button></div>${secretaryInfoTabsHtml(st,categoryMatches,null)}`;$('#nextFight').onclick=()=>nextFight(areaId);bindSecretaryInfoTabs();return;}
  const buttons=(side)=>m.score_buttons.map(b=>`<button data-score-side="${side}" data-delta="${b.delta}" ${m.status==='finished'?'disabled':''}>${esc(b.label)}</button>`).join('');
  $('#secretaryContent').innerHTML=`<div class="fight-panel">
    <div class="fighter red"><div class="name">${esc(m.red?.name||'—')}</div><div class="club">${esc(affiliation(m.red))}</div><div class="score">${m.red_score}</div><div class="score-buttons">${buttons('red')}</div><div class="row fighter-actions"><button data-warning="red" ${m.status==='finished'?'disabled':''}>⚠ Предупреждение (${m.red_warnings})</button><button class="tech-loss-btn" data-tech-loss="red" ${m.status==='finished'?'disabled':''}>Тех. поражение</button></div></div>
    <div class="timer-box"><div class="fight-meta">${esc(m.category_name)}</div><div class="secretary-context"><span class="secretary-context-badge">${esc(formatName(m.category_format))}</span><span class="secretary-context-badge stage">${esc(secretaryStageLabel(m,categoryMatches))}</span></div><div class="timer" id="fightTimer">${fmtTime(m.remaining_ms)}</div><div class="timer-controls"><button id="toggleTimer" class="timer-toggle ${m.timer_running?'running':''}" ${m.status==='finished'?'disabled':''}>${m.timer_running?'Ⅱ Пауза':'▶ Старт'}</button><button id="resetTimer" class="timer-secondary" ${m.status==='finished'?'disabled':''}>↺ Сброс</button><button id="setTimer" class="timer-secondary" ${m.status==='finished'?'disabled':''}>Время</button></div><div class="stack center-actions">${m.status==='finished'?`<button id="correctCurrentFight" class="primary">✎ Исправить завершенный бой</button>`:`<button id="undoBtn">Отменить последнее</button><button class="success" data-win="${m.red?.cp_id||''}">Победа красного по счёту</button><button class="success" data-win="${m.blue?.cp_id||''}">Победа синего по счёту</button>${['group','swiss','round_robin'].includes(m.stage)?'<button id="drawFight">Ничья</button>':''}`}<button id="nextFight" ${m.status==='finished'?'':'disabled title="Сначала внесите результат текущего боя"'}>Следующий бой</button>${m.status==='finished'?'':'<small class="next-fight-lock">Сначала внесите результат текущего боя</small>'}</div><div class="fight-status-pill">${esc(statusText(m.status))}${m.reason?' · '+esc(reasonText(m.reason)):''}</div></div>
    <div class="fighter blue"><div class="name">${esc(m.blue?.name||'—')}</div><div class="club">${esc(affiliation(m.blue))}</div><div class="score">${m.blue_score}</div><div class="score-buttons">${buttons('blue')}</div><div class="row fighter-actions"><button data-warning="blue" ${m.status==='finished'?'disabled':''}>⚠ Предупреждение (${m.blue_warnings})</button><button class="tech-loss-btn" data-tech-loss="blue" ${m.status==='finished'?'disabled':''}>Тех. поражение</button></div></div>
  </div><div class="queue-preview"><div class="card"><h3>Следующий · подготовиться</h3><div>${st.next?esc(matchTitle(st.next)):'Очередь пуста'}</div></div><div class="card"><h3>После него</h3><div>${st.following?esc(matchTitle(st.following)):'—'}</div></div></div>${secretaryInfoTabsHtml(st,categoryMatches,m)}`;
  $$('[data-score-side]').forEach(b=>b.onclick=()=>matchAction(m.id,'score',{side:b.dataset.scoreSide,delta:Number(b.dataset.delta)}));
  $$('[data-warning]').forEach(b=>b.onclick=async()=>{try{const r=await api(`/api/matches/${m.id}/warning`,{method:'POST',body:JSON.stringify({side:b.dataset.warning})});const o=r.outcome;if(o.disqualified)toast('Достигнут лимит предупреждений: участник дисквалифицирован',true);else if(o.action==='forfeit')toast('По правилу предупреждения назначено поражение');else if(o.action==='score_penalty')toast(`Штраф к счёту: ${o.delta}`);}catch(e){toast(e.message,true)}});
  $$('[data-tech-loss]').forEach(b=>b.onclick=async()=>{const losing=b.dataset.techLoss,winner=losing==='red'?m.blue?.cp_id:m.red?.cp_id;if(!winner)return;if(!confirm(`Зафиксировать техническое поражение ${losing==='red'?'красной':'синей'} стороны?`))return;try{await api(`/api/matches/${m.id}/finish`,{method:'POST',body:JSON.stringify({winner_cp_id:Number(winner),reason:'TECHNICAL_LOSS'})})}catch(e){toast(e.message,true)}});
  if($('#toggleTimer')) $('#toggleTimer').onclick=async()=>{const button=$('#toggleTimer');button.disabled=true;try{await api(`/api/matches/${m.id}/timer/${m.timer_running?'pause':'start'}`,{method:'POST'})}catch(e){toast(e.message,true);button.disabled=false}};
  if($('#resetTimer')) $('#resetTimer').onclick=()=>{if(confirm('Сбросить таймер на полную длительность?'))simplePost(`/api/matches/${m.id}/timer/reset`)};
  if($('#setTimer')) $('#setTimer').onclick=()=>{const sec=prompt('Оставшееся время в секундах:',Math.ceil(m.remaining_ms/1000));if(sec!==null)simplePost(`/api/matches/${m.id}/timer/set`,{seconds:Number(sec)})};
  if($('#undoBtn')) $('#undoBtn').onclick=()=>simplePost(`/api/matches/${m.id}/undo`);
  if($('#correctCurrentFight')) $('#correctCurrentFight').onclick=()=>openMatchCorrection(m.id);
  $$('[data-win]').forEach(b=>b.onclick=async()=>{if(!b.dataset.win)return;if(!confirm('Подтвердить победу по счёту?'))return;try{await api(`/api/matches/${m.id}/finish`,{method:'POST',body:JSON.stringify({winner_cp_id:Number(b.dataset.win),reason:'POINTS'})})}catch(e){toast(e.message,true)}});
  if($('#drawFight')) $('#drawFight').onclick=async()=>{if(!confirm('Зафиксировать ничью?'))return;try{await api(`/api/matches/${m.id}/finish`,{method:'POST',body:JSON.stringify({winner_cp_id:null,reason:'DRAW'})})}catch(e){toast(e.message,true)}};
  $('#nextFight').onclick=()=>nextFight(areaId); bindSecretaryInfoTabs();
}
async function nextFight(areaId){try{await api(`/api/areas/${areaId}/next`,{method:'POST'})}catch(e){toast(e.message,true)}}
async function simplePost(path,body=null){try{await api(path,{method:'POST',body:body?JSON.stringify(body):undefined})}catch(e){toast(e.message,true)}}
async function matchAction(id,action,body){try{await api(`/api/matches/${id}/${action}`,{method:'POST',body:JSON.stringify(body)})}catch(e){toast(e.message,true)}}
function secretaryInfoTabsHtml(st,matches,current){
  const queue=st.queue||[];
  const grouped={};for(const m of queue){const key=`${m.category_name} · ${stageName(m)}`;(grouped[key]??=[]).push(m)}
  const queueHtml=Object.entries(grouped).map(([k,rows])=>`<div class="secretary-group"><h4>${esc(k)}</h4><div class="compact-match-grid">${rows.map(x=>`<div class="match-chip"><span>#${x.match_no}</span><b>${esc(x.red?.name||'—')} — ${esc(x.blue?.name||'—')}</b></div>`).join('')}</div></div>`).join('')||'<span class="muted">Предстоящих боёв на площадке нет.</span>';
  const bracketMatches=matches.filter(x=>['knockout','playoff'].includes(x.stage));
  const rounds=[...new Set(bracketMatches.map(x=>`${x.stage}:${x.round_no}`))];
  const bracketHtml=rounds.map(key=>{const [stage,r]=key.split(':');const rows=bracketMatches.filter(x=>x.stage===stage&&x.round_no===Number(r));return `<div class="secretary-group"><h4>${stage==='playoff'?'Плей-офф':'Олимпийская'} · ${roundLabel(Number(r),Math.max(...bracketMatches.filter(x=>x.stage===stage).map(x=>x.round_no),1))}</h4><div class="compact-match-grid">${rows.map(x=>compactSecretaryMatch(x,current,st.area.id)).join('')}</div></div>`}).join('')||'<span class="muted">В этой категории нет олимпийской сетки.</span>';
  const groupNames=[...new Set(matches.filter(x=>x.stage==='group').map(x=>x.group_name))].sort();
  const groupsHtml=groupNames.map(g=>`<div class="secretary-group"><h4>Группа ${esc(g)}</h4><div class="compact-match-grid">${matches.filter(x=>x.stage==='group'&&x.group_name===g).map(x=>compactSecretaryMatch(x,current,st.area.id)).join('')}</div></div>`).join('')||'<span class="muted">Группового этапа нет.</span>';
  return `<section class="card secretary-info top-gap"><div class="secretary-tabs"><button data-sec-tab="queue" class="${secretaryInfoTab==='queue'?'active':''}">Очередь по сетке</button><button data-sec-tab="bracket" class="${secretaryInfoTab==='bracket'?'active':''}">Сетка</button><button data-sec-tab="groups" class="${secretaryInfoTab==='groups'?'active':''}">Группы</button></div><div data-sec-panel="queue" class="sec-panel ${secretaryInfoTab==='queue'?'active':''}">${queueHtml}</div><div data-sec-panel="bracket" class="sec-panel ${secretaryInfoTab==='bracket'?'active':''}">${bracketHtml}</div><div data-sec-panel="groups" class="sec-panel ${secretaryInfoTab==='groups'?'active':''}">${groupsHtml}</div></section>`;
}
function compactSecretaryMatch(x,current,areaId){return `<div class="match-chip ${x.id===current?.id?'current':''}"><div class="muted">#${x.match_no}${x.is_third_place?' · за 3-е место':''} · ${esc(statusText(x.status))}</div><div>${esc(x.red?.name||'—')} <b>${x.red_score}</b></div><div>${esc(x.blue?.name||'—')} <b>${x.blue_score}</b></div>${x.reason?`<small>${esc(reasonText(x.reason))}</small>`:''}${x.status==='finished'&&x.reason!=='BYE'&&Number(x.area_id)===Number(areaId)?`<button class="small ghost top-gap-small" data-correct-match="${x.id}">Исправить</button>`:''}</div>`}
function bindSecretaryInfoTabs(){ $$('[data-sec-tab]').forEach(b=>b.onclick=()=>{secretaryInfoTab=b.dataset.secTab;$$('[data-sec-tab]').forEach(x=>x.classList.toggle('active',x===b));$$('[data-sec-panel]').forEach(x=>x.classList.toggle('active',x.dataset.secPanel===secretaryInfoTab));}); bindMatchCorrectionButtons(); }

