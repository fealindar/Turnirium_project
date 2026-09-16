// Интерфейс организатора: категории, сетки, группы и итоговые таблицы.
function categorySelectHtml(){
  const active=adminState.categories.filter(c=>c.status!=='completed'), archived=adminState.categories.filter(c=>c.status==='completed');
  return `<select id="categorySelect"><option value="">—</option>${active.length?`<optgroup label="Активные">${active.map(c=>`<option value="${c.id}" ${c.id===adminState.selectedCategoryId?'selected':''}>${esc(c.name)}</option>`).join('')}</optgroup>`:''}${archived.length?`<optgroup label="Архив">${archived.map(c=>`<option value="${c.id}" ${c.id===adminState.selectedCategoryId?'selected':''}>${esc(c.name)} · завершена</option>`).join('')}</optgroup>`:''}</select>`;
}
function bindCategorySelect(after){const el=$('#categorySelect');if(!el)return;el.onchange=async()=>{adminState.selectedCategoryId=Number(el.value)||null;await loadSelectedCategory();after();};}
function categoryDefaults(){return {name:'',format:'knockout',match_duration_sec:120,timer_warning_sec:10,score_buttons:[{label:'-1',delta:-1},{label:'+1',delta:1},{label:'+2',delta:2},{label:'+3',delta:3}],warning_rules:[{number:1,action:'warning',delta:0},{number:2,action:'score_penalty',delta:-2},{number:3,action:'forfeit',delta:0}],cumulative_warning_limit:4,group_target_size:4,group_qualifiers:2,swiss_rounds:4,win_points:3,draw_points:1};}
function categoryFormatName(fmt){return ({knockout:'Олимпийская',groups:'Группы + плей-офф',swiss:'Швейцарская',round_robin:'Все со всеми'})[fmt]||fmt;}
function selectedCategoryStarted(c){return !!c&&adminState.matches.some(m=>m.status==='in_progress'||(m.status==='finished'&&m.reason!=='BYE'));}
function categoryListHtml(){
  const active=adminState.categories.filter(c=>c.status!=='completed'), archived=adminState.categories.filter(c=>c.status==='completed');
  const row=(c,archivedRow=false)=>`<button type="button" class="category-list-item ${c.id===adminState.selectedCategoryId?'active':''} ${archivedRow?'archived':''}" data-open-category="${c.id}"><span class="category-list-main"><b>${esc(c.name)}</b><small>${esc(categoryFormatName(c.format))}</small></span><span class="category-list-state">${archivedRow?'Архив':'Открыть'}</span></button>`;
  return `<div class="category-list-head"><div><h2>Категории</h2><span>${active.length} активн.</span></div><button type="button" id="newCategoryBtn" class="primary small">+ Новая</button></div><div class="category-list-section"><div class="category-list-label">Активные категории турнира</div><div class="category-list-scroll">${active.map(c=>row(c)).join('')||'<div class="category-list-empty">Активных категорий пока нет.</div>'}</div></div>${archived.length?`<details class="category-archive"><summary>Архив · ${archived.length}</summary><div class="category-list-scroll archived-list">${archived.map(c=>row(c,true)).join('')}</div></details>`:''}`;
}
function templateToolsHtml(prefix,locked=false){
  const opts=adminState.templates.map(t=>`<option value="${t.id}">${esc(t.name)} · ${esc(categoryFormatName(t.format))}</option>`).join('');
  return `<div class="template-inline"><div class="field template-picker"><label>Заполнить правила из шаблона</label><select id="${prefix}TemplateSelect"><option value="">— выбрать шаблон —</option>${opts}</select></div><button type="button" id="${prefix}ApplyTemplate" ${locked?'disabled':''}>Применить</button><button type="button" id="${prefix}DeleteTemplate" class="danger ghost" disabled>Удалить</button></div><div class="template-save-inline"><div><b>Сохранить правила как шаблон</b></div><input id="${prefix}TemplateName" placeholder="Сабля"><button type="button" id="${prefix}SaveTemplate">Сохранить шаблон</button></div>`;
}
function syncTemplateSelect(select,selectedId=0){if(!select)return;select.innerHTML=`<option value="">— выбрать шаблон —</option>${adminState.templates.map(t=>`<option value="${t.id}" ${t.id===selectedId?'selected':''}>${esc(t.name)} · ${esc(categoryFormatName(t.format))}</option>`).join('')}`;}
function bindTemplateTools(prefix,form,base,locked=false){
  const select=$(`#${prefix}TemplateSelect`),apply=$(`#${prefix}ApplyTemplate`),del=$(`#${prefix}DeleteTemplate`),save=$(`#${prefix}SaveTemplate`),name=$(`#${prefix}TemplateName`);
  if(select){select.onchange=()=>{if(del)del.disabled=!select.value;};}
  if(apply)apply.onclick=()=>{if(locked||!select?.value)return;const t=adminState.templates.find(x=>x.id===Number(select.value));if(!t)return;fillCategoryForm(form,t,true);toast(`Шаблон «${t.name}» применён к форме`);};
  if(del)del.onclick=async()=>{const id=Number(select?.value)||0;if(!id)return;const t=adminState.templates.find(x=>x.id===id);if(!confirm(`Удалить шаблон «${t?.name||''}»?`))return;try{await api(`/api/category-templates/${id}`,{method:'DELETE'});adminState.templates=await api('/api/category-templates');syncTemplateSelect(select);del.disabled=true;toast('Шаблон удалён')}catch(e){toast(e.message,true)}};
  if(save)save.onclick=async()=>{const data=categoryFormData(form,base);const templateName=String(name?.value||'').trim()||String(data.name||'').trim();if(!templateName){toast('Введите название категории или название шаблона',true);name?.focus();return;}try{const saved=await api('/api/category-templates',{method:'POST',body:JSON.stringify({...data,name:templateName})});adminState.templates=await api('/api/category-templates');syncTemplateSelect(select,saved.id);if(del)del.disabled=false;if(name)name.value='';toast(`Шаблон «${templateName}» сохранён`)}catch(e){toast(e.message,true)}};
}
function fillCategoryForm(form,source,preserveName=true){
  if(!form||!source)return;const oldName=form.elements.name?.value||'';
  const set=(name,value)=>{const el=form.elements[name];if(el)el.value=value??'';};
  set('format',source.format);set('match_duration_sec',source.match_duration_sec);set('timer_warning_sec',source.timer_warning_sec);set('score_buttons',scoreButtonsText(source.score_buttons||[]));set('warning_rules',warningRulesText(source.warning_rules||[]));set('cumulative_warning_limit',source.cumulative_warning_limit);set('group_target_size',source.group_target_size);set('group_qualifiers',source.group_qualifiers);set('swiss_rounds',source.swiss_rounds);set('win_points',source.win_points??3);set('draw_points',source.draw_points??1);if(!preserveName)set('name',source.name||'');else set('name',oldName);form.elements.format?.dispatchEvent(new Event('change'));
}
function categorySummaryHtml(c,locked){
  const status=c.status==='completed'?'Архив':locked?'Правила зафиксированы':'Активна';
  const editLabel=c.status==='completed'?'Просмотреть правила':'Редактировать правила';
  return `<div class="card category-summary"><div class="category-summary-main"><div><span class="eyebrow">Выбрана категория</span><h2>${esc(c.name)}</h2><p>${esc(categoryFormatName(c.format))} · ${adminState.categoryParticipants.length} участников</p></div><span class="pill ${locked?'warn':'live-pill'}">${status}</span></div><div class="category-summary-actions"><button type="button" id="editCategoryRules">${editLabel}</button>${c.status==='completed'?'<button id="reopenCategory">Вернуть в активные</button>':'<button id="completeCategory">✓ Завершить категорию</button>'}<button id="exportCategoryPdf">PDF результатов</button><button id="exportCategoryJson">JSON</button></div></div>`;
}
function categoryEditorHtml(c,locked){
  return `<div class="card category-editor" id="categoryRulesEditor"><div class="category-editor-head"><div><span class="eyebrow">Редактирование</span><h2>Правила категории</h2><p>${locked?(c.status==='completed'?'Категория завершена. Правила доступны только для просмотра.':'После первого боя спортивные правила зафиксированы. Название категории можно изменить.'):'Изменения правил доступны до первого боя.'}</p></div><button type="button" id="closeCategoryEditor" class="ghost">Закрыть</button></div>${templateToolsHtml('edit',locked)}${categoryFormHtml(c,'editCatForm',locked,locked?'Сохранить название':'Сохранить изменения')}</div>`;
}
function renderCategories(){
  const c=adminState.categories.find(x=>x.id===adminState.selectedCategoryId)||null;
  const locked=!!c&&(c.status==='completed'||selectedCategoryStarted(c));
  const creating=!c;
  if(c && adminUiState.categoryEditingId!==c.id) adminUiState.categoryEditingId=null;
  const editing=!!c&&adminUiState.categoryEditingId===c.id;
  const main=creating
    ? `<div class="card category-editor category-create-editor"><div class="category-editor-head"><div><span class="eyebrow">Создание</span><h2>Новая категория</h2><p>Задайте правила и сохраните категорию. После создания основной экран будет показывать состав участников.</p></div></div>${templateToolsHtml('create',false)}${categoryFormHtml(categoryDefaults(),'createCatForm',false,'Создать категорию')}</div>`
    : `${categorySummaryHtml(c,locked)}${editing?categoryEditorHtml(c,locked):''}${categoryParticipantsHtml(c,locked)}`;
  $('#adminContent').innerHTML=`<div class="category-workspace"><aside class="card category-sidebar">${categoryListHtml()}</aside><section class="category-main">${main}</section></div>`;
  $$('[data-open-category]').forEach(b=>b.onclick=async()=>{adminUiState.categoryCreating=false;adminUiState.categoryEditingId=null;adminState.selectedCategoryId=Number(b.dataset.openCategory);await loadSelectedCategory();renderCategories();});
  $('#newCategoryBtn').onclick=()=>{adminUiState.categoryCreating=true;adminUiState.categoryEditingId=null;adminState.selectedCategoryId=null;adminState.categoryParticipants=[];adminState.matches=[];renderCategories();};
  if(creating){
    const form=$('#createCatForm');bindCategoryFormatVisibility(form);bindTemplateTools('create',form,categoryDefaults(),false);
    form.onsubmit=async e=>{e.preventDefault();const data=categoryFormData(form,categoryDefaults());try{const created=await api(`/api/tournaments/${adminState.tournamentId}/categories`,{method:'POST',body:JSON.stringify(data)});await refreshAdminData(false);adminState.selectedCategoryId=created.id;adminUiState.categoryCreating=false;adminUiState.categoryEditingId=null;await loadSelectedCategory();renderCategories();toast('Категория создана')}catch(err){toast(err.message,true)}};
    return;
  }
  $('#editCategoryRules').onclick=()=>{adminUiState.categoryEditingId=c.id;renderCategories();requestAnimationFrame(()=>$('#categoryRulesEditor')?.scrollIntoView({behavior:'smooth',block:'nearest'}));};
  if($('#closeCategoryEditor')) $('#closeCategoryEditor').onclick=()=>{adminUiState.categoryEditingId=null;renderCategories();};
  if(editing){
    const form=$('#editCatForm');bindCategoryFormatVisibility(form);bindTemplateTools('edit',form,c,locked);
    form.onsubmit=async e=>{e.preventDefault();const data=categoryFormData(form,c);const structuralChanged=data.format!==c.format||data.group_target_size!==c.group_target_size||data.group_qualifiers!==c.group_qualifiers||data.swiss_rounds!==c.swiss_rounds;if(!locked&&structuralChanged&&adminState.matches.length&&!confirm('Изменение структуры удалит ещё не начатую сетку/туры. Результатов боёв ещё нет, поэтому это безопасно. Продолжить?'))return;try{await api(`/api/categories/${c.id}`,{method:'PUT',body:JSON.stringify(data)});await refreshAdminData(false);await loadSelectedCategory();adminUiState.categoryEditingId=null;renderCategories();toast(locked?'Название категории сохранено':structuralChanged&&adminState.matches.length?'Настройки сохранены. Сформируйте сетку заново.':'Настройки категории сохранены')}catch(err){toast(err.message,true)}};
  }
  if($('#completeCategory')) $('#completeCategory').onclick=async()=>{if(!confirm(`Завершить категорию «${c.name}»? Она исчезнет из активных и останется в архиве.`))return;try{const r=await api(`/api/categories/${c.id}/complete`,{method:'POST'});await refreshAdminData(false);adminState.selectedCategoryId=c.id;adminUiState.categoryEditingId=null;await loadSelectedCategory();renderCategories();if(r.export_error)toast(`Категория завершена, но экспорт не создан: ${r.export_error}`,true);else toast('Категория завершена. PDF и JSON подготовлены.')}catch(e){toast(e.message,true)}};
  if($('#reopenCategory')) $('#reopenCategory').onclick=async()=>{try{await api(`/api/categories/${c.id}/reopen`,{method:'POST'});await refreshAdminData(false);adminState.selectedCategoryId=c.id;adminUiState.categoryEditingId=null;await loadSelectedCategory();renderCategories();toast('Категория возвращена в активные')}catch(e){toast(e.message,true)}};
  $('#exportCategoryPdf').onclick=()=>downloadUrl(`/api/categories/${c.id}/export.pdf`);
  $('#exportCategoryJson').onclick=()=>downloadUrl(`/api/categories/${c.id}/export.json`);
  bindCategoryParticipantControls(c,locked);
  if(!locked) bindSeedDnD(c);
}
function categoryParticipantsHtml(c,locked){
  const available=adminState.participants.filter(p=>p.status!=='withdrawn'&&!adminState.categoryParticipants.some(cp=>cp.participant_id===p.id));
  return `<div class="card category-roster"><div class="category-roster-head"><div><h2>Участники категории</h2><p>${locked?'Состав и посев зафиксированы.':'Можно менять до первого боя.'}</p></div><span class="pill">${adminState.categoryParticipants.length} в категории</span></div><div class="category-roster-columns"><section class="roster-pane"><div class="roster-pane-head"><b>Состав / посев</b><span>${adminState.categoryParticipants.length}</span></div><div id="seedList" class="roster-scroll stack">${adminState.categoryParticipants.map(cp=>`<div class="list-item drag ${cp.participant_status==='withdrawn'?'row-muted':''}" draggable="${!locked}" data-cp="${cp.id}"><span class="drag-handle">${locked?'●':'⋮⋮'}</span><b>${esc(cp.name)}</b><span class="muted grow">${esc(affiliation(cp)||'Без клуба / города')}</span>${cp.participant_status==='withdrawn'?'<span class="pill warn">Выбыл</span>':''}${cp.disqualified?'<span class="pill warn">DSQ</span>':''}</div>`).join('')||'<div class="roster-empty">Участников пока нет.</div>'}</div></section><section class="roster-pane"><div class="roster-pane-head"><b>Добавить участника</b><input id="categoryParticipantSearch" class="search compact-search" placeholder="Поиск…"></div><div id="availableParticipantsList" class="roster-scroll stack">${available.map(p=>categoryAvailableParticipantHtml(p,locked)).join('')||'<div class="roster-empty">Нет доступных участников.</div>'}</div></section></div></div>`;
}
function categoryAvailableParticipantHtml(p,locked){return `<div class="list-item available-participant" data-participant-search="${esc([p.name,p.club,p.city].join(' ').toLowerCase())}"><span class="grow"><b>${esc(p.name)}</b><br><small class="muted">${esc(affiliation(p)||'Без клуба / города')}</small></span><button type="button" class="small" data-enroll="${p.id}" ${locked?'disabled':''}>Добавить</button></div>`;}
function bindCategoryParticipantControls(c,locked){
  const search=$('#categoryParticipantSearch');if(search)search.oninput=()=>{const q=search.value.trim().toLowerCase();$$('[data-participant-search]').forEach(el=>{el.hidden=!!q&&!el.dataset.participantSearch.includes(q);});};
  $$('[data-enroll]').forEach(b=>b.onclick=async()=>{if(locked)return;try{await api(`/api/categories/${c.id}/participants`,{method:'POST',body:JSON.stringify({participant_id:Number(b.dataset.enroll)})});adminState.categoryParticipants=await api(`/api/categories/${c.id}/participants`);renderCategories();toast('Участник добавлен в категорию')}catch(e){toast(e.message,true)}});
}
function categoryFormHtml(c,id,locked=false,submitLabel='Сохранить изменения'){
  c={...categoryDefaults(),...(c||{})};const dis=locked?'disabled':'';const completed=c.status==='completed';
  return `<form id="${id}" class="stack category-rule-form"><section class="category-form-section"><div class="category-form-section-title"><b>Основные параметры</b></div><div class="field"><label>Название категории</label><input name="name" value="${esc(c.name)}" placeholder="Сабля женская" required ${completed?'disabled':''}></div><div class="category-form-grid"><div class="field"><label>Формат</label><select name="format" ${dis}><option value="knockout" ${c.format==='knockout'?'selected':''}>Олимпийская</option><option value="groups" ${c.format==='groups'?'selected':''}>Группы + плей-офф</option><option value="swiss" ${c.format==='swiss'?'selected':''}>Швейцарская</option><option value="round_robin" ${c.format==='round_robin'?'selected':''}>Все со всеми</option></select></div><div class="field"><label>Длительность боя, сек.</label><input name="match_duration_sec" type="number" min="10" value="${c.match_duration_sec}" ${dis}></div><div class="field"><label>Предупредительный сигнал, сек.</label><input name="timer_warning_sec" type="number" min="0" value="${c.timer_warning_sec}" ${dis}></div></div></section><section class="category-form-section"><div class="category-form-section-title"><b>Счёт и предупреждения</b></div><div class="field"><label>Кнопки счёта — подпись:изменение, через запятую</label><input name="score_buttons" value="${esc(scoreButtonsText(c.score_buttons))}" ${dis}><small>-1:-1, +1:1, +2:2, +3:3</small></div><div class="field"><label>Предупреждения — №:action:delta</label><input name="warning_rules" value="${esc(warningRulesText(c.warning_rules))}" ${dis}><small>action: warning / score_penalty / forfeit</small></div><div class="category-form-grid compact"><div class="field"><label>Предупреждений до DSQ</label><input name="cumulative_warning_limit" type="number" min="0" value="${c.cumulative_warning_limit}" ${dis}></div></div></section><section class="category-form-section"><div class="category-form-section-title"><b>Параметры формата</b></div><div class="category-format-settings format-empty-note" data-format-only="knockout">Для олимпийской системы дополнительных параметров не требуется.</div><div class="category-format-settings" data-format-only="groups"><div class="category-form-grid"><div class="field"><label>Желаемый размер группы</label><input name="group_target_size" type="number" min="2" value="${c.group_target_size}" ${dis}></div><div class="field"><label>Выходят из группы</label><input name="group_qualifiers" type="number" min="1" value="${c.group_qualifiers}" ${dis}></div></div></div><div class="category-format-settings" data-format-only="swiss"><div class="category-form-grid"><div class="field"><label>Количество Swiss-туров</label><input name="swiss_rounds" type="number" min="1" value="${c.swiss_rounds}" ${dis}></div></div></div><div class="category-format-settings" data-format-only="groups swiss round_robin"><div class="rules-subcard"><b>Турнирные очки</b><div class="category-form-grid top-gap-small"><div class="field"><label>За победу</label><input name="win_points" type="number" min="0" value="${c.win_points??3}" ${dis}></div><div class="field"><label>За ничью</label><input name="draw_points" type="number" min="0" value="${c.draw_points??1}" ${dis}></div></div></div></div></section>${completed?'':`<div class="category-form-actions"><button class="primary">${esc(submitLabel)}</button></div>`}</form>`;
}
function categoryFormData(form,currentOverride=null){const fd=new FormData(form);const current=currentOverride||adminState.categories.find(x=>x.id===adminState.selectedCategoryId)||categoryDefaults();return {name:String(fd.get('name')??current.name).trim(),format:fd.get('format')||current.format,match_duration_sec:Number(fd.get('match_duration_sec')??current.match_duration_sec),timer_warning_sec:Number(fd.get('timer_warning_sec')??current.timer_warning_sec),score_buttons:parseScoreButtons(fd.get('score_buttons')??scoreButtonsText(current.score_buttons)),warning_rules:parseWarningRules(fd.get('warning_rules')??warningRulesText(current.warning_rules)),cumulative_warning_limit:Number(fd.get('cumulative_warning_limit')??current.cumulative_warning_limit),group_target_size:Number(fd.get('group_target_size')??current.group_target_size),group_qualifiers:Number(fd.get('group_qualifiers')??current.group_qualifiers),swiss_rounds:Number(fd.get('swiss_rounds')??current.swiss_rounds),win_points:Number(fd.get('win_points')??current.win_points??3),draw_points:Number(fd.get('draw_points')??current.draw_points??1)};}
function bindCategoryFormatVisibility(form){if(!form)return;const sel=form.elements.format;if(!sel)return;const refresh=()=>{$$('[data-format-only]',form).forEach(el=>{const allowed=(el.dataset.formatOnly||'').split(/\s+/);el.hidden=!allowed.includes(sel.value);});};sel.onchange=refresh;refresh();}

