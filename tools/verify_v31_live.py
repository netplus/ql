#!/usr/bin/env python3
"""Read-only public v3.1 acceptance; synthetic imports stay in a temporary browser profile."""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import build_opener, HTTPRedirectHandler, Request

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.test_market_http import fixture

URL = 'https://netplus.github.io/ql/'
LIMIT = 524288
class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def run(expected: Path, output: Path) -> dict:
    from playwright.sync_api import sync_playwright
    report = {'schema':'ql.v31-public-acceptance/1', 'url':URL,
              'checked_at':datetime.now(timezone.utc).isoformat(),
              'deployment_sha':'fd5dd6a5064c0235d4f54e98d268b1a19c7ef45c',
              'dataset':'synthetic-only local imports; not published',
              'html_injection':False, 'route_mocking':False, 'storage_shim':False,
              'real_device_tested':False, 'market_feed_published':False,
              'http_checks':[], 'browser_checks':[], 'passed':False}
    def check(name, ok):
        report['browser_checks'].append({'name':name,'passed':bool(ok)})
        if not ok: raise AssertionError(name)
    try:
        manifest = json.loads((expected/'release.manifest.json').read_text())
        if manifest.get('application_version') != '3.1' or manifest.get('market_data_included') is not False:
            raise ValueError('Unexpected reviewed release')
        files = manifest['files']
        names = sorted(set(files) | {'release.manifest.json'})
        opener = build_opener(NoRedirect())
        for name in names:
            if name == '.nojekyll': continue
            if not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]*',name): raise ValueError('Unsafe asset name')
            path = expected/name
            if path.is_symlink() or not path.is_file(): raise ValueError('Invalid expected file')
            raw = path.read_bytes()
            if len(raw)>LIMIT or (name in files and hashlib.sha256(raw).hexdigest()!=files[name]):
                raise ValueError('Invalid expected asset hash')
            target = URL if name=='index.html' else URL+name
            with opener.open(Request(target,headers={'Cache-Control':'no-cache','User-Agent':'ql-release-acceptance/1'}), timeout=15) as r:
                body = r.read(LIMIT+1); status = r.status; mime = r.headers.get_content_type()
            allowed = {'.html':('text/html',), '.css':('text/css',),
                       '.js':('application/javascript','text/javascript'), '.json':('application/json',)}
            ok = status==200 and body==raw and mime in allowed.get(path.suffix,())
            report['http_checks'].append({'file':name,'http_status':status,'passed':ok,'sha256':hashlib.sha256(body).hexdigest()})
            if not ok: raise AssertionError('Public bytes or MIME differ: '+name)
        with tempfile.TemporaryDirectory(prefix='ql-live-browser-') as tmp, sync_playwright() as pw:
            executable = shutil.which('google-chrome') or shutil.which('chromium')
            if not executable: raise RuntimeError('Chrome missing')
            def launch():
                return pw.chromium.launch_persistent_context(str(Path(tmp)/'profile'),
                    executable_path=executable,headless=True,viewport={'width':1440,'height':1000})
            ctx=launch(); page=ctx.pages[0]; page.set_default_timeout(10000)
            errors=[]; requests=[]
            page.on('pageerror',lambda e:errors.append(type(e).__name__))
            page.on('request',lambda r:requests.append((r.method,r.url)))
            response=page.goto(URL,wait_until='networkidle',timeout=30000)
            check('public_home_200',response is not None and response.status==200)
            page.locator('#market-status').wait_for(state='visible')
            check('v31_same_origin_loader',page.locator('html').get_attribute('data-transport')=='same-origin')
            check('default_feed_requested',any(urlsplit(u).path.endswith('/market.manifest.json') for _,u in requests))
            check('unpublished_feed_explicit','市场数据' in page.locator('#app').inner_text() and page.locator('#asof').is_disabled())
            check('empty_state_not_stuck',page.locator('#app').get_attribute('aria-busy')=='false')
            def import_local(version, accept=True):
                bundle=fixture(version);bundle['audience']='private-review'
                page.locator('#market-file').set_input_files({'name':'synthetic-only.json','mimeType':'application/json',
                     'buffer':json.dumps(bundle,ensure_ascii=False).encode()})
                page.locator('#market-dialog').wait_for(state='visible')
                if accept:
                    page.locator('#market-accept').click()
                    page.wait_for_load_state('networkidle')
                    page.locator('.stat').first.wait_for(state='visible')
                else: page.locator('#market-cancel').click()
            import_local('live-synthetic/1')
            check('variable_product_date_contract',page.locator('#asof option').count()==8 and page.locator('.desktopproducts tbody tr').count()==2)
            page.locator('#search').fill('159995')
            check('filter_works',page.locator('.desktopproducts tbody tr').count()==1)
            page.locator('#search').fill('')
            page.locator('[data-route="compare"]:visible').first.click()
            check('heatmap_works',page.locator('.heat tbody tr').count()==2)
            page.locator('[data-route="overview"]:visible').first.click()
            page.locator('[data-action="window"][data-h="20"]').first.click()
            check('short_history_not_filled','历史不足' in page.locator('#app').inner_text())
            page.locator('[data-action="window"][data-h="5"]').first.click()
            page.locator('[data-action="detail"][data-code="159995"]').first.click()
            page.locator('#detail-note').fill('SYNTHETIC NOTE - production URL test only')
            page.locator('[data-action="save-note"]').click()
            check('native_note_saved','SYNTHETIC NOTE' in (page.evaluate("localStorage.getItem('ql.personal.v1')") or ''))
            page.reload(wait_until='networkidle');page.locator('#detail-note').wait_for(state='visible')
            check('route_and_note_survive_reload','SYNTHETIC NOTE' in page.locator('#detail-note').input_value())
            page.locator('#market-refresh').click()
            page.locator('#market-message[data-error="true"]').wait_for(state='visible')
            check('unavailable_update_preserves_dataset',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='live-synthetic/1')
            import_local('live-synthetic/2',accept=False)
            check('cancel_keeps_current',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='live-synthetic/1')
            import_local('live-synthetic/2')
            check('confirmed_update_after_reload',page.evaluate("JSON.parse(document.querySelector('#ql-data').textContent).version")=='live-synthetic/2')
            page.locator('[data-route="overview"]:visible').first.click()
            for width,height in [(1440,1000),(1024,768),(768,1024),(600,960),(430,932),(360,800)]:
                page.set_viewport_size({'width':width,'height':height})
                check('no_page_overflow_'+str(width),page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            check('no_unexpected_errors',not errors)
            check('no_upload_or_third_party_requests',all(m=='GET' and urlsplit(u).netloc=='netplus.github.io' for m,u in requests))
            ctx.close();ctx=launch();page=ctx.pages[0];page.set_default_timeout(10000)
            page.goto(URL,wait_until='networkidle',timeout=30000)
            check('note_survives_browser_restart','SYNTHETIC NOTE' in (page.evaluate("localStorage.getItem('ql.personal.v1')") or ''))
            ctx.close()
        report['passed']=True
    except Exception as exc:
        report['failure_type']=type(exc).__name__
        report['failure']=str(exc).splitlines()[0][:240]
    report['passed_http_checks']=sum(c['passed'] for c in report['http_checks'])
    report['passed_browser_checks']=sum(c['passed'] for c in report['browser_checks'])
    output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--expected',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    result=run(args.expected,args.output)
    print(json.dumps(result,ensure_ascii=False))
    raise SystemExit(0 if result['passed'] else 2)
