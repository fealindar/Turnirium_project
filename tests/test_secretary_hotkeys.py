"""Команды секретаря: раскладки клавиатуры, назначения, таймер и браузерные окна."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete

from app.db import SessionLocal, init_db
from app.engine import add_category_participant, generate_groups, start_group_stage
from app.main import app
from app.models import Area, AuditEvent, Category, CategoryParticipant, CategoryTemplate, Match, MatchEvent, Participant, Tournament

ROOT = Path(__file__).resolve().parents[1]


def test_hotkey_assets_and_action_integration():
    index = (ROOT / 'app/static/index.html').read_text(encoding='utf-8')
    js = (ROOT / 'app/static/secretary.js').read_text(encoding='utf-8')
    assert index.index('secretary-hotkeys.js') < index.index('secretary.js')
    assert 'id=\\"secretaryHotkeysButton\\"' in js or 'id="secretaryHotkeysButton"' in js
    assert 'secretaryShortcutAction' in js and "timer/adjust" in js
    assert 'data-score-side' in js


@pytest.mark.skipif(not shutil.which('node'), reason='Node.js не установлен')
def test_keyboard_layouts_rebinding_conflicts_and_editing():
    script = r'''
const assert=require('assert'),fs=require('fs'),vm=require('vm');
const events=[]; const doc={addEventListener:(type,fn)=>{if(type==='keydown')events.push(fn)}, removeEventListener:()=>{},querySelector:()=>null};
const stored={}; const storage={getItem:(key)=>stored[key]||null,setItem:(key,val)=>{stored[key]=val}};
const window={localStorage:storage};
const ctx={document:doc,window,console};vm.createContext(ctx);
vm.runInContext(fs.readFileSync('app/static/secretary-hotkeys.js','utf8'),ctx);
const config=window.SecretaryHotkeyConfig, seen=[];
const hotkeys=new window.SecretaryHotkeys(action=>{seen.push(action);return true},storage);
function fire(code, opts={}) {let prevented=false,stopped=false;
 const ev={code,key:opts.key||code,repeat:!!opts.repeat,isComposing:false,metaKey:false,ctrlKey:!!opts.ctrlKey,shiftKey:!!opts.shiftKey,altKey:!!opts.altKey,
 target:opts.target||{closest:()=>null},preventDefault:()=>{prevented=true},stopPropagation:()=>{stopped=true}};
 events[0](ev);return {prevented,stopped}; }
assert.strictEqual(fire('KeyQ',{key:'й'}).prevented,true);assert.strictEqual(seen.at(-1),'redPlus1');
fire('KeyW',{key:'ц'});assert.strictEqual(seen.at(-1),'redPlus2');
fire('KeyS',{key:'ы'});assert.strictEqual(seen.at(-1),'redMinus2');
fire('KeyO',{key:'щ'});assert.strictEqual(seen.at(-1),'bluePlus2');
fire('KeyK',{key:'л'});assert.strictEqual(seen.at(-1),'blueMinus2');
fire('KeyQ',{key:'Q',shiftKey:true});assert.strictEqual(seen.at(-1),'redPlus1'); // регистронезависимо
fire('KeyQ',{key:'q'});assert.strictEqual(seen.at(-1),'redPlus1');
fire('Equal',{key:'+',shiftKey:true});assert.strictEqual(seen.at(-1),'timerPlus');
fire('NumpadAdd',{key:'+'});assert.strictEqual(seen.at(-1),'timerPlus');
fire('Minus',{key:'-'});assert.strictEqual(seen.at(-1),'timerMinus');
fire('NumpadSubtract',{key:'-'});assert.strictEqual(seen.at(-1),'timerMinus');
fire('Enter',{ctrlKey:true});assert.strictEqual(seen.at(-1),'next');
fire('KeyZ',{ctrlKey:true});assert.strictEqual(seen.at(-1),'undo');
const previous=seen.length;
assert.strictEqual(fire('KeyQ',{repeat:true}).prevented,false);
assert.strictEqual(fire('KeyQ',{target:{closest:()=>({})}}).prevented,false);
assert.strictEqual(seen.length,previous);
assert.match(hotkeys.assign('redPlus1','KeyW'),/назначено/);
assert.match(hotkeys.assign('redPlus1','Ctrl+KeyL'),/недоступно/);
assert.strictEqual(hotkeys.assign('redPlus1','Ctrl+Shift+KeyQ'),null);
assert.strictEqual(fire('KeyQ',{ctrlKey:true,shiftKey:true}).prevented,true);
assert.strictEqual(seen.at(-1),'redPlus1');
assert.strictEqual(config.normalize('Shift+Ctrl+KeyQ'),'Ctrl+Shift+KeyQ');
assert.strictEqual(hotkeys.assign('next','Alt+Enter'),null);
assert.strictEqual(hotkeys.assign('timerToggle','Ctrl+Enter'),null); // next уже Alt+Enter
assert.notStrictEqual(hotkeys.assign('next','Ctrl+Enter'),null); // теперь занят таймером
const revived=new window.SecretaryHotkeys(()=>true,storage);
assert.strictEqual(revived.bindings.timerToggle,'Ctrl+Enter');
assert.strictEqual(revived.bindings.redPlus1,'Ctrl+Shift+KeyQ');
revived.reset();assert.strictEqual(revived.bindings.timerToggle,'Space');
assert.strictEqual(revived.bindings.redMinus2,'KeyS');
assert.strictEqual(config.validSettings(JSON.parse(stored[config.STORAGE_KEY])),true);
revived.destroy();hotkeys.destroy();
'''
    proc = subprocess.run(['node', '-e', script], cwd=ROOT, text=True, capture_output=True)
    assert proc.returncode == 0, proc.stderr


def _make_area_match():
    init_db()
    with SessionLocal() as db:
        for model in (MatchEvent, AuditEvent, Match, Area, CategoryParticipant, Participant, Category, Tournament, CategoryTemplate):
            db.execute(delete(model))
        db.commit()
        t = Tournament(name='Hotkey timers'); db.add(t); db.flush()
        area = Area(tournament_id=t.id, name='One'); db.add(area)
        cat = Category(tournament_id=t.id, name='Swords', format='groups', group_target_size=2)
        db.add(cat); db.flush()
        for idx in range(2):
            p = Participant(tournament_id=t.id,last_name=f'S{idx}')
            db.add(p); db.flush(); add_category_participant(db, cat.id, p.id)
        db.commit()
        generate_groups(db,cat); start_group_stage(db,cat)
        match = db.query(Match).filter(Match.category_id==cat.id).first()
        return match.id


def test_adjust_timer_preserves_running_and_validates_bounds():
    match_id = _make_area_match()
    with TestClient(app) as client:
        start = client.post(f'/api/matches/{match_id}/timer/start')
        assert start.status_code == 200, start.text
        initial = start.json()['remaining_ms']
        add = client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':10})
        assert add.status_code == 200, add.text
        assert add.json()['timer_running'] is True
        assert initial + 8000 <= add.json()['remaining_ms'] <= initial + 10000
        subtract = client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':-10})
        assert subtract.status_code == 200, subtract.text
        assert subtract.json()['timer_running'] is True
        assert initial - 2000 <= subtract.json()['remaining_ms'] <= initial + 1000
        for delta in (-20, 0, 100):
            assert client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':delta}).status_code == 422
        assert client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':-10}).status_code == 200
        pause = client.post(f'/api/matches/{match_id}/timer/pause')
        assert pause.status_code == 200
        paused = client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':10})
        assert paused.status_code == 200 and paused.json()['timer_running'] is False
        assert paused.json()['remaining_ms'] > pause.json()['remaining_ms']
        set_zero = client.post(f'/api/matches/{match_id}/timer/set',json={'seconds':1})
        assert set_zero.status_code == 200
        assert client.post(f'/api/matches/{match_id}/timer/start').status_code == 200
        at_zero = client.post(f'/api/matches/{match_id}/timer/adjust',json={'seconds':-10})
        assert at_zero.status_code == 200
        assert at_zero.json()['timer_running'] is False
        assert at_zero.json()['remaining_ms'] == 0
