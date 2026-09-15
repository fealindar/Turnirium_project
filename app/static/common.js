const $ = (s, root=document) => root.querySelector(s);
const $$ = (s, root=document) => [...root.querySelectorAll(s)];
const esc = (v='') => String(v ?? '').replace(/[&<>'"]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;',"'":'&#39;','"':'&quot;'}[c]));

let BRANDING={app_name:'Turnirium',developer_club_name:'',developer_club_url:'',show_footer_branding:true};
function brandIconHtml(extraClass=''){return `<img class="brand-icon ${extraClass}" src="/static/turnirium_icon.png" alt="" aria-hidden="true">`}
function safeBrandUrl(){const u=(BRANDING.developer_club_url||'').trim();return /^https?:\/\//i.test(u)?u:''}
function ensureBranding(){
  document.title=BRANDING.app_name||'Turnirium';
  let el=$('#brandingFooter');
  if(!BRANDING.show_footer_branding || !BRANDING.developer_club_name){if(el)el.remove();return;}
  if(!el){el=document.createElement('div');el.id='brandingFooter';el.className='app-brand-footer';document.body.appendChild(el)}
  const url=safeBrandUrl(),name=esc(BRANDING.developer_club_name);
  el.innerHTML=`<span>${esc(BRANDING.app_name)}</span><span class="brand-sep">·</span>${url?`<a href="${esc(url)}" target="_blank" rel="noopener">${name}</a>`:`<span>${name}</span>`}`;
}
async function loadBranding(){try{BRANDING=await api('/api/branding')}catch{}ensureBranding()}

async function api(path, options={}) {
  const opts = {...options, headers:{'Content-Type':'application/json', ...(options.headers||{})}};
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `${r.status} ${r.statusText}`;
    try { const j = await r.json(); msg = j.detail || msg; } catch {}
    throw new Error(msg);
  }
  const text = await r.text();
  return text ? JSON.parse(text) : null;
}
function downloadUrl(url){
  const a=document.createElement('a');a.href=url;a.download='';a.style.display='none';document.body.appendChild(a);a.click();setTimeout(()=>a.remove(),1000);
}
function toast(msg, error=false) {
  const el = $('#toast'); el.textContent = msg; el.className = `toast show${error?' error':''}`;
  clearTimeout(window.__toast); window.__toast=setTimeout(()=>el.className='toast', 3200);
}
function fmtTime(ms) {
  ms = Math.max(0, Math.round(ms));
  const total = Math.ceil(ms/1000), m=Math.floor(total/60), s=total%60;
  return `${String(m).padStart(2,'0')}:${String(s).padStart(2,'0')}`;
}
function stageName(m) {
  if (m.is_third_place) return 'Бой за 3-е место';
  if (m.stage==='group') return `Группа ${m.group_name}`;
  if (m.stage==='round_robin') return 'Все со всеми';
  if (m.stage==='swiss') return `Swiss · тур ${m.round_no}`;
  if (m.stage==='playoff') return `Плей-офф · раунд ${m.round_no}`;
  return `Раунд ${m.round_no}`;
}
function affiliation(f) { return [f?.club, f?.city].filter(Boolean).join(' · '); }
function fighterText(f) { return f ? `${f.name}${affiliation(f) ? ' · '+affiliation(f) : ''}` : '—'; }
function matchTitle(m) { return `#${m.match_no} · ${m.category_name} · ${fighterText(m.red)} — ${fighterText(m.blue)}`; }
function statusText(s){ return ({draft:'черновик',staged:'состав редактируется',blocked:'ожидает участников',pending:'ожидает',ready:'готов',in_progress:'идёт',finished:'завершён',completed:'завершена',active:'активен',withdrawn:'выбыл'})[s]||s; }
function reasonText(r){ return ({POINTS:'По счёту',DRAW:'Ничья',TECHNICAL_LOSS:'Техническое поражение',WARNING_FORFEIT:'Поражение по предупреждениям',DISQUALIFICATION:'Дисквалификация',WITHDRAWAL:'Участник выбыл',BYE:'Автопроход'})[r]||r||''; }


