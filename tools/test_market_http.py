#!/usr/bin/env python3
"""Real loopback HTTP/browser acceptance with synthetic data only.

No HTML injection, route fulfillment, storage shims or weakened browser policies.
Does NOT deploy Pages or validate real source data. Test artifacts never contain
user market bundles, holdings or notes. Browser navigation failures fail the test.
"""
from __future__ import annotations
import argparse
import functools
import hashlib
import json
import shutil
import sys
import tempfile
import threading
from contextlib import contextmanager
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_market_page import build, canonical, encoded


def fixture(version: str = 'http-synthetic/1') -> dict:
    """Invented small values for transport/UI assertions, never research data."""
    days=['2026-10-08','2026-10-09','2026-10-12','2026-10-13',
          '2026-10-14','2026-10-15','2026-10-16','2026-10-19']
    source={'provider':'合成测试，不是行情',
            'url':'https://www.chinaamc.com/fund/510330/index.shtml',
            'recorded_at':'2026-10-20T00:00:00Z','published_at':None,
            'mode':'web_text_transcription','raw_response_archived':False,
            'evidence_sha256':None}
    products=[]
    for j,code in enumerate(['510330','159995']):
        products.append({'code':code,'exchange':'SSE' if j==0 else 'SZSE',
            'label':'合成参照' if j==0 else '合成测试',
            'name':'仅用于浏览器测试，不是实际ETF净值',
            'group':'宽基' if j==0 else '行业相关','basis':'unadjusted_nav',
            'currency':'CNY','observations':{d:{'nav':f'1.{i+j:04d}',
                'shares':None,'nav_source':'synthetic-nav','shares_source':None}
                for i,d in enumerate(days)}})
    return {'schema':'ql.market-bundle/2','version':version,'timezone':'Asia/Shanghai',
        'audience':'public-market','auto_updated':False,'observed_at':'2026-10-20T01:00:00Z',
        'asof':days[-1],'benchmark_code':'510330','calendar':{'version':'synthetic-days',
        'source_url':'https://www.sse.com.cn/disclosure/dealinstruc/closed/',
        'coverage_start':days[0],'coverage_end':days[-1],'sessions':days},
        'sources':{'synthetic-nav':source},'products':products}


def write_fixture(public: Path, version: str) -> None:
    data=encoded(canonical(encoded(fixture(version)).encode())).encode()
    sha=hashlib.sha256(data).hexdigest();name=f'market.{sha}.json'
    (public/name).write_bytes(data)
    (public/'market.manifest.json').write_text(encoded({'schema':'ql.market-manifest/2',
        'state':'ready','file':name,'sha256':sha,'bytes':len(data),'version':version,
        'asof':'2026-10-19'}),encoding='utf-8')


@contextmanager
def server(root: Path):
    class Handler(SimpleHTTPRequestHandler):
        def log_message(self,*args): pass
        def end_headers(self):
            self.send_header('Cache-Control','no-store');super().end_headers()
    http=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(Handler,directory=str(root)))
    thread=threading.Thread(target=http.serve_forever,daemon=True);thread.start()
    try: yield f'http://127.0.0.1:{http.server_port}/'
    finally: http.shutdown();http.server_close();thread.join(timeout=5)


