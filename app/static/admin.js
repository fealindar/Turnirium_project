async function initAdmin() {
  document.body.className='admin-page'; ensureBranding();
  $('#app').innerHTML = `
    <header class="admin-header">
      <div class="brand">${brandIconHtml()}<div><div class="brand-title">${esc(BRANDING.app_name)}</div><div class="brand-sub">Организатор</div></div></div>
      <div class="connection-pill"><span id="wsDot" class="status-dot"></span><span id="wsText">Подключение…</span></div>
      <span id="dbInfo" class="header-meta"></span>
    </header>
    <main class="admin-shell">
      <div class="tournament-toolbar" id="tournamentBar"></div>
      <nav class="admin-nav">
        <button data-tab="overview" class="active">Обзор</button>
        <button data-tab="participants">Участники</button>
        <button data-tab="categories">Категории</button>
        <button data-tab="bracket">Сетки и результаты</button>
        <button data-tab="schedule">Площадки</button>
        <button data-tab="screens">Экраны</button>
        <button data-tab="network">Сеть</button>
        <button data-tab="service">Сервис</button>
      </nav>
      <div id="adminContent"></div>
    </main>`;
  try { const s=await api('/api/system'); const db=$('#dbInfo');db.textContent=`БД: ${s.db_path}`;db.title=s.db_path||''; } catch {}
  $$('.admin-nav button').forEach(b=>b.onclick=()=>{ $$('.admin-nav button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); renderAdminTab(b.dataset.tab); });
  await loadAdminBase();
  wsConnect(async e=>{
    if (e.type==='clients_changed'){ if($('.admin-nav button.active')?.dataset.tab==='network') renderNetwork(); return; }
    if (e.type==='database_switched'){
      localStorage.removeItem('tournamentId');
      adminState.selectedCategoryId=null;
      await loadAdminBase();
      try{const s=await api('/api/system');const db=$('#dbInfo');if(db){db.textContent=`БД: ${s.db_path}`;db.title=s.db_path||''}}catch{}
      renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview');
      toast('Рабочая база данных переключена');
      return;
    }
    if (!adminState.tournamentId) return;
    if (e.type==='database_cleared'){ await loadAdminBase(); renderAdminTab('overview'); return; }
    if (e.type==='templates_changed'){ adminState.templates=await api('/api/category-templates'); if($('.admin-nav button.active')?.dataset.tab==='categories')renderCategories(); return; }
    if (['schedule_changed','areas_changed','match_changed','match_finished','match_corrected','area_changed','timer_changed','timer_finished','bracket_changed','participants_changed','categories_changed','category_changed','tournament_changed'].includes(e.type)) {
      // Всегда обновляем выбранную категорию: раньше после завершения боя
      // обновлялось только расписание, а сетка оставалась старой до F5.
      await refreshAdminData(true);
      renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview');
    }
  }, online=>{ const d=$('#wsDot'),t=$('#wsText'); if(d)d.classList.toggle('online',online); if(t)t.textContent=online?'Синхронизация активна':'Переподключение…'; });
  // Основной канал обновлений — WebSocket. Тихий резервный опрос помогает
  // при ограничениях Wi-Fi/AP и не прерывает заполнение форм.
  clearInterval(window.__adminFallbackPoll);
  window.__adminFallbackPoll=setInterval(async()=>{
    const tab=$('.admin-nav button.active')?.dataset.tab;
    if(tab==='network'){try{renderNetwork()}catch{};return;}
    if(!adminState.tournamentId || !['overview','bracket','schedule','screens'].includes(tab))return;
    try{await refreshAdminData(true);renderAdminTab(tab)}catch{}
  },10000);
}
async function loadAdminBase() {
  [adminState.tournaments,adminState.templates]=await Promise.all([api('/api/tournaments'),api('/api/category-templates')]);
  const saved=Number(localStorage.getItem('tournamentId'));
  const activeTs=adminState.tournaments.filter(t=>t.status!=='completed');
  adminState.tournamentId = adminState.tournaments.some(t=>t.id===saved) ? saved : activeTs[0]?.id || null;
  renderTournamentBar();
  if (adminState.tournamentId) await refreshAdminData(); else renderAdminTab('overview');
}
function renderTournamentBar() {
  const bar=$('#tournamentBar');
  const active=adminState.tournaments.filter(t=>t.status!=='completed');
  const archived=adminState.tournaments.filter(t=>t.status==='completed');
  const current=adminState.tournaments.find(t=>t.id===adminState.tournamentId);
  bar.innerHTML=`<div class="field tournament-picker"><label>Активный турнир</label><select id="tournamentSelect"><option value="">— создать —</option>${active.map(t=>`<option value="${t.id}" ${t.id===adminState.tournamentId?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div>
    ${archived.length?`<div class="field archive-picker"><label>Архив</label><select id="tournamentArchive"><option value="">Завершенные (${archived.length})…</option>${archived.map(t=>`<option value="${t.id}" ${t.id===adminState.tournamentId?'selected':''}>${esc(t.name)}</option>`).join('')}</select></div>`:''}
    <button id="newTournament" class="primary">+ Новый турнир</button>${current?(current.status==='completed'?'<button id="reopenTournament">Вернуть в активные</button>':'<button id="completeTournament">✓ Завершить турнир</button>') : ''}${current?`<button id="exportTournamentPdf">PDF</button><button id="exportTournamentJson">JSON</button>`:''}<button id="backupBtn">Резервная копия</button><span class="toolbar-hint">${current?.status==='completed'?'Открыт архивный турнир: просмотр и экспорт результатов.':'Главный компьютер хранит БД; остальные рабочие места подключаются по локальной сети.'}</span>`;
  $('#tournamentSelect').onchange=async e=>{ adminState.tournamentId=Number(e.target.value)||null; localStorage.setItem('tournamentId',adminState.tournamentId||''); await refreshAdminData(); renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview'); };
  if($('#tournamentArchive')) $('#tournamentArchive').onchange=async e=>{const id=Number(e.target.value);if(!id)return;adminState.tournamentId=id;localStorage.setItem('tournamentId',id);await refreshAdminData();renderTournamentBar();renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview');};
  $('#newTournament').onclick=async()=>{ const name=prompt('Название турнира:','Новый Турнир'); if(!name)return; try{const r=await api('/api/tournaments',{method:'POST',body:JSON.stringify({name})}); localStorage.setItem('tournamentId',r.id); await loadAdminBase(); renderAdminTab('overview');}catch(e){toast(e.message,true)} };
  if($('#completeTournament')) $('#completeTournament').onclick=async()=>{if(!confirm(`Завершить турнир «${current?.name||''}»? Он уйдет в архив, а все его категории будут закрыты.`))return;try{const r=await api(`/api/tournaments/${adminState.tournamentId}/complete`,{method:'POST'});await loadAdminBase();adminState.tournamentId=current.id;localStorage.setItem('tournamentId',current.id);await refreshAdminData();renderTournamentBar();renderAdminTab('overview');if(r.export_error)toast(`Турнир завершён, но экспорт не создан: ${r.export_error}`,true);else toast('Турнир завершён. PDF и JSON подготовлены в архиве.')}catch(e){toast(e.message,true)}};
  if($('#reopenTournament')) $('#reopenTournament').onclick=async()=>{if(!confirm('Вернуть этот турнир и его категории в работу? Категории останутся завершенными, пока вы не откроете их отдельно.'))return;try{await api(`/api/tournaments/${current.id}/reopen`,{method:'POST'});await loadAdminBase();adminState.tournamentId=current.id;localStorage.setItem('tournamentId',current.id);await refreshAdminData();renderTournamentBar();renderAdminTab('overview');toast('Турнир возвращён в активные')}catch(e){toast(e.message,true)}};
  if($('#exportTournamentPdf')) $('#exportTournamentPdf').onclick=()=>downloadUrl(`/api/tournaments/${current.id}/export.pdf`);
  if($('#exportTournamentJson')) $('#exportTournamentJson').onclick=()=>downloadUrl(`/api/tournaments/${current.id}/export.json`);
  $('#backupBtn').onclick=async()=>{try{const r=await api('/api/backup',{method:'POST'});toast(`Копия создана: ${r.path}`)}catch(e){toast(e.message,true)}};
}

async function refreshAdminData(withCategory=true) {
  if(!adminState.tournamentId) return;
  [adminState.participants,adminState.categories,adminState.areas,adminState.schedule]=await Promise.all([
    api(`/api/tournaments/${adminState.tournamentId}/participants`), api(`/api/tournaments/${adminState.tournamentId}/categories`), api(`/api/tournaments/${adminState.tournamentId}/areas`), api(`/api/tournaments/${adminState.tournamentId}/schedule`)
  ]);
  const activeCats=adminState.categories.filter(c=>c.status!=='completed');
  if(!adminState.categories.some(c=>c.id===adminState.selectedCategoryId)) adminState.selectedCategoryId=activeCats[0]?.id||adminState.categories[0]?.id||null;
  if(withCategory && adminState.selectedCategoryId) await loadSelectedCategory();
}
async function loadSelectedCategory(){
  if(!adminState.selectedCategoryId){adminState.categoryParticipants=[];adminState.matches=[];return;}
  [adminState.categoryParticipants,adminState.matches]=await Promise.all([api(`/api/categories/${adminState.selectedCategoryId}/participants`),api(`/api/categories/${adminState.selectedCategoryId}/matches`)]);
}
function renderAdminTab(tab){
  if(tab==='network'){renderNetwork();return;}
  if(tab==='service'){renderService();return;}
  if(!adminState.tournamentId){$('#adminContent').innerHTML=`<section class="empty-state"><div class="empty-icon">🏆</div><h2>Создайте первый турнир</h2><p>Площадка №1 будет создана автоматически. После этого добавьте участников и категории.</p></section>`;return;}
  if(tab==='overview') renderOverview();
  else if(tab==='participants') renderParticipants();
  else if(tab==='categories') renderCategories();
  else if(tab==='bracket') renderBracketTab();
  else if(tab==='schedule') renderSchedule();
  else if(tab==='screens') renderScreens();
  else renderService();
}
function renderOverview(){
  const live=(adminState.schedule?.areas||[]).filter(a=>a.matches.some(m=>m.status==='in_progress')).length;
  const ready=(adminState.schedule?.areas||[]).reduce((n,a)=>n+a.matches.filter(m=>['ready','pending'].includes(m.status)).length,0)+(adminState.schedule?.unassigned?.length||0);
  $('#adminContent').innerHTML=`
    <div class="metric-grid">
      <div class="metric-card"><span>Участники</span><b>${adminState.participants.length}</b></div>
      <div class="metric-card"><span>Активные категории</span><b>${adminState.categories.filter(c=>c.status!=='completed').length}</b></div>
      <div class="metric-card"><span>Площадки</span><b>${adminState.areas.length}</b></div>
      <div class="metric-card"><span>Готовых боёв</span><b>${ready}</b></div>
    </div>
    <div class="section-head"><div><h2>Состояние площадок</h2><p>Обновляется автоматически при действиях секретарей.</p></div><span class="pill ${live?'live-pill':''}">${live?`Сейчас идут: ${live}`:'Нет активных боёв'}</span></div>
    <div class="area-dashboard">${(adminState.schedule?.areas||[]).map(col=>{
      const current=col.matches.find(m=>m.id===col.area.current_match_id); const next=col.matches.find(m=>m.id!==col.area.current_match_id && ['ready','pending'].includes(m.status));
      return `<article class="area-card"><div class="area-card-head"><h3>${esc(col.area.name)}</h3><div class="quick-links"><a href="/mat/${col.area.id}" target="_blank">Секретарь ↗</a><a href="/board/${col.area.id}" target="_blank">Табло ↗</a></div></div>
        ${current?`<div class="current-fight"><span class="eyebrow">Текущий бой</span><b>${esc(current.red?.name||'—')} — ${esc(current.blue?.name||'—')}</b><small>${esc(current.category_name)} · ${fmtTime(current.remaining_ms)} · ${current.red_score}:${current.blue_score}</small></div>`:`<div class="current-fight idle"><span>Площадка свободна</span></div>`}
        <div class="next-fight"><span>Следующий</span><b>${next?`${esc(next.red?.name||'—')} — ${esc(next.blue?.name||'—')}`:'—'}</b></div></article>`;
    }).join('')||'<div class="card">Нет площадок.</div>'}</div>
    <div class="card operation-tip"><b>Упрощённый режим:</b> если площадка одна, все готовые поединки назначаются на неё автоматически, а первый готовый бой сразу выбирается как текущий.</div>`;
}
function renderParticipants(){
  $('#adminContent').innerHTML=`<div class="grid grid2 admin-two"><div class="card form-card"><div class="card-title"><h2>Новый участник</h2><span>Карточка спортсмена</span></div><form id="participantForm" class="stack">
    <div class="row"><div class="field grow"><label>Фамилия</label><input name="last_name" placeholder="Например: Иванова" required></div><div class="field grow"><label>Имя</label><input name="first_name" placeholder="Например: Анна"></div></div>
    <div class="row"><div class="field grow"><label>Клуб / школа</label><input name="club" placeholder="Например: Боевые Хомяки"></div><div class="field grow"><label>Город</label><input name="city" placeholder="Например: Москва"></div></div><button class="primary">Добавить участника</button></form></div>
    <div class="card"><div class="card-title row"><div class="grow"><h2>Участники · ${adminState.participants.length}</h2><span>Статус «Выбыл» исключает спортсмена из новых жеребьевок; уже назначенные будущие бои закрываются проходом соперника.</span></div><input id="participantSearch" class="search" placeholder="Поиск…"></div><div class="participant-tools"><button id="exportParticipantsCsv">Экспорт CSV</button><button id="exportParticipantsJson">Экспорт JSON</button><button id="importParticipantsBtn" class="primary">Импорт списка</button><input id="importParticipantsFile" type="file" accept=".csv,.json,text/csv,application/json" hidden><span class="muted">CSV: Фамилия;Имя;Клуб;Город;Статус</span></div><div id="participantTable"></div></div></div>`;
  const draw=(q='')=>{q=q.trim().toLowerCase();const rows=adminState.participants.filter(p=>!q||[p.name,p.club,p.city,statusText(p.status)].some(v=>(v||'').toLowerCase().includes(q)));$('#participantTable').innerHTML=`<div class="table-wrap"><table class="table"><thead><tr><th>Участник</th><th>Клуб</th><th>Город</th><th>Статус</th><th></th></tr></thead><tbody>${rows.map(p=>`<tr class="${p.status==='withdrawn'?'row-muted':''}"><td><b>${esc(p.name)}</b></td><td>${esc(p.club||'—')}</td><td>${esc(p.city||'—')}</td><td><span class="pill ${p.status==='withdrawn'?'warn':''}">${esc(statusText(p.status||'active'))}</span></td><td class="actions"><button class="small" data-edit-p="${p.id}">Ред.</button><button class="small ${p.status==='withdrawn'?'':'warning-btn'}" data-status-p="${p.id}" data-next-status="${p.status==='withdrawn'?'active':'withdrawn'}">${p.status==='withdrawn'?'Вернуть':'Выбыл'}</button><button class="small danger ghost" data-del-p="${p.id}">Удалить</button></td></tr>`).join('')||'<tr><td colspan="5" class="muted">Ничего не найдено</td></tr>'}</tbody></table></div>`; bindParticipantRows();};
  const bindParticipantRows=()=>{
    $$('[data-edit-p]').forEach(b=>b.onclick=()=>editParticipant(Number(b.dataset.editP)));
    $$('[data-status-p]').forEach(b=>b.onclick=async()=>{const next=b.dataset.nextStatus;const text=next==='withdrawn'?'Отметить участника как «Выбыл»? Будущие уже сформированные бои с определенным соперником будут закрыты как выбытие.':'Вернуть участника в активные? Автоматически завершенные из-за выбытия бои не будут отменены.';if(!confirm(text))return;try{await api(`/api/participants/${b.dataset.statusP}/status`,{method:'POST',body:JSON.stringify({status:next})});await refreshAdminData();renderParticipants();toast(next==='withdrawn'?'Участник выбыл':'Участник возвращен')}catch(e){toast(e.message,true)}});
    $$('[data-del-p]').forEach(b=>b.onclick=async()=>{if(!confirm('Удалить участника?'))return;try{await api(`/api/participants/${b.dataset.delP}`,{method:'DELETE'});await refreshAdminData();renderParticipants()}catch(e){toast(e.message,true)}});
  };
  draw(); $('#participantSearch').oninput=e=>draw(e.target.value);
  $('#exportParticipantsCsv').onclick=()=>downloadUrl(`/api/tournaments/${adminState.tournamentId}/participants/export.csv`);
  $('#exportParticipantsJson').onclick=()=>downloadUrl(`/api/tournaments/${adminState.tournamentId}/participants/export.json`);
  $('#importParticipantsBtn').onclick=()=>$('#importParticipantsFile').click();
  $('#importParticipantsFile').onchange=async e=>{const file=e.target.files?.[0];if(!file)return;try{const content=await file.text();const r=await api(`/api/tournaments/${adminState.tournamentId}/participants/import`,{method:'POST',body:JSON.stringify({filename:file.name,content})});await refreshAdminData();renderParticipants();toast(`Импорт: добавлено ${r.created}, обновлено ${r.updated}, пропущено ${r.skipped}`)}catch(err){toast(err.message,true)}};
  $('#participantForm').onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target);try{await api(`/api/tournaments/${adminState.tournamentId}/participants`,{method:'POST',body:JSON.stringify(Object.fromEntries(fd))});e.target.reset();await refreshAdminData();renderParticipants()}catch(err){toast(err.message,true)}};
}

async function editParticipant(id){
  const p=adminState.participants.find(x=>x.id===id); if(!p)return;
  const last=prompt('Фамилия:',p.last_name); if(last===null)return;
  const first=prompt('Имя:',p.first_name||''); if(first===null)return;
  const club=prompt('Клуб / школа:',p.club||''); if(club===null)return;
  const city=prompt('Город:',p.city||''); if(city===null)return;
  try{await api(`/api/participants/${id}`,{method:'PUT',body:JSON.stringify({last_name:last,first_name:first,club,city})});await refreshAdminData();renderParticipants();toast('Карточка участника обновлена')}catch(e){toast(e.message,true)}
}
function renderSchedule(){
  const s=adminState.schedule||{areas:[],unassigned:[],settings:{avoid_consecutive_matches:true,preferred_match_gap:1}}; const auto=adminState.areas.length===1;
  const cfg=s.settings||{avoid_consecutive_matches:true,preferred_match_gap:1};
  const repeatWarnings=(s.areas||[]).reduce((n,col)=>n+col.matches.filter(m=>m.repeat_warning).length,0);
  $('#adminContent').innerHTML=`<div class="section-head"><div><h2>Расписание площадок</h2><p>Перетаскивайте готовые бои между площадками и меняйте их порядок.</p></div><div class="row">${auto?'<span class="pill live-pill">Автоназначение включено</span>':''}<button id="addArea">+ Добавить площадку</button></div></div>
  <div class="card schedule-settings"><div><b>Порядок боёв</b><small>Генератор старается не ставить одного спортсмена на несколько боёв подряд. Ограничение мягкое: при отсутствии альтернатив очередь не блокируется.</small></div><label class="check-row"><input id="avoidConsecutive" type="checkbox" ${cfg.avoid_consecutive_matches?'checked':''}> Разносить повторные выходы</label><label class="field compact-field"><span>Других боёв между выходами</span><input id="preferredGap" type="number" min="1" max="10" value="${cfg.preferred_match_gap||1}" ${cfg.avoid_consecutive_matches?'':'disabled'}></label><button id="saveScheduleSettings">Сохранить</button><button id="optimizeSchedule" ${cfg.avoid_consecutive_matches?'':'disabled'}>Оптимизировать текущую очередь</button>${repeatWarnings?`<span class="schedule-warning">⚠ Неизбежных близких выходов: ${repeatWarnings}</span>`:'<span class="muted">Повторные выходы в текущей очереди разведены.</span>'}</div>
  <div class="schedule"><div class="schedule-col unassigned" data-area=""><div class="schedule-head"><h3>Не назначены</h3><span>${s.unassigned.length}</span></div>${s.unassigned.map(scheduleChip).join('')||'<div class="schedule-empty">Нет готовых боёв</div>'}</div>${s.areas.map(col=>`<div class="schedule-col" data-area="${col.area.id}"><div class="schedule-head"><h3>${esc(col.area.name)}</h3><span>${col.matches.length}</span></div>${col.matches.map(m=>scheduleChip(m,col.area.current_match_id)).join('')||'<div class="schedule-empty">Очередь пуста</div>'}</div>`).join('')}</div>`;
  $('#avoidConsecutive').onchange=e=>{$('#preferredGap').disabled=!e.target.checked;$('#optimizeSchedule').disabled=!e.target.checked};
  $('#saveScheduleSettings').onclick=async()=>{try{await api(`/api/tournaments/${adminState.tournamentId}/schedule-settings`,{method:'PUT',body:JSON.stringify({avoid_consecutive_matches:$('#avoidConsecutive').checked,preferred_match_gap:Number($('#preferredGap').value)||1})});await refreshAdminData(true);renderSchedule();toast('Настройки порядка боёв сохранены')}catch(e){toast(e.message,true)}};
  $('#optimizeSchedule').onclick=async()=>{try{const r=await api(`/api/tournaments/${adminState.tournamentId}/schedule-optimize`,{method:'POST'});await refreshAdminData(true);renderSchedule();toast(r.unavoidable_conflicts?`Очередь оптимизирована. Близких повторных выходов, которых нельзя избежать: ${r.unavoidable_conflicts}`:'Очередь оптимизирована: повторные выходы разведены')}catch(e){toast(e.message,true)}};
  $('#addArea').onclick=async()=>{const name=prompt('Название площадки:',`Площадка ${adminState.areas.length+1}`);if(!name)return;try{await api(`/api/tournaments/${adminState.tournamentId}/areas`,{method:'POST',body:JSON.stringify({name})});await refreshAdminData(true);renderSchedule()}catch(e){toast(e.message,true)}};
  bindScheduleDnD();
  $$('[data-select-match]').forEach(b=>b.onclick=async()=>{try{await api(`/api/areas/${b.dataset.area}/select/${b.dataset.selectMatch}`,{method:'POST'});await refreshAdminData(true);renderSchedule()}catch(e){toast(e.message,true)}});
}
function scheduleChip(m,currentId){return `<div class="match-chip drag ${m.id===currentId?'current':''} ${m.repeat_warning?'repeat-risk':''}" draggable="true" data-match="${m.id}" data-match-area="${m.area_id||''}"><div class="match-chip-title"><b>#${m.match_no} · ${esc(m.category_name)}</b><span class="pill">${esc(statusText(m.status))}</span></div><div class="match-pair"><span class="red-dot"></span>${esc(fighterText(m.red))}</div><div class="match-pair"><span class="blue-dot"></span>${esc(fighterText(m.blue))}</div>${m.repeat_warning?'<small class="repeat-note">⚠ Повторный выход близко к предыдущему</small>':''}${m.area_id?`<button class="small" data-select-match="${m.id}" data-area="${m.area_id}">${m.id===currentId?'На табло':'Показать на табло'}</button>`:''}</div>`;}
function bindScheduleDnD(){
  let draggedId=null, sourceArea='';
  $$('[data-match]').forEach(el=>{el.ondragstart=e=>{draggedId=Number(el.dataset.match);sourceArea=el.dataset.matchArea||'';e.dataTransfer.setData('text/plain',String(draggedId));};el.ondragover=e=>e.preventDefault();el.ondrop=async e=>{e.preventDefault();e.stopPropagation();const targetArea=el.closest('[data-area]').dataset.area;await handleScheduleDrop(draggedId,sourceArea,targetArea,el);};});
  $$('[data-area]').forEach(col=>{col.ondragover=e=>{e.preventDefault();col.classList.add('drop-target')};col.ondragleave=()=>col.classList.remove('drop-target');col.ondrop=async e=>{col.classList.remove('drop-target');if(e.target.closest('[data-match]'))return;e.preventDefault();await handleScheduleDrop(draggedId,sourceArea,col.dataset.area,null);};});
}
async function handleScheduleDrop(matchId,sourceArea,targetArea,beforeEl){
  if(!matchId)return;
  try{
    if(!targetArea){await api('/api/schedule/assign',{method:'POST',body:JSON.stringify({match_id:matchId,area_id:null})});}
    else if(String(sourceArea)!==String(targetArea)){await api('/api/schedule/assign',{method:'POST',body:JSON.stringify({match_id:matchId,area_id:Number(targetArea)})});}
    await refreshAdminData(true);
    if(targetArea){const col=adminState.schedule.areas.find(x=>String(x.area.id)===String(targetArea));let ids=(col?.matches||[]).map(m=>m.id).filter(id=>id!==matchId);if(beforeEl){const before=Number(beforeEl.dataset.match);const idx=ids.indexOf(before);ids.splice(idx<0?ids.length:idx,0,matchId);}else ids.push(matchId);await api(`/api/areas/${targetArea}/queue`,{method:'PUT',body:JSON.stringify({match_ids:ids})});await refreshAdminData(true);}
    renderSchedule();
  }catch(e){toast(e.message,true);await refreshAdminData(true);renderSchedule()}
}
async function renderNetwork(){
  const root=$('#adminContent');
  root.innerHTML=`<div class="grid grid2 admin-two"><section class="card"><div class="card-title"><h2>Сетевой доступ</h2><span>Адреса автоматически определяются по активным IPv4-интерфейсам главного компьютера.</span></div><div id="networkInterfaces" class="stack"><div class="muted">Определение адресов…</div></div></section><section class="card"><div class="card-title"><h2>Подключенные экраны</h2><span>Показываются активные WebSocket-соединения браузеров.</span></div><div id="networkClients"><div class="muted">Загрузка…</div></div></section></div>`;
  try{
    const r=await api('/api/system/runtime'); adminState.runtime=r;
    const firstArea=adminState.areas[0];
    const ifaces=(r.interfaces||[]).map(x=>{const base=x.base_url;const links=[['Организатор',`${base}/admin`],adminState.tournamentId?['Общий экран',`${base}/public/${adminState.tournamentId}`]:null,firstArea?['Секретарь',`${base}/mat/${firstArea.id}`]:null,firstArea?['Табло площадки',`${base}/board/${firstArea.id}`]:null].filter(Boolean);return `<div class="network-interface network-interface-rich"><div><b>${esc(x.name)}</b><small>${esc(x.ip)}${x.netmask?` · ${esc(x.netmask)}`:''}</small></div><div class="network-route-list">${links.map(([label,url])=>`<div><span>${esc(label)}</span><code>${esc(url)}</code><button class="small" data-copy-url="${esc(url)}">Копировать</button></div>`).join('')}</div></div>`}).join('')||'<div class="muted">Активный LAN IPv4-адрес не найден. Проверьте Wi-Fi/Ethernet и настройки брандмауэра Windows.</div>';
    $('#networkInterfaces').innerHTML=`<div class="network-interface local"><div><b>Этот компьютер</b><small>Доступ только локально</small></div><div class="network-links"><code>${esc(r.local_url)}</code><button class="small" data-copy-url="${esc(r.local_url)}">Копировать</button></div></div>${ifaces}<div class="network-help">На другом компьютере откройте один из LAN-адресов выше. Например: <code>/admin</code>, <code>/mat/1</code>, <code>/board/1</code> или общий экран из вкладки «Экраны».</div>`;
    $$('[data-copy-url]').forEach(b=>b.onclick=async()=>{try{await navigator.clipboard.writeText(b.dataset.copyUrl);toast('Адрес скопирован')}catch{toast(b.dataset.copyUrl)}});
    const areaNames=Object.fromEntries(adminState.areas.map(a=>[a.id,a.name]));
    const screenName={organizer:'Организатор',secretary:'Секретарь площадки',board:'Табло площадки',public:'Общий экран',unknown:'Неизвестный экран'};
    const clients=r.clients||[];
    $('#networkClients').innerHTML=clients.length?`<div class="network-count">Сейчас подключено: <b>${clients.length}</b></div><div class="table-wrap"><table class="table"><thead><tr><th>IP</th><th>Экран</th><th>Площадка</th><th>Подключен</th></tr></thead><tbody>${clients.map(c=>`<tr><td><code>${esc(c.ip||'—')}</code></td><td>${esc(screenName[c.screen]||c.screen||'—')}</td><td>${esc(areaNames[c.area_id]||'—')}</td><td>${esc(formatConnectedAt(c.connected_at))}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-network"><b>Других активных экранов сейчас нет</b><span>Откройте секретаря, табло или общий экран — они появятся здесь автоматически.</span></div>';
  }catch(e){root.innerHTML=`<section class="card"><h2>Сеть</h2><p class="error-text">${esc(e.message)}</p></section>`}
}
function formatConnectedAt(value){if(!value)return '—';try{return new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return value}}

function renderScreens(){
  const base=location.origin;
  $('#adminContent').innerHTML=`<div class="grid grid2 admin-two"><div class="card"><div class="card-title"><h2>Рабочие места площадок</h2><span>Открывайте секретаря на ноутбуке площадки, табло — на втором мониторе/ТВ.</span></div><div class="stack">${adminState.areas.map(a=>`<div class="screen-row"><b class="grow">${esc(a.name)}</b><a class="button-link" href="/mat/${a.id}" target="_blank">Секретарь ↗</a><a class="button-link" href="/board/${a.id}" target="_blank">Табло ↗</a></div>`).join('')}</div></div><div class="card"><div class="card-title"><h2>Общий экран турнира</h2><span>Для участников и зрителей.</span></div><p><a class="button-link primary-link" href="/public/${adminState.tournamentId}" target="_blank">Открыть общий экран ↗</a></p><div class="network-box"><b>Адрес главного компьютера</b><code>${esc(base)}</code><p>На других компьютерах замените localhost/127.0.0.1 на LAN-IP главного ПК, например <code>http://192.168.1.100:8000</code>.</p></div></div></div>`;
}


function formatBytes(value){const n=Number(value)||0;if(n<1024)return `${n} Б`;if(n<1024*1024)return `${(n/1024).toFixed(1)} КБ`;return `${(n/1024/1024).toFixed(1)} МБ`}
async function renderService(){
  $('#adminContent').innerHTML=`<div class="service-grid"><section class="card"><div class="card-title"><h2>Рабочая база данных</h2><span>Переключение действует на сервер и все подключённые экраны.</span></div><div id="databaseManager" class="stack"><div class="muted">Загрузка списка БД…</div></div></section><section class="card"><div class="card-title"><h2>Резервирование и обслуживание</h2><span>Перед очисткой приложение автоматически создает резервную копию SQLite.</span></div><div class="stack"><button id="serviceBackup">Создать резервную копию сейчас</button><div class="danger-zone"><h3>Очистка базы данных</h3><p>Удаляет турниры, участников, площадки, сетки, результаты и журнал. По умолчанию сохранённые шаблоны правил категорий остаются.</p><label class="check-row"><input id="preserveTemplates" type="checkbox" checked> Сохранить шаблоны категорий</label><button id="clearDb" class="danger">Очистить БД…</button></div></div></section></div>`;
  $('#serviceBackup').onclick=async()=>{try{const r=await api('/api/backup',{method:'POST'});toast(`Копия создана: ${r.path}`)}catch(e){toast(e.message,true)}};
  $('#clearDb').onclick=async()=>{const word=prompt('Это удалит все турнирные данные. Для подтверждения введите ОЧИСТИТЬ:','');if(word===null)return;try{const r=await api('/api/maintenance/clear-database',{method:'POST',body:JSON.stringify({confirmation:word,preserve_templates:$('#preserveTemplates').checked})});localStorage.removeItem('tournamentId');await loadAdminBase();renderAdminTab('overview');toast(`База очищена. Резервная копия: ${r.backup_path}`)}catch(e){toast(e.message,true)}};
  try{
    const catalog=await api('/api/databases');
    const rows=catalog.databases||[];
    const options=rows.map(x=>`<option value="${esc(x.path)}" ${x.active?'selected':''}>${esc(x.name)}${x.default?' · стандартная':''} · ${formatBytes(x.size_bytes)}</option>`).join('');
    $('#databaseManager').innerHTML=`<div class="current-db-box"><span>Сейчас используется</span><code>${esc(catalog.active_path||'—')}</code></div><div class="field"><label>Известные базы данных</label><select id="knownDatabase">${options||'<option value="">Нет доступных БД</option>'}</select></div><div class="database-path-row"><div class="field grow"><label>Или путь к SQLite-файлу на компьютере-сервере</label><input id="databasePath" value="${esc(catalog.active_path||'')}" placeholder="C:\\Turnirium\\data\\tournament.db"></div><button id="switchDatabase" class="primary">Переключить БД</button></div><small class="muted">Поддерживаются .db, .sqlite и .sqlite3. Выбранный путь сохраняется и используется при следующем запуске Turnirium. На удалённом компьютере указывайте путь именно на компьютере, где запущен сервер.</small>`;
    const known=$('#knownDatabase'),path=$('#databasePath');
    if(known)known.onchange=()=>{if(known.value)path.value=known.value};
    $('#switchDatabase').onclick=async()=>{
      const target=path.value.trim();
      if(!target){toast('Укажите путь к БД',true);return}
      if(target===catalog.active_path){toast('Эта БД уже используется');return}
      if(!confirm('Переключить рабочую базу данных? Текущие экраны турнира будут сброшены на экран организатора.'))return;
      try{
        const r=await api('/api/databases/select',{method:'POST',body:JSON.stringify({path:target})});
        localStorage.removeItem('tournamentId');adminState.selectedCategoryId=null;
        await loadAdminBase();
        const db=$('#dbInfo');if(db){db.textContent=`БД: ${r.db_path}`;db.title=r.db_path||''}
        renderService();toast('Рабочая БД переключена');
      }catch(e){toast(e.message,true)}
    };
  }catch(e){$('#databaseManager').innerHTML=`<div class="error-text">${esc(e.message)}</div>`}
}