async function openMatchCorrection(matchId,onDone=()=>{}){
  let m;try{m=await api(`/api/matches/${matchId}`)}catch(e){toast(e.message,true);return}
  if(m.status!=='finished'){toast('Корректировка доступна только для завершенного боя',true);return}
  $('#matchCorrectionOverlay')?.remove();
  const option=(value,label,selected)=>`<option value="${value}" ${selected?'selected':''}>${esc(label)}</option>`;
  const resultKey=(()=>{
    if(m.reason==='DRAW')return 'draw';
    if(m.reason==='TECHNICAL_LOSS')return m.winner_cp_id===m.red?.cp_id?'blue-tech':'red-tech';
    if(m.reason==='WARNING_FORFEIT')return m.winner_cp_id===m.red?.cp_id?'blue-warning':'red-warning';
    if(m.reason==='DISQUALIFICATION')return m.winner_cp_id===m.red?.cp_id?'blue-dsq':'red-dsq';
    if(m.reason==='WITHDRAWAL')return m.winner_cp_id===m.red?.cp_id?'blue-withdraw':'red-withdraw';
    return m.winner_cp_id===m.blue?.cp_id?'blue-points':'red-points';
  })();
  const overlay=document.createElement('div');overlay.id='matchCorrectionOverlay';overlay.className='correction-overlay';
  overlay.innerHTML=`<div class="correction-dialog"><div class="correction-head"><div><h2>Исправление завершенного боя</h2><p>${esc(m.category_name)} · ${esc(stageName(m))} · бой #${m.match_no}</p></div><button type="button" class="icon-btn" id="closeCorrection">×</button></div>
    <div class="correction-warning">Исправление сохраняется в журнале. Если результат влияет на еще не начатую следующую стадию, приложение пересчитает или сбросит её безопасным образом.</div>
    <form id="matchCorrectionForm" class="stack">
      <div class="correction-sides"><div class="correction-side red"><b>${esc(m.red?.name||'—')}</b><small>${esc(affiliation(m.red))}</small><label>Счёт<input type="number" name="red_score" value="${m.red_score}"></label><label>Предупреждения<input type="number" min="0" name="red_warnings" value="${m.red_warnings}"></label></div>
      <div class="correction-side blue"><b>${esc(m.blue?.name||'—')}</b><small>${esc(affiliation(m.blue))}</small><label>Счёт<input type="number" name="blue_score" value="${m.blue_score}"></label><label>Предупреждения<input type="number" min="0" name="blue_warnings" value="${m.blue_warnings}"></label></div></div>
      <div class="field"><label>Итог боя</label><select name="result">
        ${option('red-points','Победа красного по счёту',resultKey==='red-points')}
        ${option('blue-points','Победа синего по счёту',resultKey==='blue-points')}
        ${['group','swiss','round_robin'].includes(m.stage)?option('draw','Ничья',resultKey==='draw'):''}
        ${option('red-tech','Техническое поражение красного',resultKey==='red-tech')}
        ${option('blue-tech','Техническое поражение синего',resultKey==='blue-tech')}
        ${option('red-warning','Поражение красного по предупреждениям',resultKey==='red-warning')}
        ${option('blue-warning','Поражение синего по предупреждениям',resultKey==='blue-warning')}
        ${option('red-dsq','Дисквалификация красного',resultKey==='red-dsq')}
        ${option('blue-dsq','Дисквалификация синего',resultKey==='blue-dsq')}
        ${option('red-withdraw','Красный выбыл',resultKey==='red-withdraw')}
        ${option('blue-withdraw','Синий выбыл',resultKey==='blue-withdraw')}
      </select></div>
      <div class="row correction-actions"><button type="button" id="cancelCorrection">Отмена</button><button class="primary">Сохранить исправление</button></div>
    </form></div>`;
  document.body.appendChild(overlay);
  const close=()=>overlay.remove();$('#closeCorrection',overlay).onclick=close;$('#cancelCorrection',overlay).onclick=close;overlay.onclick=e=>{if(e.target===overlay)close()};
  $('#matchCorrectionForm',overlay).onsubmit=async e=>{e.preventDefault();const fd=new FormData(e.target),r=String(fd.get('result')),red=m.red?.cp_id||null,blue=m.blue?.cp_id||null;let winner=null,reason='POINTS';
    if(r==='red-points'){winner=red;reason='POINTS'}else if(r==='blue-points'){winner=blue;reason='POINTS'}else if(r==='draw'){winner=null;reason='DRAW'}else if(r==='red-tech'){winner=blue;reason='TECHNICAL_LOSS'}else if(r==='blue-tech'){winner=red;reason='TECHNICAL_LOSS'}else if(r==='red-warning'){winner=blue;reason='WARNING_FORFEIT'}else if(r==='blue-warning'){winner=red;reason='WARNING_FORFEIT'}else if(r==='red-dsq'){winner=blue;reason='DISQUALIFICATION'}else if(r==='blue-dsq'){winner=red;reason='DISQUALIFICATION'}else if(r==='red-withdraw'){winner=blue;reason='WITHDRAWAL'}else if(r==='blue-withdraw'){winner=red;reason='WITHDRAWAL'}
    const payload={red_score:Number(fd.get('red_score')),blue_score:Number(fd.get('blue_score')),red_warnings:Number(fd.get('red_warnings')),blue_warnings:Number(fd.get('blue_warnings')),winner_cp_id:winner,reason};
    if(!confirm('Сохранить исправленный результат? Изменение будет записано в журнал.'))return;
    try{const res=await api(`/api/matches/${m.id}/correction`,{method:'PUT',body:JSON.stringify(payload)});close();if(res.notes?.length)toast(res.notes.join(' '));else toast('Результат исправлен');await onDone(res)}catch(err){toast(err.message,true)}
  };
}
function bindMatchCorrectionButtons(onDone=async()=>{}){$$('[data-correct-match]').forEach(b=>b.onclick=e=>{e.stopPropagation();openMatchCorrection(Number(b.dataset.correctMatch),onDone)});}