def run(output: Path, browser: str) -> dict:
    from playwright.sync_api import sync_playwright
    checks=[]
    result={'schema':'ql.http-browser-acceptance/1','mode':'real_loopback_http',
        'dataset':'synthetic-only','html_injection':False,'storage_shim':False,
        'route_mocking':False,'online_deployment_tested':False,'real_device_tested':False,
        'checks':checks,'passed':False}
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok: raise AssertionError(name)
    try:
        with tempfile.TemporaryDirectory(prefix='ql-http-') as tmp:
            base=Path(tmp);build(base/'build')
            root=base/'site';root.mkdir();public=root/'ql'
            shutil.copytree(base/'build/public',public)
            with server(root) as host, sync_playwright() as pw:
                url=host+'ql/';profile=base/'browser-profile'
                def launch():
                    return pw.chromium.launch_persistent_context(str(profile),
                        executable_path=browser,headless=True,
                        viewport={'width':1440,'height':1000})
                ctx=launch();page=ctx.pages[0];errors=[];requests=[]
                page.on('pageerror',lambda e:errors.append(type(e).__name__))
                page.on('request',lambda r:requests.append(r.url))
                page.set_default_timeout(8000)
                r=page.goto(url,wait_until='networkidle',timeout=15000)
                check('actual_http_document_200',r.status==200)
                check('no_data_state_explicit','市场数据' in page.locator('#app').inner_text())
                check('no_data_status_finishes','正在校验' not in page.locator('#market-status').inner_text())
                check('date_disabled_without_data',page.locator('#asof').is_disabled())
                check('real_js_and_css_requested',sum('.js' in u for u in requests)>=4 and any('.css' in u for u in requests))
                check('no_off_origin_requests',all(urlsplit(u).netloc==urlsplit(host).netloc for u in requests))
                write_fixture(public,'http-synthetic/1')
                page.reload(wait_until='networkidle');page.wait_for_selector('.stat')
                check('manifest_loaded_without_import',page.locator('#asof option').count()==8)
                check('sha256_in_secure_loopback_context',page.evaluate('isSecureContext && !!crypto.subtle'))
                check('synthetic_product_count','2' in page.locator('.statvalue').first.inner_text())
                page.locator('[data-action="detail"][data-code="159995"]').first.click()
                page.locator('#detail-note').fill('SYNTHETIC NOTE — local storage restart test')
                page.locator('[data-action="save-note"]').click()
                check('native_localstorage_written','SYNTHETIC NOTE' in page.evaluate("localStorage.getItem('ql.personal.v1')"))
                page.reload(wait_until='networkidle');page.wait_for_selector('.stat')
                check('hash_route_survives_reload',page.locator('h1').inner_text()=='合成测试')
                check('note_survives_reload','SYNTHETIC NOTE' in page.locator('#detail-note').input_value())
                page.locator('[data-route="overview"]').first.click()
                for width,height in [(1440,1000),(1024,768),(768,1024),(600,960),(430,932),(360,800)]:
                    page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(120)
                    check(f'no_horizontal_overflow_{width}',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
                page.set_viewport_size({'width':1440,'height':1000})
                page.locator('[data-route="compare"]').first.click()
                check('heatmap_rows',page.locator('.heat tbody tr').count()==2)
                page.locator('[data-route="overview"]').first.click()
                page.locator('#search').fill('159995')
                check('search_filters_product',page.locator('.desktopproducts tbody tr').count()==1)
                page.locator('#search').fill('')
                page.locator('[data-action="window"][data-h="20"]').first.click()
                check('insufficient_history_not_fabricated','历史不足' in page.locator('#app').inner_text())
                page.locator('[data-action="window"][data-h="5"]').first.click()
                write_fixture(public,'http-synthetic/2');page.locator('#market-refresh').click()
                page.locator('#market-dialog').wait_for(state='visible')
                check('update_requires_confirmation',page.locator('#market-dialog').is_visible())
                page.locator('#market-cancel').click()
                check('cancel_keeps_dataset',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='http-synthetic/1')
                page.locator('#market-refresh').click();page.locator('#market-dialog').wait_for(state='visible')
                page.locator('#market-accept').click();page.wait_for_load_state('networkidle');page.wait_for_selector('.stat')
                check('confirmed_update_survives_actual_reload',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='http-synthetic/2')
                manifest=json.loads((public/'market.manifest.json').read_text())
                original=(public/manifest['file']).read_bytes()
                (public/manifest['file']).write_bytes(b' '+original[1:])
                page.locator('#market-refresh').click()
                page.locator('#market-message[data-error="true"]').wait_for(state='attached')
                check('bad_digest_preserves_loaded_dataset',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='http-synthetic/2')
                check('bad_digest_preserves_notes','SYNTHETIC NOTE' in page.evaluate("localStorage.getItem('ql.personal.v1')"))
                (public/manifest['file']).write_bytes(original)
                check('no_unexpected_js_errors',not errors)
                ctx.close();ctx=launch();page=ctx.pages[0]
                page.goto(url+'#/watch',wait_until='networkidle',timeout=15000)
                page.wait_for_selector('.watchrow')
                check('native_notes_survive_browser_restart','SYNTHETIC NOTE' in page.locator('#app').inner_text())
                ctx.close()
                # Real resource corruption: Chrome must enforce SRI, not a route mock.
                engine=next(public.glob('market-data.*.js'));engine.write_bytes(engine.read_bytes()+b'\n/* changed */')
                ctx=pw.chromium.launch_persistent_context(str(base/'sri-profile'),executable_path=browser,headless=True)
                page=ctx.pages[0];page.goto(url,wait_until='networkidle',timeout=15000)
                page.locator('#market-reload').wait_for(state='visible',timeout=10000)
                check('sri_failure_shows_recovery','页面未能完整启动' in page.locator('#app').inner_text())
                check('sri_prevents_engine_execution',page.evaluate("typeof QLMarketData==='undefined'"))
                ctx.close()
            result['passed']=True
            result['native_persistence_tested']=True
    except Exception as exc:
        result['failure_type']=type(exc).__name__
        result['failure']=str(exc).splitlines()[0][:250]
    finally:
        result['passed_checks']=sum(x['passed'] for x in checks)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--browser',default=shutil.which('google-chrome') or shutil.which('chromium'))
    a=p.parse_args()
    if not a.browser:p.exit(2,'No system Chromium/Chrome executable\n')
    report=run(a.output,a.browser);print(json.dumps(report,ensure_ascii=False))
    raise SystemExit(0 if report['passed'] else 2)
