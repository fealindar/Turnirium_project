// --------------------------- Расписание площадок ---------------------------
function scheduleFormatName(format) {
  return ({
    knockout:'Олимпийская',
    groups:'Группы + плей-офф',
    swiss:'Швейцарская',
    round_robin:'Все со всеми',
  })[format] || format || 'Категория';
}

function scheduleStageLabel(match) {
  if (match.is_third_place) return 'За 3-е место';
  if (match.stage === 'group') return `Группа ${match.group_name || '—'}`;
  if (match.stage === 'swiss') return `Тур ${match.round_no}`;
  if (match.stage === 'round_robin') return 'Все со всеми';
  if (match.stage === 'playoff') return `Плей-офф · раунд ${match.round_no}`;
  return `Олимпийка · раунд ${match.round_no}`;
}

function scheduleUnassignedHtml(schedule) {
  const byCategory = new Map();
  for (const match of schedule.unassigned || []) {
    if (!byCategory.has(match.category_id)) byCategory.set(match.category_id, []);
    byCategory.get(match.category_id).push(match);
  }
  const units = new Map((schedule.category_units || []).map(row => [row.category_id, row]));
  if (!byCategory.size) return '<div class="schedule-empty">Нет готовых неназначенных боёв</div>';
  return [...byCategory.entries()].map(([categoryId, matches]) => {
    const unit = units.get(categoryId);
    const groups = new Map();
    for (const match of matches) {
      const key = match.stage === 'group' ? `Группа ${match.group_name || '—'}` : scheduleStageLabel(match);
      if (!groups.has(key)) groups.set(key, []);
      groups.get(key).push(match);
    }
    return `<section class="unassigned-category">
      <div class="unassigned-category-head"><div><b>${esc(matches[0]?.category_name || unit?.name || 'Категория')}</b><small>${unit ? `${esc(scheduleFormatName(unit.format))} · ${unit.participant_count} бойцов` : ''}</small></div><span>${matches.length}</span></div>
      ${[...groups.entries()].map(([label, rows]) => `<div class="unassigned-stage"><div class="unassigned-stage-title">${esc(label)}</div>${rows.map(m => scheduleChip(m)).join('')}</div>`).join('')}
    </section>`;
  }).join('');
}

function scheduleFightersPreview(names, limit=5) {
  const items = names || [];
  const shown = items.slice(0, limit).map(esc).join(', ');
  return `${shown}${items.length > limit ? ` +${items.length - limit}` : ''}`;
}

function quickAssignButtons(unit, groupName='') {
  const schedule = adminState.schedule || {areas:[]};
  const available = groupName
    ? unit.groups.find(group => group.name === groupName)?.ready_unassigned || 0
    : unit.ready_unassigned || 0;
  return (schedule.areas || []).map(column => `<button class="small quick-area-btn" data-quick-category="${unit.category_id}" data-quick-group="${esc(groupName)}" data-quick-area="${column.area.id}" ${available && column.area.enabled !== false ? '' : 'disabled'} title="Назначить ${groupName ? `группу ${esc(groupName)} категории ${esc(unit.name)}` : `категорию ${esc(unit.name)}`} на ${esc(column.area.name)}">→ ${esc(column.area.name)}</button>`).join('');
}