function bindSeedDnD(c){
  if(!c)return;let dragged=null;
  $$('[data-cp]').forEach(el=>{el.ondragstart=()=>{dragged=el};el.ondragover=e=>{e.preventDefault();el.classList.add('over')};el.ondragleave=()=>el.classList.remove('over');el.ondrop=async e=>{e.preventDefault();el.classList.remove('over');if(!dragged||dragged===el)return;const list=$('#seedList');const rect=el.getBoundingClientRect();list.insertBefore(dragged,e.clientY<rect.top+rect.height/2?el:el.nextSibling);const ids=$$('[data-cp]',list).map(x=>Number(x.dataset.cp));try{await api(`/api/categories/${c.id}/seed`,{method:'PUT',body:JSON.stringify({cp_ids:ids})});await loadSelectedCategory();toast('Посев обновлён')}catch(err){toast(err.message,true);await loadSelectedCategory();renderCategories()}};});
}
function renderBracketTab(){
  const c=adminState.categories.find(x=>x.id===adminState.selectedCategoryId), archived=c?.status==='completed';
  const groupMatches=adminState.matches.filter(m=>m.stage==='group');
  const groupStaged=!!c&&c.format==='groups'&&groupMatches.length>0&&groupMatches.every(m=>m.status==='staged');
  const groupDone=!!c&&c.format==='groups'&&groupMatches.length>0&&groupMatches.every(m=>m.status==='finished');
  const swissRounds=adminState.matches.filter(m=>m.stage==='swiss'), swissCurrent=Math.max(0,...swissRounds.map(m=>m.round_no));
  const swissCurrentRows=swissRounds.filter(m=>m.round_no===swissCurrent), swissStaged=!!swissCurrentRows.length&&swissCurrentRows.every(m=>m.status==='staged');
  const canNextSwiss=!!c&&c.format==='swiss'&&swissRounds.length&& !swissStaged && swissCurrentRows.every(m=>m.status==='finished');
  let buildControls='';
  if(c&&!archived){
    if(c.format==='swiss'){if(!swissRounds.length)buildControls+=`<button id="generateBtn" class="primary">Сформировать тур 1</button>`;if(swissStaged)buildControls+=`<button id="startSwissBtn" class="primary">▶ Начать тур ${swissCurrent}</button>`;if(canNextSwiss)buildControls+=`<button id="swissBtn">Сформировать тур ${swissCurrent+1}</button>`;}
    else {buildControls+=`<button id="generateBtn" class="primary">${adminState.matches.length?'Перегенерировать':'Сформировать'}</button>`;}
    if(c.format==='groups'&&groupStaged)buildControls+=`<button id="startGroupsBtn" class="primary">▶ Начать групповой этап</button>`;
    if(c.format==='groups'&&groupDone&&!adminState.matches.some(m=>m.stage==='playoff'))buildControls+=`<button id="playoffBtn" class="primary">Создать плей-офф</button>`;
    buildControls+=`<button id="completeCategoryQuick">✓ Завершить категорию</button>`;
  }
  $('#adminContent').innerHTML=`<div class="bracket-toolbar"><div class="field"><label>Категория</label>${categorySelectHtml()}</div>${c?`${archived?'<span class="pill warn">Архив · только просмотр</span>':buildControls}<button id="standingsBtn">Таблица результатов</button><button id="bracketExportPdf">PDF</button><button id="bracketExportJson">JSON</button>`:''}${archived?'<span class="toolbar-hint">Только просмотр</span>':''}</div><div id="bracketBody" class="top-gap"></div>`;
  bindCategorySelect(async()=>{await loadSelectedCategory();renderBracketTab()});
  if(!c){$('#bracketBody').innerHTML='<div class="card">Выберите категорию.</div>';return;}
  if(!archived){
    if($('#generateBtn'))$('#generateBtn').onclick=async()=>{if(adminState.matches.length&&c.format!=='swiss'&&!confirm('Перестроить сетку? Это возможно только до начала боёв соответствующего этапа.'))return;try{await api(`/api/categories/${c.id}/generate`,{method:'POST'});await refreshAdminData(true);renderBracketTab()}catch(e){toast(e.message,true)}};
    if($('#startGroupsBtn'))$('#startGroupsBtn').onclick=async()=>{if(!confirm('Начать групповой этап? После этого состав групп будет зафиксирован.'))return;try{await api(`/api/categories/${c.id}/groups-start`,{method:'POST'});await refreshAdminData(true);renderBracketTab();toast('Групповой этап начат')}catch(e){toast(e.message,true)}};
    if($('#startSwissBtn'))$('#startSwissBtn').onclick=async()=>{if(!confirm(`Начать Swiss-тур ${swissCurrent}? После этого пары тура будут зафиксированы.`))return;try{await api(`/api/categories/${c.id}/swiss-start`,{method:'POST'});await refreshAdminData(true);renderBracketTab();toast(`Тур ${swissCurrent} начат`)}catch(e){toast(e.message,true)}};
    if($('#playoffBtn')) $('#playoffBtn').onclick=async()=>{try{await api(`/api/categories/${c.id}/group-playoff`,{method:'POST'});await refreshAdminData(true);renderBracketTab()}catch(e){toast(e.message,true)}};
    if($('#swissBtn')) $('#swissBtn').onclick=async()=>{try{await api(`/api/categories/${c.id}/swiss-next`,{method:'POST'});await refreshAdminData(true);renderBracketTab()}catch(e){toast(e.message,true)}};
    if($('#completeCategoryQuick')) $('#completeCategoryQuick').onclick=async()=>{if(!confirm(`Завершить категорию «${c.name}»?`))return;try{const r=await api(`/api/categories/${c.id}/complete`,{method:'POST'});await refreshAdminData(true);adminState.selectedCategoryId=c.id;await loadSelectedCategory();renderBracketTab();if(r.export_error)toast(`Категория завершена, но экспорт не создан: ${r.export_error}`,true);else toast('Категория завершена. PDF и JSON подготовлены.')}catch(e){toast(e.message,true)}};
  }
  $('#standingsBtn').onclick=()=>showStandings(c);
  $('#bracketExportPdf').onclick=()=>downloadUrl(`/api/categories/${c.id}/export.pdf`);
  $('#bracketExportJson').onclick=()=>downloadUrl(`/api/categories/${c.id}/export.json`);
  renderBracketBody(c);
}

