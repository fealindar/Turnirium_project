"""Хотфикс 1.2.2: актуальные ресурсы и мгновенная смена сторон табло."""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.main import FRONTEND_REVISION, app
from app.version import APP_VERSION

ROOT = Path(__file__).resolve().parents[1]


def test_hotfix_keeps_122_and_never_serves_unversioned_frontend():
    assert APP_VERSION == "1.2.2"
    with TestClient(app) as client:
        for page in ("/mat/1", "/board/1", "/admin"):
            response = client.get(page)
            assert response.status_code == 200
            assert response.headers["cache-control"] == "no-store"
            assert f'window.TURNIRIUM_FRONTEND_REVISION="{FRONTEND_REVISION}"' in response.text
            assert f'/static/board.js?v={FRONTEND_REVISION}' in response.text
            assert f'/static/secretary.js?v={FRONTEND_REVISION}' in response.text
            assert f'/static/secretary-board.css?v={FRONTEND_REVISION}' in response.text
            # Нельзя оставлять ни одну CSS/JS ссылку без версии.
            assert not re.search(r'(?:src|href)="/static/[^"?]+\.(?:css|js)"', response.text)
        script = client.get(f'/static/board.js?v={FRONTEND_REVISION}')
        assert script.status_code == 200
        assert "loadRevision" in script.text


def test_area_state_exposes_frontend_revision():
    # Не требует площадки: проверяет объявленную ревизию на уровне app.state.
    assert app.state.frontend_revision == FRONTEND_REVISION
    assert len(FRONTEND_REVISION) == 16
    assert all(c in "0123456789abcdef" for c in FRONTEND_REVISION)


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js не установлен")
def test_board_ws_mirror_event_updates_without_waiting_for_http_poll():
    """На событие реагируем в том же такте JS, даже если GET завис."""
    script = r'''
const fs=require('fs'),vm=require('vm');
const state={frontend_revision:'revision',area:{name:'Area',board_mirrored:false},
 current:{red:{name:'Red'},blue:{name:'Blue'},red_score:5,blue_score:3,
 red_warnings:1,blue_warnings:2,status:'in_progress',timer_running:false,
 category_name:'Test',stage:'group',remaining_ms:30000},next:null};
let html='',getCalls=0,eventCallback=null,reloads=0;
const elements={
 '#app':{set innerHTML(value){this._html=value}},
 '#unlockBtn':{},
 '#unlock':{classList:{add(){}}},
 '#boardContent':{set innerHTML(value){html=value},get innerHTML(){return html}},
 '#boardTimer':{textContent:''},
};
const ctx={
 $:(selector)=>elements[selector],
 document:{body:{className:''},documentElement:{requestFullscreen:()=>Promise.resolve()}},
 window:{TURNIRIUM_FRONTEND_REVISION:'revision',AudioContext:function(){}},
 location:{reload:()=>{reloads++}},
 ensureBranding:()=>{},
 api:async()=>{getCalls++;return {...state,area:{...state.area}}},
 wsConnect:(callback)=>{eventCallback=callback},
 setTimerSnapshot:()=>{},clearInterval:()=>{},setInterval:()=>1,
 esc:(value)=>String(value??''),fighterText:(x)=>x?.name||'—',
 affiliation:()=>'',fmtTime:()=> '00:30',stageName:()=>'',
 console,
};
vm.createContext(ctx);
vm.runInContext(fs.readFileSync('app/static/board.js','utf8'),ctx);
(async()=>{
 await ctx.initBoard(1);
 if(!eventCallback)throw Error('WebSocket callback missing');
 if(html.indexOf('class="board-side red"')>html.indexOf('class="board-side blue"'))throw Error('wrong initial sides');
 eventCallback({type:'area_changed',area_id:1,board_mirrored:true});
 if(html.indexOf('class="board-side red"')<html.indexOf('class="board-side blue"'))throw Error('WS did not mirror immediately');
 eventCallback({type:'area_changed',area_id:1,board_mirrored:false});
 if(html.indexOf('class="board-side red"')>html.indexOf('class="board-side blue"'))throw Error('WS did not restore immediately');
 await Promise.resolve();
 if(getCalls<3||reloads!==0)throw Error('bad reload/update behavior');
})().catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


@pytest.mark.skipif(shutil.which("node") is None, reason="Node.js не установлен")
def test_open_board_reloads_if_server_has_new_frontend_revision():
    script = r'''
const fs=require('fs'),vm=require('vm');
let reloads=0,rendered=false;
const els={
 '#app':{set innerHTML(x){}},'#unlockBtn':{},
 '#boardContent':{set innerHTML(x){rendered=true}}
};
const ctx={
 $:(x)=>els[x],document:{body:{},documentElement:{}},
 window:{TURNIRIUM_FRONTEND_REVISION:'old-build'},
 location:{reload:()=>reloads++},ensureBranding:()=>{},
 api:async()=>({frontend_revision:'new-build',current:null}),
 clearInterval:()=>{},setInterval:()=>1,
 wsConnect:()=>{},console,
};
vm.createContext(ctx);vm.runInContext(fs.readFileSync('app/static/board.js','utf8'),ctx);
ctx.initBoard(1).then(()=>{
 if(reloads!==1 || rendered) throw Error('Old board did not reload before rendering stale data');
}).catch(e=>{console.error(e);process.exitCode=1});
'''
    result = subprocess.run(["node", "-e", script], cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