function quickAssignmentHtml(schedule) {
  const units = schedule.category_units || [];
  if (!units.length) return '<div class="muted">В активных категориях пока нет заявленных бойцов.</div>';
  return `<div class="quick-assignment-list">${units.map(unit => {
    const groups = unit.groups || [];
    const groupsOpen = adminUiState.scheduleExpandedGroups.has(unit.category_id);
    const groupBlock = groups.length ? `<details class="quick-group-details" data-quick-groups-category="${unit.category_id}" ${groupsOpen ? 'open' : ''}><summary><span>Группы</span><span>${groups.length}</span></summary><div class="quick-group-list">${groups.map(group => `<div class="quick-group-row"><div class="quick-group-info"><b>Группа ${esc(group.name)}</b><small>${group.participant_count} бойцов · ${group.ready_unassigned} готово</small><small class="quick-fighters" title="${esc((group.participants || []).join(', '))}">${scheduleFightersPreview(group.participants, 4)}</small></div><div class="quick-area-actions">${quickAssignButtons(unit, group.name)}</div></div>`).join('')}</div></details>` : '';
    return `<section class="quick-category-card"><div class="quick-category-top"><div class="quick-category-summary"><div><b>${esc(unit.name)}</b><small>${esc(scheduleFormatName(unit.format))} · ${unit.participant_count} бойцов</small></div><small class="quick-fighters" title="${esc((unit.participants || []).join(', '))}">${scheduleFightersPreview(unit.participants, 5)}</small></div><div class="quick-category-actions"><span class="pill">${unit.ready_unassigned} готово</span><div class="quick-area-actions">${quickAssignButtons(unit)}</div></div></div>${groupBlock}</section>`;
  }).join('')}</div>`;
}

function scheduleWarningHtml(match) {
  const notes = [];
  if (match.repeat_warning) notes.push('<small class="repeat-note">⚠ Мало отдыха между боями на этой площадке</small>');
  if (match.cross_area_warning) {
    const details = (match.cross_area_conflicts || []).map(conflict => {
      const people = (conflict.participants || []).join(', ') || 'тот же боец';
      return `${people}: ${conflict.area_name}, позиция ${conflict.queue_position || conflict.queue_order}`;
    }).join('; ');
    notes.push(`<small class="cross-area-note">⚠ Конфликт соседних площадок: ${esc(details)}</small>`);
  }
  return notes.join('');
}

function scheduleChip(match, currentId=null) {
  const movable = match.status !== 'in_progress';
  const warningClass = match.cross_area_warning ? 'cross-area-risk' : match.repeat_warning ? 'repeat-risk' : '';
  return `<div class="match-chip schedule-match ${match.id === currentId ? 'current' : ''} ${warningClass}" draggable="${movable}" data-match="${match.id}" data-match-area="${match.area_id || ''}">
    <div class="match-chip-title"><b><span class="drag-handle">${movable ? '⋮⋮' : '●'}</span> #${match.match_no} · ${esc(match.category_name)}</b><span class="pill">${esc(statusText(match.status))}</span></div>
    <div class="match-stage-row"><span class="stage-badge">${esc(scheduleStageLabel(match))}</span>${match.area_id ? `<span class="queue-badge">позиция ${match.queue_position || match.queue_order || '—'}</span>` : ''}</div>
    <div class="match-pair"><span class="red-dot"></span>${esc(fighterText(match.red))}</div>
    <div class="match-pair"><span class="blue-dot"></span>${esc(fighterText(match.blue))}</div>
    ${scheduleWarningHtml(match)}
    ${match.area_id ? `<button class="small" data-select-match="${match.id}" data-area="${match.area_id}">${match.id === currentId ? 'На табло' : 'Показать на табло'}</button>` : ''}
  </div>`;
}

