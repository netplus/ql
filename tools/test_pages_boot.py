#!/usr/bin/env python3
"""Synthetic startup failure tests, injected into Chromium; not an HTTP/SRI test."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright


def run(candidate: Path, browser_path: str) -> dict:
    manifest=json.loads((candidate/'release.manifest.json').read_text())
    boot=(candidate/manifest['entrypoints']['start.js']).read_text()
    html='''<html><head><meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; connect-src 'none'"></head><body><section id="boot-status" role="status"><span id="boot-text">starting</span><button id="boot-retry" hidden>retry</button></section><p id="bundle-message"></p></body></html>'''
    checks=[]
    cases={
        'missing_loader':"",
        'throws_on_start':"window.QLRelease={start(){throw new Error('synthetic')}};",
        'empty_shell_ready':"window.QLRelease={start(){}};",
        'app_loading':"window.QLRelease={start(fn){fn();}};",
        'resource_failure':"window.QLRelease={start(fn){fn();}};",
        'runtime_failure':"window.QLRelease={start(fn){fn();}};",
        'resource_success':"window.QLRelease={start(fn){fn();}};",
        'startup_timeout':"window.QLRelease={start(fn){fn();}};",
        'launch_once':"window.QLRelease={start(fn){fn();fn();}};",
    }
    # Explicit stubs: app resources are not fetched or executed, storage untouched.
    harness="""window.added=[];window.timers=[];window.timerClears=0;
const originalAppend=document.body.appendChild.bind(document.body);
document.body.appendChild=(el)=>{if(el.tagName==='SCRIPT'&&el.src){window.added.push(el);return el;}return originalAppend(el);};
window.setTimeout=(fn)=>{window.timers.push(fn);return window.timers.length;};
window.clearTimeout=()=>window.timerClears++;
"""
    with sync_playwright() as p:
        browser=p.chromium.launch(executable_path=browser_path,headless=True,args=['--no-sandbox'])
        version=browser.version
        for name,stub in cases.items():
            context=browser.new_context()
            page=context.new_page();requests=[]
            page.on('request',lambda r:requests.append(r.url))
            page.set_content(html)
            page.add_script_tag(content=harness+stub)
            page.add_script_tag(content=boot)
            if name=='resource_failure':page.evaluate("added[0].dispatchEvent(new Event('error'))")
            if name=='runtime_failure':
                page.evaluate("dispatchEvent(new ErrorEvent('error',{filename:added[0].src,message:'synthetic'}));added[0].dispatchEvent(new Event('load'))")
            if name=='resource_success':page.evaluate("added[0].dispatchEvent(new Event('load'))")
            if name=='startup_timeout':page.evaluate("timers[0]()")
            state=page.evaluate("""({hidden:document.getElementById('boot-status').hidden,role:document.getElementById('boot-status').getAttribute('role'),retry:!document.getElementById('boot-retry').hidden,text:document.getElementById('boot-text').textContent,count:added.length,integrity:added[0]?.integrity||null,clears:timerClears})""")
            if name in ('missing_loader','throws_on_start','resource_failure','runtime_failure','startup_timeout'):
                assert not state['hidden'] and state['role']=='alert' and state['retry'],(name,state)
                assert '未被删除' in state['text']
            if name in ('empty_shell_ready','resource_success'):
                assert state['hidden'],(name,state)
            if name in ('app_loading','launch_once'):
                assert not state['hidden'] and state['count']==1,(name,state)
            if state['count']:
                assert state['integrity'].startswith('sha256-'),(name,state)
            assert not requests,(name,requests)
            checks.append({'case':name,'passed':True,'external_requests':len(requests)})
            context.close()
        browser.close()
    return {'scope':'Synthetic boot control-flow only; script loading mocked; no HTTP, SRI enforcement, storage, or device acceptance',
            'browser':version,'checks':checks,'passed':len(checks),'browser_navigation_verified':False}


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate',type=Path,required=True)
    parser.add_argument('--browser',default='/usr/bin/chromium')
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.candidate,args.browser)
    with args.output.open('x',encoding='utf-8') as f:json.dump(result,f,ensure_ascii=False,indent=2);f.write('\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
