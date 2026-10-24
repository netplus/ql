#!/usr/bin/env python3
"""Exercise the exact preview in Chromium. Injection fallback is explicitly recorded.
No storage shim, policy modification or claim of real-device/online acceptance.
"""
import argparse,json
from pathlib import Path
from playwright.sync_api import sync_playwright

def run(preview,output,browser):
    checks=[];errors=[];requests=[]
    def check(name,ok):
        checks.append({'name':name,'passed':bool(ok)})
        if not ok: raise AssertionError(name)
    with sync_playwright() as pw:
        b=pw.chromium.launch(executable_path=browser,headless=True,args=['--no-sandbox'])
        context=b.new_context(viewport={'width':1440,'height':1100})
        page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
        mode='file_navigation';nav_error=None
        try:page.goto(preview.resolve().as_uri(),wait_until='load',timeout=10000)
        except Exception as e:
            mode='html_injection';nav_error=str(e).splitlines()[0];page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url));page.set_content(preview.read_text(),wait_until='load')
        page.wait_for_selector('.stat',timeout=10000)
        check('data-driven count is seven','7' in page.locator('.statvalue').first.inner_text())
        check('12 selectable sessions',page.locator('#asof option').count()==12)
        check('latest date is 2026-10-23',page.locator('#asof').input_value()=='2026-10-23')
        check('chart contains seventh product',page.get_by_role('button',name='上证50',exact=True).count()>0)
        check('no undefined SVG color','undefined' not in (page.locator('svg').first.get_attribute('outerHTML') or page.locator('svg').first.evaluate('(e)=>e.outerHTML')))
        page.screenshot(path=str(output.parent/'market-desktop.png'),full_page=True)
        page.locator('[data-action="window"][data-h="20"]').first.click();check('20d requires real history','历史不足' in page.locator('#app').inner_text())
        page.locator('[data-action="window"][data-h="5"]').first.click()
        page.locator('[data-action="detail"][data-code="510050"]').first.click();check('new product detail works',page.locator('h1').inner_text()=='上证50')
        page.locator('#detail-note').fill('观察5日相对变化，不预设资金意图。');page.locator('[data-action="save-note"]').click()
        page.locator('[data-route="watch"]').first.click();check('new product can be watched','上证50' in page.locator('#app').inner_text());check('note kept in memory','观察5日' in page.locator('#app').inner_text())
        page.locator('[data-route="detail"]').first.click();page.locator('#product-select').select_option('510030');page.locator('#asof').select_option('2026-10-15')
        page.locator('[data-action="flow"]').click();check('old conditional flow retained','710.15' in page.locator('#app').inner_text())
        page.locator('#asof').select_option('2026-10-23')
        if page.locator('[data-action="flow"]').get_attribute('aria-expanded')=='false':page.locator('[data-action="flow"]').click()
        check('new shares not forward-filled','窗口不足' in page.locator('#app').inner_text())
        page.locator('[data-action="evidence"]').click();check('source dialog opened',page.locator('#evidence-dialog').is_visible());page.locator('#close-dialog').click()
        page.locator('[data-route="overview"]').first.click();page.locator('#search').fill('510050');check('search new code',page.locator('.desktopproducts tbody tr').count()==1);page.locator('#search').fill('')
        for width,height in [(1440,1000),(1024,768),(768,1024),(600,960),(430,932),(360,800)]:
            page.set_viewport_size({'width':width,'height':height});page.wait_for_timeout(160)
            check(f'no page overflow {width}',page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
            check(f'visible UI {width}',page.locator('h1').is_visible())
            if width==430:page.screenshot(path=str(output.parent/'market-phone.png'),full_page=True)
        page.locator('[data-route="compare"]').first.click();check('heatmap has seven products',page.locator('.heat tbody tr').count()==7)
        page.locator('[data-action="heat"][data-code="510050"][data-date="2026-10-23"]').click();check('heatmap opens correct product',page.locator('h1').inner_text()=='上证50')
        check('no JS errors',not errors)
        b.close()
    result={'mode':mode,'navigation_error':nav_error,'checks':checks,'passed':sum(x['passed'] for x in checks),'errors':errors,'requests':requests,'native_persistence_tested':False,'real_device_tested':False,'online_deployment_tested':False}
    output.write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n');print(json.dumps({'mode':mode,'passed':result['passed']},ensure_ascii=False))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--preview',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--browser',default='/usr/bin/chromium');a=p.parse_args();a.output.parent.mkdir(parents=True,exist_ok=True);run(a.preview,a.output,a.browser)