function wsScreenMeta(){
  const path=location.pathname;
  let m;
  if(path.startsWith('/admin')) return {screen:'organizer'};
  if((m=path.match(/^\/mat\/(\d+)/))) return {screen:'secretary',area_id:m[1]};
  if((m=path.match(/^\/board\/(\d+)/))) return {screen:'board',area_id:m[1]};
  if((m=path.match(/^\/public\/(\d+)/))) return {screen:'public',tournament_id:m[1]};
  return {screen:'unknown'};
}
function wsConnect(onEvent, onState=()=>{}, extraMeta={}) {
  let ws, retry, stopped=false, ping=null;
  const cleanup=()=>{
    stopped=true; clearTimeout(retry); clearInterval(ping);
    try { if(ws && ws.readyState<2) ws.close(1000,'page closing'); } catch {}
  };
  const connect=()=>{
    if(stopped)return;
    const proto = location.protocol==='https:'?'wss':'ws';
    const params=new URLSearchParams({...wsScreenMeta(),...extraMeta});
    ws = new WebSocket(`${proto}://${location.host}/ws?${params.toString()}`);
    ws.onmessage = e => {
      try {
        const payload=JSON.parse(e.data);
        if(payload.type==='database_switched' && !location.pathname.startsWith('/admin')){
          location.href='/admin';
          return;
        }
        onEvent(payload);
      } catch {}
    };
    ws.onclose = () => { clearInterval(ping); onState(false); if(!stopped){clearTimeout(retry);retry=setTimeout(connect,1300);} };
    ws.onerror = () => {};
    ws.onopen = () => { onState(true); clearInterval(ping); ping=setInterval(()=>{ if(ws.readyState===1) { try{ws.send('ping')}catch{} } },20000); };
  };
  window.addEventListener('pagehide',cleanup,{once:true});
  connect();
  return cleanup;
}


function parseScoreButtons(text) {
  return text.split(',').map(x=>x.trim()).filter(Boolean).map(x=>{
    const [label, delta] = x.split(':'); return {label:(label||'').trim(), delta:Number(delta)};
  }).filter(x=>x.label && Number.isFinite(x.delta));
}
function scoreButtonsText(items) { return (items||[]).map(x=>`${x.label}:${x.delta}`).join(', '); }
function parseWarningRules(text) {
  return text.split(',').map(x=>x.trim()).filter(Boolean).map(x=>{
    const [number,action,delta] = x.split(':');
    return {number:Number(number), action:(action||'warning').trim(), delta:Number(delta||0)};
  }).filter(x=>Number.isFinite(x.number));
}
function warningRulesText(items) { return (items||[]).map(x=>`${x.number}:${x.action}:${x.delta||0}`).join(', '); }

const adminState = { tournamentId:null, tournaments:[], participants:[], categories:[], templates:[], areas:[], selectedCategoryId:null, categoryParticipants:[], matches:[], schedule:null, runtime:null };

