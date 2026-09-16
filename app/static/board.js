// --------------------------- Табло ---------------------------
let audioCtx=null, boardWarned=new Map(), boardFinished=new Set();
function beep(freq=880,duration=.18,count=1,volume=.7){
  if(!audioCtx)return; let t=audioCtx.currentTime;
  for(let i=0;i<count;i++){
    const o=audioCtx.createOscillator(),g=audioCtx.createGain(),end=t+duration;
    o.frequency.value=freq;o.connect(g);g.connect(audioCtx.destination);
    g.gain.setValueAtTime(.0001,t);
    g.gain.exponentialRampToValueAtTime(volume,t+.01);
    g.gain.setValueAtTime(volume,Math.max(t+.01,end-.03));
    g.gain.exponentialRampToValueAtTime(.0001,end);
    o.start(t);o.stop(end+.02);t=end+.08;
  }
}
async function initBoard(areaId){
  document.body.className='board'; ensureBranding();
  $('#app').innerHTML=`<div id="unlock" class="unlock"><div class="unlock-card"><h1>Табло площадки</h1><p>Одно нажатие разрешит звук и полноэкранный режим.</p><button id="unlockBtn" class="primary">Включить табло и звук</button></div></div><div id="boardContent" class="board-shell"></div>`;
  $('#unlockBtn').onclick=()=>{audioCtx=new (window.AudioContext||window.webkitAudioContext)();audioCtx.resume();$('#unlock').classList.add('hidden');document.documentElement.requestFullscreen?.().catch(()=>{});};
  let state=null;
  const load=async()=>{try{state=await api(`/api/areas/${areaId}/state`);renderBoard(state);setTimerSnapshot(state.current)}catch(e){}};
  await load(); wsConnect(e=>{if(!e.area_id||Number(e.area_id)===Number(areaId)||e.type==='schedule_changed')load();});
  clearInterval(window.__boardPaint);window.__boardPaint=setInterval(()=>{const el=$('#boardTimer');if(!el||!state?.current)return;const rem=timerNow();el.textContent=fmtTime(rem);const m=state.current,w=(m.timer_warning_sec||0)*1000;if(w>0&&rem>0&&rem<=w&&!boardWarned.get(m.id)){boardWarned.set(m.id,true);beep(950,.2,2,.99)}if(rem<=0&&!boardFinished.has(m.id)){boardFinished.add(m.id);beep(1050,1.5,1,.99)}if(rem>w+1500)boardWarned.delete(m.id);},80);
  setInterval(load,5000);
}
function renderBoard(st){
  const m=st.current;
  if(!m){$('#boardContent').innerHTML=`<div class="board-main board-idle"><div class="board-center"><div class="board-label">${esc(st.area.name)}</div><div class="board-name">Ожидание поединка</div></div></div><div class="board-next"><div><div class="label">СЛЕДУЮЩИЙ БОЙ</div><div class="names">${st.next?esc(fighterText(st.next.red)+' — '+fighterText(st.next.blue)):'—'}</div></div></div>`;return;}
  const side=(f,score,warnings,cls,label)=>`<div class="board-side ${cls}"><div class="board-side-top"><div class="board-label">${label}</div><div class="board-name">${esc(f?.name||'—')}</div><div class="board-club">${esc(affiliation(f))}</div></div><div class="board-score">${score}</div><div class="board-side-bottom">Предупреждения: <b>${warnings}</b></div></div>`;
  $('#boardContent').innerHTML=`<div class="board-main">${side(m.red,m.red_score,m.red_warnings,'red','КРАСНЫЙ')}<div class="board-center"><div class="board-label">${esc(st.area.name)}</div><div class="timer" id="boardTimer">${fmtTime(m.remaining_ms)}</div><div class="board-status">${m.status==='finished'?'ПОЕДИНОК ЗАВЕРШЁН':m.timer_running?'ИДЁТ БОЙ':'ПАУЗА'}</div><div class="board-category">${esc(m.category_name)}<small>${esc(stageName(m))}</small></div></div>${side(m.blue,m.blue_score,m.blue_warnings,'blue','СИНИЙ')}</div><div class="board-next"><div class="next-caption"><div class="label">СЛЕДУЮЩИЙ БОЙ · ПРИГОТОВИТЬСЯ</div><div class="next-category">${st.next?esc(st.next.category_name):''}</div></div><div class="names">${st.next?`<span>${esc(st.next.red?.name||'—')}<small>${esc(affiliation(st.next.red))}</small></span><b>—</b><span>${esc(st.next.blue?.name||'—')}<small>${esc(affiliation(st.next.blue))}</small></span>`:'Очередь пуста'}</div></div>`;
}