function renderBracketBody(c){
  if(!adminState.matches.length){$('#bracketBody').innerHTML='<div class="empty-state compact"><h2>Сетка ещё не сформирована</h2><p>При жеребьёвке учитываются клуб и город.</p></div>';return;}
  let html='';
  if(c.format==='groups') html += renderGroupsLayout();
  const stages=[...new Set(adminState.matches.map(m=>m.stage))];
  for(const stage of stages){
    const ms=adminState.matches.filter(m=>m.stage===stage);
    if(stage==='group'){
      const groups=[...new Set(ms.map(m=>m.group_name))].sort();
      html += `<section class="card top-gap"><div class="section-head"><div><h2>Поединки группового этапа</h2></div></div>${groups.map(g=>`<div class="group-matches"><h3>Группа ${esc(g)}</h3><div class="table-wrap"><table class="table compact-table"><thead><tr><th>#</th><th>Красный</th><th>Синий</th><th>Счёт</th><th>Статус</th><th></th></tr></thead><tbody>${ms.filter(m=>m.group_name===g).map(m=>`<tr><td>${m.match_no}</td><td>${esc(fighterText(m.red))}</td><td>${esc(fighterText(m.blue))}</td><td><b>${m.red_score}:${m.blue_score}</b></td><td>${esc(statusText(m.status))}</td><td>${m.status==='finished'&&m.reason!=='BYE'?`<button class="small ghost" data-correct-match="${m.id}">Исправить</button>`:''}</td></tr>`).join('')}</tbody></table></div></div>`).join('')}</section>`;
    } else if(stage==='round_robin'){
      html += `<section class="card top-gap"><div class="section-head"><div><h2>Все со всеми</h2></div></div><div class="table-wrap"><table class="table compact-table"><thead><tr><th>#</th><th>Красный</th><th>Синий</th><th>Счёт</th><th>Статус</th><th></th></tr></thead><tbody>${ms.sort((a,b)=>a.match_no-b.match_no).map(m=>`<tr><td>${m.match_no}</td><td>${esc(fighterText(m.red))}</td><td>${esc(fighterText(m.blue))}</td><td><b>${m.red_score}:${m.blue_score}</b></td><td>${esc(statusText(m.status))}</td><td>${m.status==='finished'&&m.reason!=='BYE'?`<button class="small ghost" data-correct-match="${m.id}">Исправить</button>`:''}</td></tr>`).join('')}</tbody></table></div></section>`;
    } else if(stage==='knockout' || stage==='playoff') html += renderTreeStage(stage,ms);
    else if(stage==='swiss') html += renderSwissStage(ms);
  }
  $('#bracketBody').innerHTML=html;
  if(c.status!=='completed'&&c.format==='groups') bindGroupDnD(c);
  if(c.status!=='completed') for(const stage of ['knockout','playoff']) if(adminState.matches.some(m=>m.stage===stage)) bindBracketDnD(c,stage);
  if(c.status!=='completed'&&c.format==='swiss') bindSwissDnD(c);
  if(c.status!=='completed') bindMatchCorrectionButtons(async()=>{await refreshAdminData(true);renderBracketTab()});
  requestAnimationFrame(redrawAllBracketLines);
  clearTimeout(window.__bracketResizeTimer);
  if(!window.__bracketResizeBound){window.addEventListener('resize',()=>{clearTimeout(window.__bracketResizeTimer);window.__bracketResizeTimer=setTimeout(redrawAllBracketLines,120)});window.__bracketResizeBound=true;}
}
function groupCpLocked(cpId){
  return adminState.matches.some(m=>m.stage==='group'&&(m.red?.cp_id===cpId||m.blue?.cp_id===cpId)&&(m.status==='in_progress'||(m.status==='finished'&&m.reason!=='BYE')||m.red_score||m.blue_score||m.red_warnings||m.blue_warnings));
}
function renderGroupsLayout(){
  const groups={}; for(const cp of adminState.categoryParticipants){ if(cp.group){(groups[cp.group]??=[]).push(cp);} }
  const names=Object.keys(groups).sort();
  if(!names.length)return '';
  const playoffExists=adminState.matches.some(m=>m.stage==='playoff');
  const movable=cp=>!playoffExists&&!groupCpLocked(cp.id);
  const anyMovable=Object.values(groups).flat().some(movable);
  return `<section class="card"><div class="section-head"><div><h2>Состав групп</h2><p>${playoffExists?'Состав групп зафиксирован.':anyMovable?'Перетаскивайте бойцов между группами до их первого боя.':'Состав групп зафиксирован.'}</p></div><span class="pill">Разведение: клуб → город</span></div><div class="groups-grid">${names.map(g=>`<div class="group-box"><div class="group-title"><b>Группа ${esc(g)}</b><span>${groups[g].length} уч.</span></div><div class="group-members" data-group="${esc(g)}">${groups[g].map(cp=>{const editable=movable(cp);return `<div class="group-member ${editable?'drag':'locked'}" draggable="${editable}" data-group-cp="${cp.id}">${editable?'<span class="drag-handle">⋮⋮</span>':'<span class="drag-lock">●</span>'}<div class="grow"><b>${esc(cp.name)}</b><small>${esc(affiliation(cp)||'Без клуба / города')}</small></div></div>`}).join('')}</div></div>`).join('')}</div></section>`;
}