function renderSchedule() {
  const schedule = adminState.schedule || {areas:[],unassigned:[],category_units:[],settings:{avoid_consecutive_matches:true,preferred_match_gap:1}};
  const auto = adminState.areas.length === 1;
  const cfg = schedule.settings || {avoid_consecutive_matches:true,preferred_match_gap:1};
  const localWarnings = (schedule.areas || []).reduce((sum, column) => sum + column.matches.filter(m => m.repeat_warning).length, 0);
  const crossWarnings = (schedule.areas || []).reduce((sum, column) => sum + column.matches.filter(m => m.cross_area_warning).length, 0);
  $('#adminContent').innerHTML = `<div class="section-head schedule-page-head"><div><h2>Расписание площадок</h2><p>Назначайте категории, группы или отдельные бои по площадкам.</p></div><div class="row schedule-main-actions">${auto ? '<span class="pill live-pill">Автоназначение включено</span>' : ''}<button id="resetScheduleAssignments" class="danger ghost" ${schedule.areas.length || schedule.unassigned.length ? '' : 'disabled'}>Сбросить распределение</button><button id="addArea">+ Добавить площадку</button></div></div>
    <div class="card schedule-settings"><div><b>Порядок боёв</b><small>Интервал между повторными выходами одного бойца.</small></div><label class="check-row"><input id="avoidConsecutive" type="checkbox" ${cfg.avoid_consecutive_matches ? 'checked' : ''}> Разносить повторные выходы</label><label class="field compact-field"><span>Других боёв между выходами</span><input id="preferredGap" type="number" min="1" max="10" value="${cfg.preferred_match_gap || 1}" ${cfg.avoid_consecutive_matches ? '' : 'disabled'}></label><button id="saveScheduleSettings">Сохранить</button><button id="optimizeSchedule" ${cfg.avoid_consecutive_matches ? '' : 'disabled'}>Оптимизировать очереди</button><div class="schedule-warning-summary">${localWarnings ? `<span class="schedule-warning">⚠ Внутри площадок: ${localWarnings}</span>` : '<span class="schedule-ok">Внутри площадок интервалы соблюдены</span>'}${crossWarnings ? `<span class="schedule-danger">⚠ Между площадками: ${crossWarnings}</span>` : '<span class="schedule-ok">Межплощадочных конфликтов ±1 нет</span>'}</div></div>
    <section class="card quick-assignment"><div class="section-head compact"><div><h2>Быстрое распределение</h2></div></div>${quickAssignmentHtml(schedule)}</section>
    <div class="schedule-layout"><section class="schedule-unassigned schedule-drop-zone" data-area=""><div class="schedule-head"><div><h3>Не распределены</h3><small>Разделены по категориям и этапам</small></div><span>${schedule.unassigned.length}</span></div>${scheduleUnassignedHtml(schedule)}</section><div class="schedule-area-scroll"><div class="schedule-area-grid">${schedule.areas.map(column => `<section class="schedule-col schedule-drop-zone ${column.area.enabled === false ? 'disabled' : ''}" data-area="${column.area.id}" data-enabled="${column.area.enabled === false ? '0' : '1'}"><div class="schedule-head"><div><h3>${esc(column.area.name)}</h3><small>${column.area.enabled === false ? 'Площадка отключена' : 'Очередь площадки'}</small></div><div class="schedule-head-actions"><span>${column.matches.length}</span><button class="area-reset-btn" type="button" data-reset-area="${column.area.id}" data-area-name="${esc(column.area.name)}" ${column.matches.length?'':'disabled'} title="Снять все бои с площадки">Сбросить</button><button class="area-delete-btn" type="button" data-delete-area="${column.area.id}" data-area-name="${esc(column.area.name)}" title="Удалить площадку" aria-label="Удалить площадку ${esc(column.area.name)}">×</button></div></div><div class="schedule-column-body">${column.matches.map(match => scheduleChip(match, column.area.current_match_id)).join('') || '<div class="schedule-empty">Очередь пуста</div>'}</div></section>`).join('') || '<div class="schedule-no-areas">Площадок нет.</div>'}</div></div></div>`;
  bindScheduleControls();
}
function bindScheduleControls() {
  $$('[data-quick-groups-category]').forEach(details => {
    details.ontoggle = () => {
      const categoryId = Number(details.dataset.quickGroupsCategory);
      if (details.open) adminUiState.scheduleExpandedGroups.add(categoryId);
      else adminUiState.scheduleExpandedGroups.delete(categoryId);
    };
  });
  $('#avoidConsecutive').onchange = event => {
    $('#preferredGap').disabled = !event.target.checked;
    $('#optimizeSchedule').disabled = !event.target.checked;
  };
  $('#saveScheduleSettings').onclick = async () => {
    try {
      await api(`/api/tournaments/${adminState.tournamentId}/schedule-settings`, {method:'PUT', body:JSON.stringify({avoid_consecutive_matches:$('#avoidConsecutive').checked, preferred_match_gap:Number($('#preferredGap').value) || 1})});
      await refreshAdminData(true); renderSchedule(); toast('Настройки порядка боёв сохранены');
    } catch (error) { toast(error.message, true); }
  };
  $('#optimizeSchedule').onclick = async () => {
    try {
      const result = await api(`/api/tournaments/${adminState.tournamentId}/schedule-optimize`, {method:'POST'});
      await refreshAdminData(true); renderSchedule();
      toast(result.unavoidable_conflicts ? `Очереди оптимизированы. Неизбежных близких выходов: ${result.unavoidable_conflicts}` : 'Очереди оптимизированы');
    } catch (error) { toast(error.message, true); }
  };
  $('#addArea').onclick = async () => {
    const name = prompt('Название площадки:', `Площадка ${adminState.areas.length + 1}`);
    if (!name) return;
    try { await api(`/api/tournaments/${adminState.tournamentId}/areas`, {method:'POST', body:JSON.stringify({name})}); await refreshAdminData(true); renderSchedule(); }
    catch (error) { toast(error.message, true); }
  };
  $('#resetScheduleAssignments').onclick = async () => {
    if (!confirm('Снять распределение всех незавершённых боёв по площадкам? Завершённые результаты не изменятся.')) return;
    try {
      const result = await api(`/api/tournaments/${adminState.tournamentId}/schedule-reset`, {method:'POST'});
      await refreshAdminData(true); renderSchedule();
      toast(`Распределение сброшено. Возвращено боёв: ${result.unassigned_matches}`);
    } catch (error) { toast(error.message, true); }
  };
  $$('[data-reset-area]').forEach(button => button.onclick = async event => {
    event.stopPropagation();
    const name = button.dataset.areaName || 'площадку';
    if (!confirm(`Снять все незавершённые бои с «${name}» и вернуть их в нераспределённые?`)) return;
    try {
      const result = await api(`/api/areas/${button.dataset.resetArea}/reset`, {method:'POST'});
      await refreshAdminData(true); renderSchedule();
      toast(result.unassigned_matches ? `Площадка очищена. Возвращено боёв: ${result.unassigned_matches}` : 'На площадке не было назначенных боёв');
    } catch (error) { toast(error.message, true); }
  });
  $$('[data-delete-area]').forEach(button => button.onclick = async event => {
    event.stopPropagation();
    const name = button.dataset.areaName || 'площадку';
    if (!confirm(`Удалить «${name}»? Незавершённые назначенные бои вернутся в список нераспределённых.`)) return;
    try {
      const result = await api(`/api/areas/${button.dataset.deleteArea}`, {method:'DELETE'});
      await refreshAdminData(true); renderSchedule();
      toast(result.returned_to_pool ? `Площадка удалена. Возвращено боёв: ${result.returned_to_pool}` : 'Площадка удалена');
    } catch (error) { toast(error.message, true); }
  });
  $$('[data-select-match]').forEach(button => button.onclick = async event => {
    event.stopPropagation();
    try { await api(`/api/areas/${button.dataset.area}/select/${button.dataset.selectMatch}`, {method:'POST'}); await refreshAdminData(true); renderSchedule(); }
    catch (error) { toast(error.message, true); }
  });
  $$('[data-quick-category]').forEach(button => button.onclick = () => quickAssignScheduleUnit(button));
  bindScheduleDnD();
}

