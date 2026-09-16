const adminUiState = {
  participantExpanded:new Set(),
  participantCategories:new Map(),
  scheduleExpandedGroups:new Set(),
  categoryEditingId:null,
  categoryCreating:false,
};

function resetAdminUiState() {
  adminUiState.participantExpanded.clear();
  adminUiState.participantCategories.clear();
  adminUiState.scheduleExpandedGroups.clear();
  adminUiState.categoryEditingId=null;
  adminUiState.categoryCreating=false;
}

async function initAdmin() {
  document.body.className='admin-page'; ensureBranding();
  $('#app').innerHTML = `
    <header class="admin-header">
      <div class="admin-header-inner">
        <div class="brand">${brandIconHtml()}<div><div class="brand-title">${esc(BRANDING.app_name)}</div><div class="brand-sub">Организатор</div></div></div>
        <div class="connection-pill"><span id="wsDot" class="status-dot"></span><span id="wsText">Подключение…</span></div>
        <span id="dbInfo" class="header-meta"></span>
      </div>
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
  $$('.admin-nav button').forEach(b=>b.onclick=async()=>{ $$('.admin-nav button').forEach(x=>x.classList.remove('active')); b.classList.add('active'); if(b.dataset.tab!=='categories'){adminUiState.categoryCreating=false;adminUiState.categoryEditingId=null;if(!adminState.selectedCategoryId&&adminState.categories.length){const active=adminState.categories.filter(c=>c.status!=='completed');adminState.selectedCategoryId=active[0]?.id||adminState.categories[0].id;await loadSelectedCategory();}} renderAdminTab(b.dataset.tab); });
  await loadAdminBase();
  wsConnect(async e=>{
    if (e.type==='clients_changed'){ if($('.admin-nav button.active')?.dataset.tab==='network') renderNetwork(); return; }
    if (e.type==='database_switched'){
      localStorage.removeItem('tournamentId');
      adminState.selectedCategoryId=null;
      resetAdminUiState();
      await loadAdminBase();
      try{const s=await api('/api/system');const db=$('#dbInfo');if(db){db.textContent=`БД: ${s.db_path}`;db.title=s.db_path||''}}catch{}
      renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview');
      toast('Рабочая база данных переключена');
      return;
    }
    if (!adminState.tournamentId) return;
    if (e.type==='database_cleared'){ resetAdminUiState(); await loadAdminBase(); renderAdminTab('overview'); return; }
    if (e.type==='templates_changed'){ adminState.templates=await api('/api/category-templates'); if($('.admin-nav button.active')?.dataset.tab==='categories'&&!adminUiState.categoryCreating&&adminUiState.categoryEditingId===null)renderCategories(); return; }
    if (e.type==='participant_details_changed' && e.participant){
      const index=adminState.participants.findIndex(item=>item.id===e.participant.id);
      if(index>=0)adminState.participants[index]=e.participant;
      const row=document.querySelector(`[data-participant-row="${e.participant.id}"]`);
      row?.classList.toggle('participant-paid',Boolean(e.participant.fee_paid));
      const paid=document.querySelector(`[data-participant-paid="${e.participant.id}"]`);
      const comment=document.querySelector(`[data-participant-comment="${e.participant.id}"]`);
      if(paid && document.activeElement!==paid)paid.checked=Boolean(e.participant.fee_paid);
      if(comment && document.activeElement!==comment)comment.value=e.participant.comment||'';
      return;
    }
    if (['schedule_changed','areas_changed','match_changed','match_finished','match_corrected','area_changed','timer_changed','timer_finished','bracket_changed','participants_changed','categories_changed','category_changed','tournament_changed'].includes(e.type)) {
      if (['participants_changed','categories_changed','category_changed'].includes(e.type)) adminUiState.participantCategories.clear();
      // Всегда обновляем выбранную категорию: раньше после завершения боя
      // обновлялось только расписание, а сетка оставалась старой до F5.
      await refreshAdminData(true);
      const activeTab=$('.admin-nav button.active')?.dataset.tab||'overview';
      if(activeTab==='categories'&&(adminUiState.categoryCreating||adminUiState.categoryEditingId!==null))return;
      renderAdminTab(activeTab);
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
    <button id="newTournament" class="primary">+ Новый турнир</button>${current?(current.status==='completed'?'<button id="reopenTournament">Вернуть в активные</button>':'<button id="completeTournament">✓ Завершить турнир</button>') : ''}${current?`<button id="exportTournamentPdf">PDF</button><button id="exportTournamentJson">JSON</button>`:''}<button id="backupBtn">Резервная копия</button>${current?.status==='completed'?'<span class="toolbar-hint">Архивный турнир</span>':''}`;
  $('#tournamentSelect').onchange=async e=>{ adminState.tournamentId=Number(e.target.value)||null; resetAdminUiState(); localStorage.setItem('tournamentId',adminState.tournamentId||''); await refreshAdminData(); renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview'); };
  if($('#tournamentArchive')) $('#tournamentArchive').onchange=async e=>{const id=Number(e.target.value);if(!id)return;adminState.tournamentId=id;resetAdminUiState();localStorage.setItem('tournamentId',id);await refreshAdminData();renderTournamentBar();renderAdminTab($('.admin-nav button.active')?.dataset.tab||'overview');};
  $('#newTournament').onclick=async()=>{ const name=prompt('Название турнира:','Новый Турнир'); if(!name)return; try{const r=await api('/api/tournaments',{method:'POST',body:JSON.stringify({name})}); resetAdminUiState(); localStorage.setItem('tournamentId',r.id); await loadAdminBase(); renderAdminTab('overview');}catch(e){toast(e.message,true)} };
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
  if(!adminUiState.categoryCreating&&!adminState.categories.some(c=>c.id===adminState.selectedCategoryId)) adminState.selectedCategoryId=activeCats[0]?.id||adminState.categories[0]?.id||null;
  if(withCategory && adminState.selectedCategoryId) await loadSelectedCategory();
}
async function loadSelectedCategory(){
  if(!adminState.selectedCategoryId){adminState.categoryParticipants=[];adminState.matches=[];return;}
  [adminState.categoryParticipants,adminState.matches]=await Promise.all([api(`/api/categories/${adminState.selectedCategoryId}/participants`),api(`/api/categories/${adminState.selectedCategoryId}/matches`)]);
}
function renderAdminTab(tab){
  const content=$('#adminContent');
  if(content) content.className='';
  if(tab==='network'){renderNetwork();return;}
  if(tab==='service'){renderService();return;}
  if(!adminState.tournamentId){content.innerHTML=`<section class="empty-state"><div class="empty-icon">🏆</div><h2>Создайте первый турнир</h2><p>Будет создана площадка №1. Затем добавьте участников и категории.</p></section>`;return;}
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
    <div class="section-head"><div><h2>Состояние площадок</h2></div><span class="pill ${live?'live-pill':''}">${live?`Сейчас идут: ${live}`:'Нет активных боёв'}</span></div>
    <div class="area-dashboard">${(adminState.schedule?.areas||[]).map(col=>{
      const current=col.matches.find(m=>m.id===col.area.current_match_id); const next=col.matches.find(m=>m.id!==col.area.current_match_id && ['ready','pending'].includes(m.status));
      return `<article class="area-card"><div class="area-card-head"><h3>${esc(col.area.name)}</h3><div class="quick-links"><a href="/mat/${col.area.id}" target="_blank">Секретарь ↗</a><a href="/board/${col.area.id}" target="_blank">Табло ↗</a></div></div>
        ${current?`<div class="current-fight"><span class="eyebrow">Текущий бой</span><b>${esc(current.red?.name||'—')} — ${esc(current.blue?.name||'—')}</b><small>${esc(current.category_name)} · ${fmtTime(current.remaining_ms)} · ${current.red_score}:${current.blue_score}</small></div>`:`<div class="current-fight idle"><span>Площадка свободна</span></div>`}
        <div class="next-fight"><span>Следующий</span><b>${next?`${esc(next.red?.name||'—')} — ${esc(next.blue?.name||'—')}`:'—'}</b></div></article>`;
    }).join('')||'<div class="card">Нет площадок.</div>'}</div>
    `;
}
function participantCategoriesHtml(categories) {
  if (!categories.length) {
    return '<div class="participant-category-empty">Участник пока не заявлен ни в одну категорию.</div>';
  }
  return `<div class="participant-category-list">${categories.map(category => `
    <div class="participant-category-item">
      <div>
        <b>${esc(category.name)}</b>
        <small>${esc(formatName(category.format))}${category.group_name ? ` · Группа ${esc(category.group_name)}` : ''}</small>
      </div>
      <div class="participant-category-state">
        ${category.disqualified ? '<span class="pill warn">DSQ</span>' : ''}
        <span class="pill ${category.status === 'completed' ? 'muted-pill' : ''}">${category.status === 'completed' ? 'Завершена' : 'Участвует'}</span>
      </div>
    </div>`).join('')}</div>`;
}

function participantExtraHtml(participant, categories) {
  return `<div class="participant-extra-grid">
    <section class="participant-extra-section">
      <div class="participant-extra-title">Категории</div>
      ${participantCategoriesHtml(categories)}
    </section>
    <section class="participant-extra-section participant-admin-note">
      <div class="participant-extra-title">Организационные данные</div>
      <label class="participant-paid-control">
        <input type="checkbox" data-participant-paid="${participant.id}" ${participant.fee_paid ? 'checked' : ''}>
        <span>Сдал взнос</span>
      </label>
      <label class="field participant-comment-field">
        <span>Комментарий</span>
        <textarea data-participant-comment="${participant.id}" maxlength="4000" placeholder="Произвольная заметка организатора">${esc(participant.comment || '')}</textarea>
      </label>
      <div class="participant-note-actions">
        <span class="muted" data-participant-note-status="${participant.id}"></span>
        <button type="button" class="small primary" data-save-participant-details="${participant.id}">Сохранить</button>
      </div>
    </section>
  </div>`;
}

async function saveParticipantDetails(participantId) {
  const paid = document.querySelector(`[data-participant-paid="${participantId}"]`);
  const comment = document.querySelector(`[data-participant-comment="${participantId}"]`);
  const status = document.querySelector(`[data-participant-note-status="${participantId}"]`);
  if (!paid || !comment) return;
  if (status) status.textContent = 'Сохранение…';
  try {
    const updated = await api(`/api/participants/${participantId}/details`, {
      method:'PUT',
      body:JSON.stringify({fee_paid:paid.checked, comment:comment.value}),
    });
    const index = adminState.participants.findIndex(item => item.id === participantId);
    if (index >= 0) adminState.participants[index] = updated;
    if (status) status.textContent = 'Сохранено';
    const mainRow = document.querySelector(`[data-participant-row="${participantId}"]`);
    mainRow?.classList.toggle('participant-paid', Boolean(updated.fee_paid));
  } catch (error) {
    if (status) status.textContent = '';
    toast(error.message, true);
  }
}

async function loadParticipantExtra(participantId) {
  const participant = adminState.participants.find(item => item.id === participantId);
  const row = document.querySelector(`[data-participant-category-row="${participantId}"]`);
  const body = row?.querySelector('[data-participant-category-body]');
  if (!participant || !row || !body) return;

  const cached = adminUiState.participantCategories.get(participantId);
  if (cached) {
    body.innerHTML = participantExtraHtml(participant, cached);
    row.dataset.loaded = '1';
  } else {
    body.innerHTML = '<div class="muted">Загрузка…</div>';
    try {
      const categories = await api(`/api/participants/${participantId}/categories`);
      adminUiState.participantCategories.set(participantId, categories);
      const currentRow = document.querySelector(`[data-participant-category-row="${participantId}"]`);
      const currentBody = currentRow?.querySelector('[data-participant-category-body]');
      if (!currentRow || !currentBody) return;
      currentBody.innerHTML = participantExtraHtml(participant, categories);
      currentRow.dataset.loaded = '1';
    } catch (error) {
      const currentBody = document.querySelector(`[data-participant-category-row="${participantId}"] [data-participant-category-body]`);
      if (currentBody) currentBody.innerHTML = `<div class="error-text">${esc(error.message)}</div>`;
      return;
    }
  }
  const currentBody = document.querySelector(`[data-participant-category-row="${participantId}"] [data-participant-category-body]`);
  currentBody?.querySelector(`[data-save-participant-details="${participantId}"]`)?.addEventListener('click', () => saveParticipantDetails(participantId));
  const paid = currentBody?.querySelector(`[data-participant-paid="${participantId}"]`);
  if (paid) paid.onchange = () => saveParticipantDetails(participantId);
}

async function toggleParticipantCategories(button) {
  const participantId = Number(button.dataset.participantCategories);
  const participant = adminState.participants.find(item => item.id === participantId);
  const row = document.querySelector(`[data-participant-category-row="${participantId}"]`);
  if (!row || !participant) return;
  const opening = row.hidden;
  row.hidden = !opening;
  button.classList.toggle('open', opening);
  button.setAttribute('aria-expanded', opening ? 'true' : 'false');
  if (opening) {
    adminUiState.participantExpanded.add(participantId);
    await loadParticipantExtra(participantId);
  } else {
    adminUiState.participantExpanded.delete(participantId);
  }
}

function participantTableHtml(rows) {
  if (!rows.length) return '<tr><td colspan="5" class="muted">Ничего не найдено</td></tr>';
  return rows.map(participant => {
    const rowClasses = [
      participant.status === 'withdrawn' ? 'row-muted' : '',
      participant.fee_paid ? 'participant-paid' : '',
    ].filter(Boolean).join(' ');
    const expanded = adminUiState.participantExpanded.has(participant.id);
    return `<tr class="${rowClasses}" data-participant-row="${participant.id}">
      <td><div class="participant-name-cell"><button type="button" class="participant-chevron ${expanded ? 'open' : ''}" data-participant-categories="${participant.id}" aria-expanded="${expanded ? 'true' : 'false'}" title="Категории и заметки"><span aria-hidden="true"></span></button><b>${esc(participant.name)}</b></div></td>
      <td>${esc(participant.club || '—')}</td>
      <td>${esc(participant.city || '—')}</td>
      <td><span class="pill ${participant.status === 'withdrawn' ? 'warn' : ''}">${esc(statusText(participant.status || 'active'))}</span></td>
      <td class="actions"><button class="small" data-edit-p="${participant.id}">Ред.</button><button class="small ${participant.status === 'withdrawn' ? '' : 'warning-btn'}" data-status-p="${participant.id}" data-next-status="${participant.status === 'withdrawn' ? 'active' : 'withdrawn'}">${participant.status === 'withdrawn' ? 'Вернуть' : 'Выбыл'}</button><button class="small danger ghost" data-del-p="${participant.id}">Удалить</button></td>
    </tr>
    <tr class="participant-category-row" data-participant-category-row="${participant.id}" ${expanded ? '' : 'hidden'}><td colspan="5"><div class="participant-category-body" data-participant-category-body>${expanded ? '<div class="muted">Загрузка…</div>' : ''}</div></td></tr>`;
  }).join('');
}

function bindParticipantRows() {
  $$('[data-participant-categories]').forEach(button => {
    button.onclick = () => toggleParticipantCategories(button);
    if (adminUiState.participantExpanded.has(Number(button.dataset.participantCategories))) loadParticipantExtra(Number(button.dataset.participantCategories));
  });
  $$('[data-edit-p]').forEach(button => button.onclick = () => editParticipant(Number(button.dataset.editP)));
  $$('[data-status-p]').forEach(button => button.onclick = async () => {
    const next = button.dataset.nextStatus;
    const text = next === 'withdrawn'
      ? 'Отметить участника как «Выбыл»? Будущие уже сформированные бои с определенным соперником будут закрыты как выбытие.'
      : 'Вернуть участника в активные? Автоматически завершенные из-за выбытия бои не будут отменены.';
    if (!confirm(text)) return;
    try {
      await api(`/api/participants/${button.dataset.statusP}/status`, {method:'POST', body:JSON.stringify({status:next})});
      await refreshAdminData();
      renderParticipants();
      toast(next === 'withdrawn' ? 'Участник выбыл' : 'Участник возвращен');
    } catch (error) { toast(error.message, true); }
  });
  $$('[data-del-p]').forEach(button => button.onclick = async () => {
    if (!confirm('Удалить участника?')) return;
    try {
      const participantId = Number(button.dataset.delP);
      await api(`/api/participants/${participantId}`, {method:'DELETE'});
      adminUiState.participantExpanded.delete(participantId);
      adminUiState.participantCategories.delete(participantId);
      await refreshAdminData();
      renderParticipants();
    } catch (error) { toast(error.message, true); }
  });
}

function renderParticipants() {
  $('#adminContent').innerHTML = `<div class="participant-workspace"><div class="card form-card participant-create-card"><div class="card-title"><h2>Новый участник</h2><span>Карточка спортсмена</span></div><form id="participantForm" class="stack">
    <div class="row"><div class="field grow"><label>Фамилия</label><input name="last_name" placeholder="Иванова" required></div><div class="field grow"><label>Имя</label><input name="first_name" placeholder="Анна"></div></div>
    <div class="row"><div class="field grow"><label>Клуб / школа</label><input name="club" placeholder="Клуб"></div><div class="field grow"><label>Город</label><input name="city" placeholder="Москва"></div></div><button class="primary">Добавить участника</button></form></div>
    <div class="card"><div class="card-title row"><div class="grow"><h2>Участники · ${adminState.participants.length}</h2><span>Категории и заметки — по стрелке.</span></div><input id="participantSearch" class="search" placeholder="Поиск…"></div><div class="participant-tools"><button id="exportParticipantsCsv">Экспорт CSV</button><button id="exportParticipantsJson">Экспорт JSON</button><button id="importParticipantsBtn" class="primary">Импорт списка</button><input id="importParticipantsFile" type="file" accept=".csv,.json,text/csv,application/json" hidden></div><div id="participantTable"></div></div></div>`;

  const draw = (query='') => {
    const normalized = query.trim().toLowerCase();
    const rows = adminState.participants.filter(participant => !normalized || [
      participant.name,
      participant.club,
      participant.city,
      participant.comment,
      statusText(participant.status),
    ].some(value => (value || '').toLowerCase().includes(normalized)));
    $('#participantTable').innerHTML = `<div class="table-wrap"><table class="table participant-table"><thead><tr><th>Участник</th><th>Клуб</th><th>Город</th><th>Статус</th><th></th></tr></thead><tbody>${participantTableHtml(rows)}</tbody></table></div>`;
    bindParticipantRows();
  };

  draw();
  $('#participantSearch').oninput = event => draw(event.target.value);
  $('#exportParticipantsCsv').onclick = () => downloadUrl(`/api/tournaments/${adminState.tournamentId}/participants/export.csv`);
  $('#exportParticipantsJson').onclick = () => downloadUrl(`/api/tournaments/${adminState.tournamentId}/participants/export.json`);
  $('#importParticipantsBtn').onclick = () => $('#importParticipantsFile').click();
  $('#importParticipantsFile').onchange = async event => {
    const file = event.target.files?.[0];
    if (!file) return;
    try {
      const content = await file.text();
      const result = await api(`/api/tournaments/${adminState.tournamentId}/participants/import`, {method:'POST', body:JSON.stringify({filename:file.name, content})});
      await refreshAdminData();
      renderParticipants();
      toast(`Импорт: добавлено ${result.created}, обновлено ${result.updated}, пропущено ${result.skipped}`);
    } catch (error) { toast(error.message, true); }
  };
  $('#participantForm').onsubmit = async event => {
    event.preventDefault();
    const form = new FormData(event.target);
    try {
      await api(`/api/tournaments/${adminState.tournamentId}/participants`, {method:'POST', body:JSON.stringify(Object.fromEntries(form))});
      event.target.reset();
      await refreshAdminData();
      renderParticipants();
    } catch (error) { toast(error.message, true); }
  };
}

async function editParticipant(id){
  const p=adminState.participants.find(x=>x.id===id); if(!p)return;
  const last=prompt('Фамилия:',p.last_name); if(last===null)return;
  const first=prompt('Имя:',p.first_name||''); if(first===null)return;
  const club=prompt('Клуб / школа:',p.club||''); if(club===null)return;
  const city=prompt('Город:',p.city||''); if(city===null)return;
  try{await api(`/api/participants/${id}`,{method:'PUT',body:JSON.stringify({last_name:last,first_name:first,club,city})});await refreshAdminData();renderParticipants();toast('Карточка участника обновлена')}catch(e){toast(e.message,true)}
}
async function renderNetwork(){
  const root=$('#adminContent');
  root.innerHTML=`<div class="grid grid2 admin-two"><section class="card"><div class="card-title"><h2>Сетевой доступ</h2><span>Адреса этого компьютера в локальной сети.</span></div><div id="networkInterfaces" class="stack"><div class="muted">Определение адресов…</div></div></section><section class="card"><div class="card-title"><h2>Подключенные экраны</h2><span>Активные подключения.</span></div><div id="networkClients"><div class="muted">Загрузка…</div></div></section></div>`;
  try{
    const r=await api('/api/system/runtime'); adminState.runtime=r;
    const firstArea=adminState.areas[0];
    const ifaces=(r.interfaces||[]).map(x=>{const base=x.base_url;const links=[['Организатор',`${base}/admin`],adminState.tournamentId?['Общий экран',`${base}/public/${adminState.tournamentId}`]:null,firstArea?['Секретарь',`${base}/mat/${firstArea.id}`]:null,firstArea?['Табло площадки',`${base}/board/${firstArea.id}`]:null].filter(Boolean);return `<div class="network-interface network-interface-rich"><div><b>${esc(x.name)}</b><small>${esc(x.ip)}${x.netmask?` · ${esc(x.netmask)}`:''}</small></div><div class="network-route-list">${links.map(([label,url])=>`<div><span>${esc(label)}</span><code>${esc(url)}</code><button class="small" data-copy-url="${esc(url)}">Копировать</button></div>`).join('')}</div></div>`}).join('')||'<div class="muted">Активный LAN IPv4-адрес не найден. Проверьте Wi-Fi/Ethernet и настройки брандмауэра Windows.</div>';
    $('#networkInterfaces').innerHTML=`<div class="network-interface local"><div><b>Этот компьютер</b><small>Доступ только локально</small></div><div class="network-links"><code>${esc(r.local_url)}</code><button class="small" data-copy-url="${esc(r.local_url)}">Копировать</button></div></div>${ifaces}`;
    $$('[data-copy-url]').forEach(b=>b.onclick=async()=>{try{await navigator.clipboard.writeText(b.dataset.copyUrl);toast('Адрес скопирован')}catch{toast(b.dataset.copyUrl)}});
    const areaNames=Object.fromEntries(adminState.areas.map(a=>[a.id,a.name]));
    const screenName={organizer:'Организатор',secretary:'Секретарь площадки',board:'Табло площадки',public:'Общий экран',unknown:'Неизвестный экран'};
    const clients=r.clients||[];
    $('#networkClients').innerHTML=clients.length?`<div class="network-count">Сейчас подключено: <b>${clients.length}</b></div><div class="table-wrap"><table class="table"><thead><tr><th>IP</th><th>Экран</th><th>Площадка</th><th>Подключен</th></tr></thead><tbody>${clients.map(c=>`<tr><td><code>${esc(c.ip||'—')}</code></td><td>${esc(screenName[c.screen]||c.screen||'—')}</td><td>${esc(areaNames[c.area_id]||'—')}</td><td>${esc(formatConnectedAt(c.connected_at))}</td></tr>`).join('')}</tbody></table></div>`:'<div class="empty-network"><b>Других активных экранов нет</b></div>';
  }catch(e){root.innerHTML=`<section class="card"><h2>Сеть</h2><p class="error-text">${esc(e.message)}</p></section>`}
}
function formatConnectedAt(value){if(!value)return '—';try{return new Date(value).toLocaleTimeString('ru-RU',{hour:'2-digit',minute:'2-digit',second:'2-digit'})}catch{return value}}

function renderScreens(){
  const base=location.origin;
  $('#adminContent').innerHTML=`<div class="grid grid2 admin-two"><div class="card"><div class="card-title"><h2>Рабочие места площадок</h2><span>Ссылки для рабочих мест.</span></div><div class="stack">${adminState.areas.map(a=>`<div class="screen-row"><b class="grow">${esc(a.name)}</b><a class="button-link" href="/mat/${a.id}" target="_blank">Секретарь ↗</a><a class="button-link" href="/board/${a.id}" target="_blank">Табло ↗</a></div>`).join('')}</div></div><div class="card"><div class="card-title"><h2>Общий экран турнира</h2></div><p><a class="button-link primary-link" href="/public/${adminState.tournamentId}" target="_blank">Открыть общий экран ↗</a></p><div class="network-box"><b>Адрес главного компьютера</b><code>${esc(base)}</code><p>Для других устройств используйте LAN-адрес из вкладки «Сеть».</p></div></div></div>`;
}


function formatBytes(value){const n=Number(value)||0;if(n<1024)return `${n} Б`;if(n<1024*1024)return `${(n/1024).toFixed(1)} КБ`;return `${(n/1024/1024).toFixed(1)} МБ`}
async function renderService(){
  $('#adminContent').innerHTML=`<div class="service-grid"><section class="card"><div class="card-title"><h2>Рабочая база данных</h2><span>Текущий SQLite-файл.</span></div><div id="databaseManager" class="stack"><div class="muted">Загрузка списка БД…</div></div></section><section class="card"><div class="card-title"><h2>Резервирование и обслуживание</h2><span>Резервные копии и очистка.</span></div><div class="stack"><button id="serviceBackup">Создать резервную копию сейчас</button><div class="danger-zone"><h3>Очистка базы данных</h3><p>Удаляет турниры, участников, площадки, сетки, результаты и журнал. По умолчанию сохранённые шаблоны правил категорий остаются.</p><label class="check-row"><input id="preserveTemplates" type="checkbox" checked> Сохранить шаблоны категорий</label><button id="clearDb" class="danger">Очистить БД…</button></div></div></section></div>`;
  $('#serviceBackup').onclick=async()=>{try{const r=await api('/api/backup',{method:'POST'});toast(`Копия создана: ${r.path}`)}catch(e){toast(e.message,true)}};
  $('#clearDb').onclick=async()=>{const word=prompt('Это удалит все турнирные данные. Для подтверждения введите ОЧИСТИТЬ:','');if(word===null)return;try{const r=await api('/api/maintenance/clear-database',{method:'POST',body:JSON.stringify({confirmation:word,preserve_templates:$('#preserveTemplates').checked})});localStorage.removeItem('tournamentId');await loadAdminBase();renderAdminTab('overview');toast(`База очищена. Резервная копия: ${r.backup_path}`)}catch(e){toast(e.message,true)}};
  try{
    const catalog=await api('/api/databases');
    const rows=catalog.databases||[];
    const options=rows.map(x=>`<option value="${esc(x.path)}" ${x.active?'selected':''}>${esc(x.name)}${x.default?' · стандартная':''} · ${formatBytes(x.size_bytes)}</option>`).join('');
    $('#databaseManager').innerHTML=`<div class="current-db-box"><span>Сейчас используется</span><code>${esc(catalog.active_path||'—')}</code></div><div class="field"><label>Известные базы данных</label><select id="knownDatabase">${options||'<option value="">Нет доступных БД</option>'}</select></div><div class="database-path-row"><div class="field grow"><label>Или путь к SQLite-файлу на компьютере-сервере</label><input id="databasePath" value="${esc(catalog.active_path||'')}" placeholder="C:\\Turnirium\\data\\tournament.db"></div><button id="switchDatabase" class="primary">Переключить БД</button></div><small class="muted">Форматы: .db, .sqlite, .sqlite3. Путь указывается на серверном компьютере.</small>`;
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