function renderTreeStage(stage,ms){
  const bronze=ms.find(m=>m.is_third_place), tree=ms.filter(m=>!m.is_third_place);
  const rounds=[...new Set(tree.map(m=>m.round_no))].sort((a,b)=>a-b), last=rounds.at(-1);
  if(!last)return '';
  const first=tree.filter(m=>m.round_no===1).sort((a,b)=>a.match_no-b.match_no);
  // Центральная колонка может содержать финал и бой за третье место.
  // После появления результата прежней минимальной высоты могло не хватать.
  // Резервируем место для обеих карточек целиком, не уменьшая
  // подписи и не скрывая нижнюю часть контейнером.
  const centerMinHeight=bronze?520:430;
  const height=Math.max(centerMinHeight,Math.ceil(first.length/2)*165);
  const roundColumn=(r,side)=>{
    const all=tree.filter(m=>m.round_no===r).sort((a,b)=>a.match_no-b.match_no), half=Math.ceil(all.length/2);
    const rows=side==='left'?all.slice(0,half):all.slice(half);
    return `<div class="mirror-round ${side}" data-round="${r}"><div class="round-title">${roundLabel(r,rounds.length)}</div><div class="mirror-round-matches">${rows.map(m=>{const firstIndex=first.findIndex(x=>x.id===m.id);return treeMatchCard(m,r===1,firstIndex>=0?firstIndex*2:0)}).join('')}</div></div>`;
  };
  const leftRounds=rounds.filter(r=>r<last).map(r=>roundColumn(r,'left')).join('');
  const rightRounds=rounds.filter(r=>r<last).sort((a,b)=>b-a).map(r=>roundColumn(r,'right')).join('');
  const finalMatch=tree.find(m=>m.round_no===last);
  return `<section class="card top-gap bracket-section mirror-bracket-section" data-stage-section="${stage}"><div class="section-head"><div><h2>${stage==='playoff'?'Плей-офф':'Олимпийская сетка'}</h2><p>Первый раунд можно переставлять до начала этапа.</p></div><span class="pill">${first.length*2} мест</span></div><div class="mirror-bracket-scroll"><div class="mirror-bracket" data-bracket-stage="${stage}" style="height:${height}px"><svg class="bracket-lines" aria-hidden="true"></svg>${leftRounds}<div class="final-column"><div class="round-title">Финал</div><div class="final-match-wrap">${treeMatchCard(finalMatch,last===1,0)}${bronze?`<div class="third-place-wrap"><div class="round-title">За 3-е место</div>${treeMatchCard(bronze,false,0)}</div>`:''}</div></div>${rightRounds}</div></div></section>`;
}

