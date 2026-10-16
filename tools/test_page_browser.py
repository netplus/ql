#!/usr/bin/env python3
"""Chromium interaction tests; viewport/touch emulation, not physical devices."""
import argparse
import json
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from playwright.sync_api import sync_playwright

ROOT=Path(__file__).resolve().parents[1]

def main():
 parser=argparse.ArgumentParser(description=__doc__)
 parser.add_argument('--page',type=Path,default=ROOT/'dist/index.html')
 parser.add_argument('--mode',choices=['injected','http'],default='injected')
 parser.add_argument('--browser',default='/usr/bin/chromium')
 args=parser.parse_args();out=ROOT/'artifacts';out.mkdir(exist_ok=True)
 # Serve beneath a Pages-like project subpath; also test direct file opening.
 class Handler(SimpleHTTPRequestHandler):
  def do_GET(self):
   if self.path.split('?')[0]=='/ql/index.html':
    self.send_response(200);self.send_header('Content-Type','text/html; charset=utf-8');self.end_headers();self.wfile.write(args.page.read_bytes())
   else:self.send_error(404)
  def log_message(self,*args):pass
 server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
 threading.Thread(target=server.serve_forever,daemon=True).start()
 url=f'http://127.0.0.1:{server.server_port}/ql/index.html'
 checks=[];errors=[];requests=[];navigation_limits=[]
 html=args.page.read_text()
 def check(name,condition):
  if not condition:raise AssertionError(name)
  checks.append(name);print('PASS',name)
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path=args.browser,headless=True,args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1440,'height':1000},accept_downloads=True)
  def load(context,fragment='',seed=None,storage=True):
   p=context.new_page();p.on('pageerror',lambda e:errors.append(str(e)));p.on('request',lambda r:requests.append(r.url))
   if args.mode=='injected':
    if storage:
     p.evaluate('''seed=>{window.__qlTestStore=seed||{};Object.defineProperty(window,'localStorage',{configurable:true,value:{getItem:k=>window.__qlTestStore[k]??null,setItem:(k,v)=>{window.__qlTestStore[k]=String(v)},removeItem:k=>delete window.__qlTestStore[k]}})}''',seed)
    else:p.evaluate("Object.defineProperty(window,'localStorage',{get(){throw Error('blocked')}})")
    p.set_content(html)
    if fragment:
     p.evaluate('v=>location.hash=v',fragment)
     p.wait_for_selector('a[data-route="'+fragment.replace('#/','').split('?')[0]+'"][aria-current="page"]')
   else:
    if not storage:p.add_init_script("Object.defineProperty(window,'localStorage',{get(){throw Error('blocked')}})")
    p.goto(url+fragment)
   p.wait_for_function("document.querySelector('#app').getAttribute('aria-busy')==='false'")
   return p
  page=load(context);page.set_default_timeout(5000);page.wait_for_selector('[data-plot] svg')
  check('initial six product rows',page.locator('tbody tr').count()==6)
  check('SVG has six actual series',page.locator('.series').count()==6)
  check('date options reflect sample only',page.locator('#asof option').count()==6)
  page.screenshot(path=str(out/'page-desktop.png'),full_page=True)
  page.get_by_role('button',name='20日',exact=True).click()
  check('20-day insufficient, not synthetic',page.get_by_text('历史不足，暂不计算',exact=True).is_visible() and page.locator('[data-plot] svg').count()==0)
  page.get_by_role('button',name='5日',exact=True).click()
  page.select_option('#asof','2026-10-14')
  check('five-day window needs six observations',page.get_by_text('历史不足，暂不计算',exact=True).is_visible())
  page.select_option('#asof','2026-10-15')
  page.locator('#search').fill('159995');check('search filters exactly',page.locator('tbody tr').count()==1)
  check('search focused after render',page.locator('#search').evaluate('(e)=>e===document.activeElement'))
  page.locator('#search').fill('not-a-code');check('empty search state',page.get_by_text('没有匹配的产品',exact=True).is_visible())
  page.locator('#search').fill('');page.get_by_role('button',name='主题',exact=True).click();check('theme not mixed as canonical industry',page.locator('tbody tr').count()==2)
  page.get_by_role('button',name='全部',exact=True).click()
  page.locator('.legend button').first.click();check('legend toggles a series',page.locator('.series').count()==5)
  page.locator('.legend button').first.click()
  page.locator('rect[data-index="2"]').click();check('chart click readout',page.locator('[data-readout]').inner_text().startswith('2026-10-12'))
  page.get_by_role('button',name='加入自选 半导体芯片').click()
  page.locator('[data-route="watch"]').click();check('favorite saved',page.get_by_text('半导体芯片 ↗',exact=True).is_visible())
  if args.mode=='injected':
   seed=page.evaluate('window.__qlTestStore');page.close();page=load(context,'#/watch',seed)
  else:page.reload()
  check('favorite restored from storage adapter',page.get_by_text('半导体芯片 ↗',exact=True).is_visible())
  page.get_by_text('半导体芯片 ↗',exact=True).click();page.wait_for_selector('#detail-note')
  malicious='<img src=x onerror=alert(1)> 检查同日份额'
  page.locator('#detail-note').fill(malicious);page.get_by_role('button',name='保存观察',exact=True).click()
  page.locator('[data-route="watch"]').click();check('note is text, not HTML',page.get_by_text(malicious,exact=True).is_visible() and page.locator('img').count()==0)
  with page.expect_download() as got:page.get_by_role('button',name='导出自选与备注 ↓').click()
  exported=got.value;data=json.loads(Path(exported.path()).read_text());check('export only private schema',set(data)=={'schema','favorites','notes'} and '159995' in data['favorites'])
  page.locator('#personal-file').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':b'{"schema":"ql.personal/1","favorites":["__proto__"],"notes":{}}'})
  page.wait_for_timeout(150);check('invalid import rejected, favorites preserved',page.locator('#toast').inner_text().startswith('导入失败') and page.get_by_text('半导体芯片 ↗',exact=True).is_visible())
  payload=json.dumps({'schema':'ql.personal/1','favorites':['510030'],'notes':{'510030':'待核实事件'}},ensure_ascii=False).encode()
  page.locator('#personal-file').set_input_files({'name':'good.json','mimeType':'application/json','buffer':payload})
  page.wait_for_selector('dialog[open]');page.get_by_role('button',name='确认',exact=True).click()
  check('valid import after confirmation',page.get_by_text('180价值 ↗',exact=True).is_visible())
  page.get_by_role('button',name='清空本地记录').click();page.get_by_role('button',name='取消',exact=True).click();check('cancel clear preserves data',page.get_by_text('180价值 ↗',exact=True).is_visible())
  page.get_by_role('button',name='清空本地记录').click();page.get_by_role('button',name='确认',exact=True).click();check('confirmed clear empty state',page.get_by_text('先加入一个值得跟踪的方向',exact=True).is_visible())
  page.locator('[data-route="detail"]').click();page.select_option('#product-select','510030')
  check('share graph exists',page.locator('[data-plot="shares"] svg').count()==1)
  page.get_by_role('button',name='查看条件试算 +',exact=True).click();check('conditional flow exact, not admitted',page.get_by_text('-710.15 万元',exact=True).is_visible() and page.get_by_text('未通过',exact=True).is_visible())
  page.get_by_role('button',name='来源与原始字段 ↗').click();check('evidence dialog table',page.locator('dialog tbody tr').count()==6)
  page.keyboard.press('Escape');check('escape closes accessible dialog',page.locator('dialog[open]').count()==0)
  page.screenshot(path=str(out/'page-detail.png'),full_page=True)
  page.locator('[data-route="compare"]').click();check('heatmap real rows',page.locator('.heat tbody tr').count()==6)
  page.locator('.heatcell').nth(1).click();check('heat cell drills down on correct date',page.locator('#asof').input_value()=='2026-10-09' and '/detail?' in page.url)
  page.locator('[data-route="methods"]').click();check('source links safe',page.locator('#app .sourceitem a').count()==8)
  check('no outside requests during interactions',all(r.startswith(url) for r in requests))
  # Each layout uses actual Chromium + touch emulation where relevant.
  layouts=[('phone',393,852,True),('phone-wide',852,393,True),('small-phone',360,780,True),('tablet',820,1180,True),('tablet-landscape',1180,820,True),('split',600,900,True),('pc-small',1024,768,False)]
  for name,w,h,touch in layouts:
   c=browser.new_context(viewport={'width':w,'height':h},has_touch=touch,is_mobile=touch)
   pg=load(c);pg.wait_for_selector('svg')
   for route_name in ['overview','compare','detail','watch','methods']:
    pg.locator(f'[data-route="{route_name}"]').click()
    check(f'{name} {route_name} no horizontal page overflow',pg.evaluate('document.documentElement.scrollWidth <= innerWidth + 1'))
   pg.locator('[data-route="overview"]').click()
   if touch:
    pg.locator('.legend button').first.tap();check(f'{name} touch legend',pg.locator('.series').count()==5)
    pg.locator('.legend button').first.tap()
   if w<=760:check(f'{name} mobile cards replace wide table',pg.locator('.mobileproducts').is_visible() and not pg.locator('.desktopproducts').is_visible())
   if name in ('phone','tablet'):
    pg.screenshot(path=str(out/f'page-{name}.png'),full_page=True)
    if name=='phone':pg.screenshot(path=str(out/'page-phone-viewport.png'))
   c.close()
  for target in [url,args.page.resolve().as_uri()]:
   probe=context.new_page()
   try:probe.goto(target,timeout=5000);probe.wait_for_selector('svg',timeout=5000)
   except Exception as exc:navigation_limits.append({'target':'http' if target.startswith('http') else 'file','error':str(exc).split('Call log:')[0].strip()})
   finally:probe.close()
  blocked=browser.new_context()
  bp=load(blocked,'#/watch',storage=False);check('blocked storage explained',bp.get_by_text('浏览器存储不可用或旧记录无效',exact=False).is_visible());blocked.close()
  bad=context.new_page();bad.set_content(html.replace('type="application/json"','type="application/json"',1).replace('id="ql-data"','id="ql-data-missing"',1));check('missing payload shows explicit error',bad.get_by_text('页面数据未能载入',exact=True).is_visible());bad.close()
  check('no uncaught JavaScript errors',len(errors)==0)
  report={'tested_at':datetime.now(timezone.utc).isoformat(),'mode':args.mode,'navigation_limits':navigation_limits,'persistence_test':'in-memory adapter' if args.mode=='injected' else 'native localStorage','browser':browser.version,'engine':'Chromium','executable':args.browser,'checks_passed':len(checks),'checks':checks,'errors':errors,'physical_device_tests':False,'webkit_tested':False,'public_deployment_tested':False}
  (out/'browser-results.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
  browser.close()
 server.shutdown();print('ALL CHECKS',len(checks))
if __name__=='__main__':main()
