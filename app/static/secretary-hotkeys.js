/* Горячие клавиши секретаря: физические коды клавиш, локальные настройки, без зависимостей. */
(function (global) {
  'use strict';

  const STORAGE_KEY = 'turnirium.secretary.hotkeys.v1';
  const ACTIONS = Object.freeze([
    {id:'timerToggle', label:'Старт / пауза таймера', group:'Время', key:'Space'},
    {id:'timerPlus', label:'Добавить 10 секунд', group:'Время', key:'Shift+Equal', aliases:['NumpadAdd']},
    {id:'timerMinus', label:'Убрать 10 секунд', group:'Время', key:'Minus', aliases:['NumpadSubtract']},
    {id:'redPlus1', label:'Красному +1 очко', group:'Красный', key:'KeyQ'},
    {id:'redPlus2', label:'Красному +2 очка', group:'Красный', key:'KeyW'},
    {id:'redMinus1', label:'Красному −1 очко', group:'Красный', key:'KeyA'},
    {id:'redMinus2', label:'Красному −2 очка', group:'Красный', key:'KeyS'},
    {id:'bluePlus1', label:'Синему +1 очко', group:'Синий', key:'KeyP'},
    {id:'bluePlus2', label:'Синему +2 очка', group:'Синий', key:'KeyO'},
    {id:'blueMinus1', label:'Синему −1 очко', group:'Синий', key:'KeyL'},
    {id:'blueMinus2', label:'Синему −2 очка', group:'Синий', key:'KeyK'},
    {id:'undo', label:'Отменить последнее действие', group:'Общие действия', key:'Ctrl+KeyZ'},
    {id:'next', label:'Следующий бой', group:'Общие действия', key:'Ctrl+Enter'},
  ]);
  const ACTION_IDS = new Set(ACTIONS.map(action => action.id));
  const MODIFIERS = ['Ctrl','Alt','Shift'];
  const MODIFIER_CODES = new Set(['ControlLeft','ControlRight','ShiftLeft','ShiftRight','AltLeft','AltRight','MetaLeft','MetaRight']);
  const BLOCKED_MODIFIER_COMBOS = new Set([
    'Ctrl+KeyL','Ctrl+KeyP','Ctrl+KeyQ','Ctrl+KeyR','Ctrl+KeyT','Ctrl+KeyW',
    'Ctrl+KeyN','Ctrl+KeyS','Ctrl+KeyA','Ctrl+KeyF','Ctrl+KeyD','Ctrl+KeyH',
    'Ctrl+KeyJ','Ctrl+KeyU','Ctrl+KeyC','Ctrl+KeyV','Ctrl+KeyX',
    'Ctrl+Shift+KeyT','Ctrl+Shift+KeyN','Ctrl+Shift+KeyL',
    'Alt+F4','Alt+ArrowLeft','Alt+ArrowRight',
  ]);

  function normalize(input) {
    if (typeof input !== 'string') return null;
    const parts = input.split('+');
    const code = parts.pop();
    if (!code || !/^(Key[A-Z]|Digit[0-9]|Numpad(?:[0-9]|Add|Subtract|Multiply|Divide|Decimal|Enter)|F(?:[1-9]|1[0-2])|Space|Enter|Tab|Backspace|Delete|Insert|Home|End|PageUp|PageDown|Arrow(?:Up|Down|Left|Right)|Equal|Minus|BracketLeft|BracketRight|Backslash|Semicolon|Quote|Comma|Period|Slash|Backquote)$/.test(code)) return null;
    if (new Set(parts).size !== parts.length || parts.some(p => !MODIFIERS.includes(p))) return null;
    return [...MODIFIERS.filter(p => parts.includes(p)), code].join('+');
  }
  function isBlocked(combo) {
    if (!combo || BLOCKED_MODIFIER_COMBOS.has(combo)) return true;
    const code = combo.split('+').pop();
    if (code === 'Tab' || /^F(?:[1-9]|1[0-2])$/.test(code)) return true;
    // Системные сочетания (например, закрытие окна) нельзя использовать как команды.
    if (combo.includes('Alt+') && (code === 'Tab' || code === 'F4')) return true;
    return false;
  }
  function combinationFromEvent(event) {
    if (event.isComposing || event.key === 'Dead' || event.keyCode === 229 || event.metaKey) return null;
    if (MODIFIER_CODES.has(event.code)) return null;
    return normalize([...MODIFIERS.filter(mod => event[mod.toLowerCase()+'Key']), event.code].join('+'));
  }
  function defaults() { return Object.fromEntries(ACTIONS.map(action => [action.id, action.key])); }
  function aliasesFor(action, bindings) {
    // Альтернативы (+/- на NumPad) действуют только пока не переназначена команда.
    return bindings[action.id] === action.key ? (action.aliases || []) : [];
  }
  function activeKeys(action, bindings) { return [bindings[action.id], ...aliasesFor(action, bindings)]; }
  function validation(id, combo, bindings) {
    if (!ACTION_IDS.has(id) || !normalize(combo) || isBlocked(combo)) return 'Сочетание недоступно или зарезервировано браузером.';
    for (const action of ACTIONS) {
      if (action.id !== id && activeKeys(action, bindings).includes(combo)) {
        return `Сочетание уже назначено: ${action.label}.`;
      }
    }
    return null;
  }
  function validSettings(value) {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return false;
    if (Object.keys(value).length !== ACTIONS.length) return false;
    for (const action of ACTIONS) {
      if (normalize(value[action.id]) !== value[action.id] || isBlocked(value[action.id])) return false;
    }
    return ACTIONS.every(action => !validation(action.id, value[action.id], value));
  }
  function safeStorage() {
    try { return global.localStorage; }
    catch { return {getItem:() => null, setItem:() => {}}; }
  }
  function readSettings(storage) {
    try {
      const saved = JSON.parse(storage.getItem(STORAGE_KEY));
      return validSettings(saved) ? saved : defaults();
    } catch { return defaults(); }
  }
  function labelKey(combination) {
    const parts = combination.split('+');
    const code = parts.pop();
    const labels = {Space:'Пробел',Equal:'=',Minus:'-',Enter:'Enter',NumpadAdd:'Num +',NumpadSubtract:'Num −'};
    const keyLabel = code.startsWith('Key') ? code.slice(3) : code.startsWith('Digit') ? code.slice(5) : (labels[code] || code.replace(/^Numpad/, 'Num '));
    if (combination === 'Shift+Equal') return '+';
    return [...parts, keyLabel].join(' + ');
  }
  function isTyping(target) {
    return !!target?.closest?.('input, textarea, select, [contenteditable], [contenteditable="true"], [role="textbox"]');
  }
  function otherDialogOpen() {
    return !!document.querySelector('[role="dialog"], .correction-overlay, dialog[open], #matchCorrectionOverlay');
  }

  class SecretaryHotkeys {
    constructor(onAction, storage = null) {
      this.onAction = onAction;
      this.storage = storage || safeStorage();
      this.bindings = readSettings(this.storage);
      this.panel = null;
      this.capture = null;
      this.candidate = null;
      this.targetAction = null;
      this.lastTrigger = null;
      this.boundKeydown = event => this.handleKeydown(event);
      document.addEventListener('keydown', this.boundKeydown, true);
    }
    destroy() {
      document.removeEventListener('keydown', this.boundKeydown, true);
      this.capture?.remove(); this.panel?.remove();
      this.capture = null; this.panel = null;
    }
    persist() {
      try { this.storage.setItem(STORAGE_KEY, JSON.stringify(this.bindings)); }
      catch { /* Запрет localStorage не должен ломать секретаря. */ }
    }
    assign(id, combo) {
      const error = validation(id, combo, this.bindings);
      if (error) return error;
      this.bindings = {...this.bindings, [id]:combo};
      this.persist();
      return null;
    }
    reset() { this.bindings = defaults(); this.persist(); this.renderPanel(); }
    resolve(combo) {
      let action = ACTIONS.find(item => activeKeys(item, this.bindings).includes(combo));
      // Shift для буквы может означать только регистр. Явное Shift+... всегда
      // имеет приоритет; иначе разрешаем обычную буквенную команду.
      if (!action && /(?:^|\+)Shift\+Key[A-Z]$/.test(combo)) {
        const withoutShift = combo.replace(/(^|\+)Shift\+/, '$1');
        action = ACTIONS.find(item => activeKeys(item, this.bindings).includes(withoutShift));
      }
      return action?.id || null;
    }
    handleKeydown(event) {
      if (event.defaultPrevented || event.repeat || event.isComposing) return;
      if (this.capture) { this.captureKeydown(event); return; }
      if (this.panel) {
        if (event.code === 'Escape') { event.preventDefault(); this.closePanel(); }
        return;
      }
      if (otherDialogOpen() || isTyping(event.target)) return;
      const combo = combinationFromEvent(event);
      const action = combo ? this.resolve(combo) : null;
      if (!action) return;
      // Обычные браузерные функции не блокируются, когда команда недоступна.
      if (!this.onAction(action)) return;
      event.preventDefault();
      event.stopPropagation();
    }
    openPanel(trigger = null) {
      if (this.panel) { this.closePanel(); return; }
      this.lastTrigger = trigger;
      const overlay = document.createElement('div');
      overlay.id = 'secretaryHotkeysPanel';
      overlay.className = 'secretary-shortcut-overlay';
      overlay.innerHTML = `<section class="secretary-shortcut-dialog" role="dialog" aria-modal="true" aria-labelledby="secretaryShortcutsTitle">
        <div class="secretary-shortcut-heading"><div><h2 id="secretaryShortcutsTitle">Горячие клавиши</h2><p>Нажмите на назначение, чтобы изменить его.</p></div><button type="button" class="secretary-shortcut-close" aria-label="Закрыть окно" title="Закрыть"><svg aria-hidden="true" viewBox="0 0 24 24" focusable="false"><path d="M18 6 6 18M6 6l12 12"/></svg></button></div>
        <div id="secretaryShortcutsRows"></div><div class="secretary-shortcut-footer"><button type="button" id="secretaryShortcutsReset">Сбросить по умолчанию</button><button type="button" class="primary" id="secretaryShortcutsDone">Закрыть</button></div>
      </section>`;
      document.body.appendChild(overlay);
      this.panel = overlay;
      overlay.querySelector('.secretary-shortcut-close').onclick = () => this.closePanel();
      overlay.querySelector('#secretaryShortcutsDone').onclick = () => this.closePanel();
      overlay.querySelector('#secretaryShortcutsReset').onclick = () => {
        if (global.confirm('Восстановить горячие клавиши по умолчанию?')) this.reset();
      };
      overlay.addEventListener('click', event => { if (event.target === overlay) this.closePanel(); });
      this.renderPanel();
      overlay.querySelector('.secretary-shortcut-close').focus();
    }
    closePanel() {
      this.closeCapture(); this.panel?.remove(); this.panel = null;
      this.lastTrigger?.focus?.();
    }
    renderPanel() {
      if (!this.panel) return;
      const holder = this.panel.querySelector('#secretaryShortcutsRows');
      // Данные команд фиксированы, назначения проверяются normalize() — в HTML нет пользовательского ввода.
      holder.innerHTML = ACTIONS.map((action, index) => {
        const heading = index === 0 || ACTIONS[index-1].group !== action.group ? `<h3>${action.group}</h3>` : '';
        return `${heading}<div class="secretary-shortcut-row"><span>${action.label}</span><button type="button" class="secretary-shortcut-key" data-shortcut-action="${action.id}" title="Переназначить">${labelKey(this.bindings[action.id])}</button></div>`;
      }).join('');
      holder.querySelectorAll('[data-shortcut-action]').forEach(button => {
        button.onclick = () => this.openCapture(button.dataset.shortcutAction);
      });
    }
    openCapture(id) {
      if (!ACTION_IDS.has(id) || !this.panel || this.capture) return;
      this.targetAction = id; this.candidate = null;
      const overlay = document.createElement('div');
      overlay.id = 'secretaryHotkeyCapture';
      overlay.className = 'secretary-shortcut-overlay secretary-shortcut-capture-layer';
      overlay.innerHTML = `<section class="secretary-shortcut-capture" role="dialog" aria-modal="true" aria-labelledby="secretaryCaptureTitle">
        <h2 id="secretaryCaptureTitle">Нажмите клавишу или сочетание клавиш</h2>
        <p>Клавиши будут распознаны независимо от русской или английской раскладки.</p>
        <div class="secretary-shortcut-preview" id="secretaryCapturePreview" aria-live="polite">Ожидание нажатия…</div>
        <p class="secretary-shortcut-error" id="secretaryCaptureError" role="alert"></p>
        <div class="secretary-shortcut-footer"><button type="button" id="secretaryCaptureCancel">Отмена</button><button type="button" class="primary" id="secretaryCaptureSave" disabled>Сохранить</button></div>
      </section>`;
      document.body.appendChild(overlay);
      this.capture = overlay;
      overlay.querySelector('#secretaryCaptureCancel').onclick = () => this.closeCapture();
      overlay.querySelector('#secretaryCaptureSave').onclick = () => {
        if (!this.candidate) return;
        const error = this.assign(this.targetAction, this.candidate);
        if (error) { this.showCandidate(this.candidate); return; }
        this.closeCapture(); this.renderPanel();
      };
      overlay.addEventListener('click', event => { if (event.target === overlay) this.closeCapture(); });
      overlay.querySelector('#secretaryCaptureCancel').focus();
    }
    closeCapture() {
      const id = this.targetAction;
      this.capture?.remove(); this.capture = null; this.candidate = null; this.targetAction = null;
      if (id) this.panel?.querySelector(`[data-shortcut-action="${id}"]`)?.focus();
    }
    showCandidate(combo) {
      const error = validation(this.targetAction, combo, this.bindings);
      this.candidate = error ? null : combo;
      this.capture.querySelector('#secretaryCapturePreview').textContent = combo ? labelKey(combo) : 'Недопустимая клавиша';
      this.capture.querySelector('#secretaryCaptureError').textContent = error || '';
      this.capture.querySelector('#secretaryCaptureSave').disabled = !!error;
    }
    captureKeydown(event) {
      // В модальном режиме блокируются и основные горячие клавиши, и действия браузера.
      event.preventDefault(); event.stopPropagation();
      if (event.code === 'Escape' && !event.ctrlKey && !event.altKey && !event.shiftKey) { this.closeCapture(); return; }
      if (event.repeat || MODIFIER_CODES.has(event.code)) return;
      this.showCandidate(combinationFromEvent(event));
    }
  }

  global.SecretaryHotkeys = SecretaryHotkeys;
  // Экспорт логики отдельно позволяет тестировать клавиатуру без DOM и браузера.
  global.SecretaryHotkeyConfig = Object.freeze({ACTIONS, STORAGE_KEY, defaults, normalize, combinationFromEvent, validation, validSettings, labelKey});
})(window);