function treeMatchCard(m,draggable=false,slotBase=0){
  if(!m)return '';
  const side=(f,score,which,idx)=>`<div class="fighter-card bracket-slot ${m.winner_cp_id===f?.cp_id?'winner':''} ${f?'':'bye-card'}" ${draggable?`data-bracket-slot="${idx}" data-slot-cp="${f?.cp_id||''}"`:''} ${draggable&&f?`draggable="true"`:''}><span class="side-mark ${which}"></span><div class="slot-person"><b>${esc(f?.name||'BYE')}</b><small>${esc(affiliation(f)||'Свободный слот')}</small></div><strong>${score}</strong>${draggable?'<span class="card-drag">⋮⋮</span>':''}</div>`;
  return `<div class="bracket-match" data-bracket-match="${m.id}"><div class="match-meta"><span>Бой #${m.match_no}</span><span class="match-meta-right">${esc(statusText(m.status))}${m.status==='finished'&&m.reason!=='BYE'?`<button class="mini-edit" data-correct-match="${m.id}" title="Исправить результат">✎</button>`:''}</span></div>${side(m.red,m.red_score,'red',slotBase)}${side(m.blue,m.blue_score,'blue',slotBase+1)}${m.reason?`<div class="result-note">${esc(reasonText(m.reason))}</div>`:''}</div>`;
}
function drawBracketLines(stage,ms){
  const root=$(`[data-bracket-stage="${stage}"]`); if(!root)return; const svg=$('.bracket-lines',root);if(!svg)return;
  const rr=root.getBoundingClientRect(); svg.setAttribute('viewBox',`0 0 ${rr.width} ${rr.height}`);svg.setAttribute('width',rr.width);svg.setAttribute('height',rr.height);
  const paths=[];
  for(const m of ms){
    if(!m.next_match_id)continue;const a=$(`[data-bracket-match="${m.id}"]`,root),b=$(`[data-bracket-match="${m.next_match_id}"]`,root);if(!a||!b)continue;
    const ar=a.getBoundingClientRect(),br=b.getBoundingClientRect();const leftToRight=ar.left<br.left;
    const sx=(leftToRight?ar.right:ar.left)-rr.left, sy=ar.top+ar.height/2-rr.top;
    const tx=(leftToRight?br.left:br.right)-rr.left, ty=br.top+br.height/2-rr.top;const mx=(sx+tx)/2;
    paths.push(`<path d="M ${sx.toFixed(1)} ${sy.toFixed(1)} H ${mx.toFixed(1)} V ${ty.toFixed(1)} H ${tx.toFixed(1)}"/>`);
  }
  svg.innerHTML=paths.join('');
}
function redrawAllBracketLines(){for(const stage of ['knockout','playoff']){const ms=adminState.matches.filter(m=>m.stage===stage);if(ms.length)drawBracketLines(stage,ms)}}