async function quickAssignScheduleUnit(button) {
  const categoryId = Number(button.dataset.quickCategory);
  const areaId = Number(button.dataset.quickArea);
  const groupName = button.dataset.quickGroup || '';
  try {
    const result = await api(`/api/tournaments/${adminState.tournamentId}/schedule-assign-unit`, {method:'POST', body:JSON.stringify({category_id:categoryId, area_id:areaId, group_name:groupName})});
    await refreshAdminData(true); renderSchedule();
    toast(`Назначено боёв: ${result.assigned}`);
  } catch (error) { toast(error.message, true); }
}

function clearScheduleDropMarkers() {
  $$('.schedule-match.drop-before,.schedule-match.drop-after').forEach(card => card.classList.remove('drop-before', 'drop-after'));
  $$('.schedule-drop-zone.drag-over').forEach(column => column.classList.remove('drag-over'));
}

function bindScheduleDnD() {
  let draggedId = null;
  let sourceArea = '';
  $$('[data-match][draggable="true"]').forEach(card => {
    card.ondragstart = event => {
      draggedId = Number(card.dataset.match); sourceArea = card.dataset.matchArea || '';
      event.dataTransfer.effectAllowed = 'move'; event.dataTransfer.setData('text/plain', String(draggedId));
      card.classList.add('dragging'); document.body.classList.add('schedule-drag-active');
    };
    card.ondragend = () => { card.classList.remove('dragging'); document.body.classList.remove('schedule-drag-active'); clearScheduleDropMarkers(); };
    card.ondragover = event => {
      event.preventDefault(); event.stopPropagation(); clearScheduleDropMarkers();
      const rect = card.getBoundingClientRect();
      card.classList.add(event.clientY < rect.top + rect.height / 2 ? 'drop-before' : 'drop-after');
      card.closest('[data-area]')?.classList.add('drag-over');
    };
    card.ondrop = async event => {
      event.preventDefault(); event.stopPropagation();
      const targetArea = card.closest('[data-area]').dataset.area;
      const after = card.classList.contains('drop-after');
      const beforeCard = after ? card.nextElementSibling?.closest?.('[data-match]') : card;
      clearScheduleDropMarkers();
      await handleScheduleDrop(draggedId, sourceArea, targetArea, beforeCard || null);
    };
  });
  $$('.schedule-drop-zone').forEach(column => {
    if (column.dataset.enabled === '0') return;
    column.ondragover = event => { if (event.target.closest('[data-match]')) return; event.preventDefault(); clearScheduleDropMarkers(); column.classList.add('drag-over'); };
    column.ondragleave = event => { if (!column.contains(event.relatedTarget)) column.classList.remove('drag-over'); };
    column.ondrop = async event => {
      if (event.target.closest('[data-match]')) return;
      event.preventDefault(); clearScheduleDropMarkers();
      await handleScheduleDrop(draggedId, sourceArea, column.dataset.area, null);
    };
  });
}

async function handleScheduleDrop(matchId, sourceArea, targetArea, beforeEl) {
  if (!matchId) return;
  try {
    if (!targetArea) {
      await api('/api/schedule/assign', {method:'POST', body:JSON.stringify({match_id:matchId, area_id:null})});
    } else if (String(sourceArea) !== String(targetArea)) {
      await api('/api/schedule/assign', {method:'POST', body:JSON.stringify({match_id:matchId, area_id:Number(targetArea)})});
    }
    await refreshAdminData(true);
    if (targetArea) {
      const column = adminState.schedule.areas.find(row => String(row.area.id) === String(targetArea));
      const ids = (column?.matches || []).map(match => match.id).filter(id => id !== matchId);
      const beforeId = beforeEl ? Number(beforeEl.dataset.match) : null;
      const index = beforeId ? ids.indexOf(beforeId) : -1;
      ids.splice(index >= 0 ? index : ids.length, 0, matchId);
      await api(`/api/areas/${targetArea}/queue`, {method:'PUT', body:JSON.stringify({match_ids:ids})});
      await refreshAdminData(true);
    }
    renderSchedule();
  } catch (error) {
    toast(error.message, true); await refreshAdminData(true); renderSchedule();
  }
}
