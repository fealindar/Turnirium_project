"""Необязательный браузерный smoke-тест для UI версии 1.2.0.

Установка: pip install playwright. Нужен Chromium в PATH (или установленный
браузер Playwright). Запуск: python tools/verify_ui_release_120.py.
"""

from pathlib import Path
import shutil

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parents[1] / 'app/static'
chromium = shutil.which('chromium') or shutil.which('chromium-browser') or shutil.which('google-chrome')
with sync_playwright() as p:
    browser=p.chromium.launch(headless=True, executable_path=chromium, args=['--no-sandbox'])
    page=browser.new_page(viewport={'width':1200,'height':900})
    page.set_content('<div id="areaTitle"></div><div id="secretaryContent"></div>')
    page.evaluate('''() => {
      window.$ = (s) => document.querySelector(s); window.$$ = (s, el=document) => [...el.querySelectorAll(s)];
      window.esc = (s) => String(s ?? ''); window.fmtTime=()=> '03:00'; window.formatName=()=> 'Группы';
      window.affiliation=()=> ''; window.statusText=()=> 'Ожидает'; window.stageName=()=> 'Группа';
      window.bindMatchCorrectionButtons = () => {};window.matchTitle=()=> 'Бой';
      window.__calls=[]; window.api=async (p,o) => {window.__calls.push({path:p, payload:JSON.parse(o.body)}); return {status:'finished'};};
      window.toast=(s)=>{ window.__toast=s; };
      window.__match={id:12,category_name:'Проверка',category_format:'groups',stage:'group',group_name:'A',round_no:1,
        red:{cp_id:30,name:'Красный'},blue:{cp_id:40,name:'Синий'}, red_score:3,blue_score:5,
        red_warnings:0,blue_warnings:0,status:'ready',remaining_ms:180000,timer_running:false,
        score_buttons:[{label:'+1',delta:1}],pending_penalties:{}};
      window.show = (penalties, status='ready') => {
        window.__match.pending_penalties=penalties;
        window.__match.status=status;
        renderSecretary({area:{id:3,name:'Площадка 3'},current:window.__match,queue:[],next:null,following:null},3,[]);
      };
    }''')
    page.add_script_tag(path=str(root/'secretary.js'))
    page.evaluate('show({})')
    assert page.locator('#finishFight').count()==0
    page.get_by_role('button',name='Победа красного по счёту').click()
    assert page.evaluate('window.__calls.at(-1)') == {'path':'/api/matches/12/finish','payload':{'winner_cp_id':30,'reason':'POINTS'}}
    page.evaluate('show({})')
    page.get_by_role('button',name='Ничья').click()
    assert page.evaluate('window.__calls.at(-1).payload') == {'winner_cp_id':None,'reason':'DRAW'}
    page.evaluate("show({red:'TECHNICAL_LOSS',blue:'TECHNICAL_LOSS'})")
    assert page.locator('#finishFight').count()==1
    assert page.get_by_role('button',name='Победа красного по счёту').is_disabled()
    page.locator('#finishFight').click()
    assert page.evaluate('window.__calls.at(-1).payload') == {'winner_cp_id':None,'reason':'DOUBLE_TECHNICAL_LOSS'}
    page.evaluate("show({blue:'WARNING_FORFEIT'})")
    page.locator('#finishFight').click()
    assert page.evaluate('window.__calls.at(-1).payload') == {'winner_cp_id':30,'reason':'WARNING_FORFEIT'}
    page.evaluate("show({red:'DISQUALIFICATION',blue:'DISQUALIFICATION'})")
    page.locator('#finishFight').click()
    assert page.evaluate('window.__calls.at(-1).payload') == {'winner_cp_id':None,'reason':'DOUBLE_DISQUALIFICATION'}
    page.evaluate('show({}, "finished")')
    assert page.locator('#finishFight').count()==0
    assert page.locator('[data-win]').count()==0
    print('SECRETARY BROWSER: immediate points/draw, delayed single/double penalties, finished mode OK')

    pg=browser.new_page(viewport={'width':800,'height':550})
    pg.set_content('<div id="section"></div>')
    pg.evaluate('''() => {
      window.$ = (s) => document.querySelector(s); window.$$ = (s, el=document) => [...el.querySelectorAll(s)];
      window.esc=(s)=>String(s ?? '').replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('"','&quot;');
      window.adminState={tournamentId:1,schedule:{areas:[{area:{id:23,name:'Площадка 23',enabled:true}}]}};
      window.__calls=[];window.api=(path,options)=>{window.__calls.push({path,payload:JSON.parse(options.body)});return new Promise(()=>{});};
      window.toast=()=>{};
    }''')
    pg.add_script_tag(path=str(root/'schedule.js'))
    pg.evaluate('''() => {
      document.querySelector('#section').innerHTML=quickAssignButtons({category_id:9,ready_unassigned:6,groups:[]});
      bindQuickMultiAssignment();
    }''')
    assert pg.locator('[data-quick-category]').count() == 0
    trigger=pg.get_by_role('button',name='Распределить по площадкам')
    trigger.click()
    pg.get_by_role('checkbox',name='Площадка 23').check()
    pg.get_by_role('button',name='Подтвердить распределение').click()
    assert pg.evaluate('window.__calls.at(-1)')=={'path':'/api/tournaments/1/schedule-assign-multi','payload':{'category_id':9,'group_name':'','area_ids':[23]}}
    print('SCHEDULE BROWSER: single area multiselect produces API request OK')
    browser.close()