function swissMatchLocked(m){return m.status==='in_progress'||(m.status==='finished'&&m.reason!=='BYE')||m.red_score||m.blue_score||m.red_warnings||m.blue_warnings;}
function renderSwissStage(ms){
  const rounds=[...new Set(ms.map(m=>m.round_no))].sort((a,b)=>a-b), current=rounds.at(-1);
  return `<section class="card top-gap"><div class="section-head"><div><h2>Швейцарская система</h2><p>Пары текущего тура можно переставлять до начала боя.</p></div></div><div class="swiss-rounds">${rounds.map(r=>{const rows=ms.filter(m=>m.round_no===r).sort((a,b)=>a.match_no-b.match_no),currentRound=r===current;let idx=0;const anyEditable=currentRound&&rows.some(m=>!swissMatchLocked(m));return `<div class="swiss-round ${anyEditable?'editable':''}" data-swiss-round="${r}"><div class="swiss-round-head"><h3>Тур ${r}</h3><span>${rows.every(m=>m.status==='finished')?'Завершён':anyEditable?'Можно менять пары':'Идёт'}</span></div><div class="swiss-pairs-grid">${rows.map(m=>{const a=idx++,b=idx++,locked=!currentRound||swissMatchLocked(m);const slot=(f,slotIdx)=>`<div class="swiss-fighter ${f?'':'bye-card'} ${locked?'locked':''}" data-swiss-slot="${slotIdx}" data-swiss-cp="${f?.cp_id||''}" data-swiss-locked="${locked?'1':'0'}" ${!locked&&f?'draggable="true"':''}><span class="drag-handle">${!locked?'⋮⋮':'●'}</span><span><b>${esc(f?.name||'BYE')}</b><small>${esc(affiliation(f)||'Свободный слот')}</small></span></div>`;return `<div class="swiss-pair">${slot(m.red,a)}<span class="vs">—</span>${slot(m.blue,b)}<small class="swiss-state">${m.red_score}:${m.blue_score} · ${esc(statusText(m.status))}${m.reason?' · '+esc(reasonText(m.reason)):''}${m.status==='finished'&&m.reason!=='BYE'?` <button class="link-edit" data-correct-match="${m.id}">Исправить</button>`:''}</small></div>`}).join('')}</div></div>`}).join('')}</div></section>`;
}
function bindSwissDnD(c){
  const rows=adminState.matches.filter(m=>m.stage==='swiss'), current=Math.max(0,...rows.map(m=>m.round_no)), currentRows=rows.filter(m=>m.round_no===current).sort((a,b)=>a.match_no-b.match_no);
  if(!currentRows.length)return;
  const root=$(`[data-swiss-round="${current}"]`);if(!root)return;let dragged=null;$$('[data-swiss-slot]',root).forEach(slot=>{const locked=slot.dataset.swissLocked==='1';if(!locked&&slot.dataset.swissCp)slot.ondragstart=e=>{dragged=Number(slot.dataset.swissCp);e.dataTransfer.setData('text/plain',String(dragged));slot.classList.add('dragging')};slot.ondragend=()=>slot.classList.remove('dragging');if(!locked){slot.ondragover=e=>{e.preventDefault();slot.classList.add('drop-target')};slot.ondragleave=()=>slot.classList.remove('drop-target');slot.ondrop=async e=>{e.preventDefault();slot.classList.remove('drop-target');if(!dragged)return;const slots=[];for(const m of currentRows)slots.push(m.red?.cp_id||null,m.blue?.cp_id||null);const source=slots.indexOf(dragged),target=Number(slot.dataset.swissSlot);if(source<0||source===target)return;[slots[source],slots[target]]=[slots[target],slots[source]];try{await api(`/api/categories/${c.id}/swiss-layout`,{method:'PUT',body:JSON.stringify({cp_ids:slots})});await refreshAdminData(true);renderBracketTab();toast('Пары Swiss-тура обновлены')}catch(err){toast(err.message,true);await refreshAdminData(true);renderBracketTab()}}}});
}


function bindGroupDnD(c){
  let dragged=null;
  const save=async()=>{const groups={};$$('.group-members').forEach(g=>groups[g.dataset.group]=$$('[data-group-cp]',g).map(x=>Number(x.dataset.groupCp)));try{await api(`/api/categories/${c.id}/groups-layout`,{method:'PUT',body:JSON.stringify({groups})});await refreshAdminData(true);renderBracketTab();toast('Состав групп обновлён')}catch(err){toast(err.message,true);await refreshAdminData(true);renderBracketTab()}};
  $$('[data-group-cp][draggable="true"]').forEach(el=>{el.ondragstart=e=>{dragged=el;e.dataTransfer.setData('text/plain',el.dataset.groupCp);el.classList.add('dragging')};el.ondragend=()=>el.classList.remove('dragging');el.ondragover=e=>{e.preventDefault();el.classList.add('drop-target')};el.ondragleave=()=>el.classList.remove('drop-target');el.ondrop=async e=>{e.preventDefault();e.stopPropagation();el.classList.remove('drop-target');if(!dragged||dragged===el)return;const box=el.closest('.group-members'),rect=el.getBoundingClientRect();box.insertBefore(dragged,e.clientY<rect.top+rect.height/2?el:el.nextSibling);await save()}});
  $$('.group-members').forEach(box=>{box.ondragover=e=>{e.preventDefault();box.classList.add('drop-target')};box.ondragleave=()=>box.classList.remove('drop-target');box.ondrop=async e=>{if(e.target.closest('[data-group-cp]'))return;e.preventDefault();box.classList.remove('drop-target');if(!dragged)return;box.appendChild(dragged);await save()};});
}

function bindBracketDnD(c,stage){
  const first=adminState.matches.filter(m=>m.stage===stage&&m.round_no===1).sort((a,b)=>a.match_no-b.match_no);
  if(!first.length)return;
  let draggedCp=null;
  $$(`[data-bracket-slot]`).forEach(slot=>{
    if(slot.dataset.slotCp) slot.ondragstart=e=>{draggedCp=Number(slot.dataset.slotCp);e.dataTransfer.setData('text/plain',String(draggedCp));slot.classList.add('dragging')};
    slot.ondragend=()=>slot.classList.remove('dragging');
    slot.ondragover=e=>{e.preventDefault();slot.classList.add('drop-target')}; slot.ondragleave=()=>slot.classList.remove('drop-target');
    slot.ondrop=async e=>{e.preventDefault();slot.classList.remove('drop-target');if(!draggedCp)return;const targetIdx=Number(slot.dataset.bracketSlot);let slots=[];for(const m of first)slots.push(m.red?.cp_id||null,m.blue?.cp_id||null);const sourceIdx=slots.indexOf(draggedCp);if(sourceIdx<0||sourceIdx===targetIdx)return;[slots[sourceIdx],slots[targetIdx]]=[slots[targetIdx],slots[sourceIdx]];try{await api(`/api/categories/${c.id}/bracket-layout`,{method:'PUT',body:JSON.stringify({stage,slot_cp_ids:slots})});await refreshAdminData(true);renderBracketTab();toast('Ветви сетки обновлены')}catch(err){toast(err.message,true);await refreshAdminData(true);renderBracketTab()}};
  });
}
async function showStandings(c){
  try{
    const rows=await api(`/api/categories/${c.id}/standings`);
    const elimination=rows.some(r=>r.ranking_type==='elimination');
    const w=window.open('','standings','width=980,height=780');
    const css=`body{font-family:Arial,sans-serif;padding:20px;color:#1f2937}h2{margin:0 0 6px}.hint{color:#667085;margin:0 0 16px;font-size:13px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left;vertical-align:top}th{background:#f7f8fa;position:sticky;top:0}.stage{font-weight:700}.score{font-variant-numeric:tabular-nums;white-space:nowrap}.muted{color:#7b8794}`;
    let table='';
    if(elimination){
      table=`<p class="hint">Сортировка: достигнутый этап, затем результат и разница счёта.</p><table><tr><th>#</th><th>Участник</th><th>Клуб / город</th><th>Достигнутый этап</th><th>Бои</th><th>Победы</th><th>Общий счёт</th><th>Последний бой</th><th>Пред.</th></tr>${rows.map(r=>`<tr><td><b>${r.place}</b></td><td>${esc(r.name)}</td><td>${esc([r.club,r.city].filter(Boolean).join(' · '))}</td><td class="stage">${esc(r.stage_label||'—')}</td><td>${r.played}</td><td>${r.wins}</td><td class="score">${r.for}:${r.against} <span class="muted">(${r.diff>=0?'+':''}${r.diff})</span></td><td class="score">${r.last_score?`${esc(r.last_score)}${r.last_result?` · ${esc(reasonText(r.last_result))}`:''}`:'—'}</td><td>${r.warnings}${r.disqualified?' DSQ':''}</td></tr>`).join('')}</table>`;
    }else{
      table=`<table><tr><th>#</th><th>Участник</th><th>Клуб / город</th><th>Группа</th><th>Бои</th><th>Победы</th><th>Ничьи</th><th>Турн. очки</th><th>Разница</th><th>Пред.</th></tr>${rows.map(r=>`<tr><td>${r.place}</td><td>${esc(r.name)}</td><td>${esc([r.club,r.city].filter(Boolean).join(' · '))}</td><td>${esc(r.group)}</td><td>${r.played}</td><td>${r.wins}</td><td>${r.draws??0}</td><td><b>${r.points}</b></td><td>${r.diff}</td><td>${r.warnings}${r.disqualified?' DSQ':''}</td></tr>`).join('')}</table>`;
    }
    w.document.write(`<html><head><meta charset="utf-8"><title>Таблица результатов</title><style>${css}</style></head><body><h2>${esc(c.name)}</h2>${table}</body></html>`);
    w.document.close();
  }catch(e){toast(e.message,true)}
}
