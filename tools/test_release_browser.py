#!/usr/bin/env python3
"""Injected Chromium UI checks; NOT native navigation, storage or device certification."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect

ROOT=Path(__file__).resolve().parents[1]
MEMORY="""() => {window.__qlMemory={session:{},local:{}};for(const [name,k] of [['sessionStorage','session'],['localStorage','local']])Object.defineProperty(window,name,{configurable:true,value:{getItem:x=>window.__qlMemory[k][x]??null,setItem:(x,v)=>window.__qlMemory[k][x]=String(v),removeItem:x=>delete window.__qlMemory[k][x],clear:()=>window.__qlMemory[k]={}}});} """

def run(release:Path,out:Path):
 out.mkdir(parents=True,exist_ok=True)
 shell=(release/'private/ql-shell-offline.html').read_text();preview=(release/'private/ql-preview.html').read_text()
 raw=(release/'private/ql-review.json').read_bytes();payload=json.loads(raw)
 records=[];errors=[];requests=[]
 def check(name,condition):
  records.append({'name':name,'passed':bool(condition)})
  if not condition:
   print('FAILED',name,'errors',errors,'APP',page.locator('#app').inner_text()[:1000],'MESSAGE',page.locator('#bundle-message').inner_text());page.screenshot(path=str(out/'failure.png'),full_page=True);raise AssertionError(name)
 with sync_playwright() as pw:
  browser=pw.chromium.launch(executable_path='/usr/bin/chromium',headless=True,args=['--no-sandbox'])
  context=browser.new_context(viewport={'width':1440,'height':1000},has_touch=True)
  page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url))
  page.evaluate(MEMORY);page.set_content(shell,wait_until='load')
  check('shell has no plotted market series',page.locator('svg.plot').count()==0)
  check('shell explains local-only import','不包含市场数值' in page.locator('#notice-text').inner_text())
  check('shell cutoff disabled',page.locator('#asof').is_disabled())
  for w,h,label in [(1440,1000,'desktop'),(390,844,'phone'),(820,1180,'tablet'),(1024,768,'tablet-landscape')]:
   page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(120)
   check('shell no horizontal overflow '+label,page.evaluate('document.documentElement.scrollWidth <= innerWidth+1'))
  page.screenshot(path=str(out/'public-shell-tablet.png'),full_page=True)
  page.locator('#bundle-file').set_input_files({'name':'ql-review.json','mimeType':'application/json','buffer':raw})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  page.locator('#bundle-dialog').wait_for(state='visible')
  check('import opens explicit confirmation',page.locator('#bundle-dialog').is_visible())
  check('nothing rendered before confirmation',page.locator('svg.plot').count()==0)
  page.locator('#bundle-cancel').click();check('cancel keeps empty state',page.locator('svg.plot').count()==0)
  page.locator('#bundle-file').set_input_files({'name':'ql-review.json','mimeType':'application/json','buffer':raw})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  page.locator('#bundle-accept').click();page.locator('svg.plot').first.wait_for(state='visible')
  check('accepted dataset renders chart',page.locator('svg.plot').count()==1)
  check('cutoff matches fixture',page.locator('#asof').input_value()=='2026-10-15')
  check('freshness has Shanghai calendar date','上海日期' in page.locator('#dataset-status').inner_text())
  check('no claim of automatic acquisition','无自动采集' in page.locator('#dataset-status').inner_text())
  saved=page.evaluate("window.__qlMemory.session['ql.dataset.tab.v1']")
  check('market data not stored with personal notes',page.evaluate("!window.__qlMemory.local['ql.personal.v1']"))
  page.locator('[data-action="window"][data-h="60"]').first.click()
  check('long window remains missing','历史不足' in page.locator('#app').inner_text())
  page.locator('[data-action="window"][data-h="5"]').first.click()
  page.locator('[data-action="detail"][data-code="510030"]').first.click()
  check('share detail exists','总份额变化' in page.locator('#app').inner_text())
  page.locator('[data-action="flow"]').click();check('conditional amount is preserved','-710.15' in page.locator('#app').inner_text())
  page.locator('#detail-note').fill('TEST ONLY: wait for same-day evidence')
  page.locator('[data-action="save-note"]').click()
  check('personal record separately stored','TEST ONLY' in page.evaluate("window.__qlMemory.local['ql.personal.v1']"))
  olddate=page.locator('#asof').input_value()
  bad=json.loads(raw);bad['payload']['products'][0]['windows']['2026-10-15']['5']['value']='99.000000'
  page.locator('#bundle-file').set_input_files({'name':'bad.json','mimeType':'application/json','buffer':json.dumps(bad).encode()})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  check('tampered calculation rejected','导入失败' in page.locator('#bundle-message').inner_text())
  check('bad import leaves date unchanged',page.locator('#asof').input_value()==olddate)
  check('bad import leaves saved data unchanged',page.evaluate("window.__qlMemory.session['ql.dataset.tab.v1']")==saved)
  page.locator('#bundle-file').set_input_files({'name':'private-notes.json','mimeType':'application/json','buffer':b'{"schema":"ql.personal/1","favorites":[],"notes":{}}'})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  check('personal bundle rejected in market importer','自选备注' in page.locator('#bundle-message').inner_text())
  page.locator('#bundle-file').set_input_files({'name':'broken.json','mimeType':'application/json','buffer':b'{broken'})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  check('invalid json rejected',page.locator('#bundle-message').get_attribute('data-error')=='true')
  page.locator('#bundle-file').set_input_files({'name':'large.json','mimeType':'application/json','buffer':b' '* (2*1024*1024+1)})
  expect(page.locator('#bundle-file')).to_have_value('', timeout=5000)
  check('oversize file rejected','超过2MB' in page.locator('#bundle-message').inner_text())
  # Re-create a document with the explicit memory fixture to test restoration logic,
  # not native sessionStorage or an actual reload (navigation is policy-blocked).
  restored=context.new_page();restored.on('pageerror',lambda e:errors.append(str(e)));restored.evaluate(MEMORY)
  restored.evaluate("raw=>sessionStorage.setItem('ql.dataset.tab.v1',raw)",saved);restored.set_content(shell,wait_until='load')
  check('session restoration logic renders chart',restored.locator('svg.plot').count()==1)
  restored.close()
  page=context.new_page();page.on('pageerror',lambda e:errors.append(str(e)));page.on('request',lambda r:requests.append(r.url));page.evaluate(MEMORY);page.set_content(preview,wait_until='load');page.locator('svg.plot').first.wait_for(state='visible')
  for w,h,label in [(1440,1000,'desktop'),(390,844,'phone'),(430,932,'wide-phone'),(820,1180,'tablet'),(1024,768,'tablet-landscape'),(600,900,'split-screen')]:
   page.set_viewport_size({'width':w,'height':h});page.wait_for_timeout(150)
   check('loaded no horizontal overflow '+label,page.evaluate('document.documentElement.scrollWidth<=innerWidth+1'))
   check('loaded chart within viewport '+label,page.locator('svg.plot').first.bounding_box()['width']<=w)
   if label in ('desktop','phone'):page.screenshot(path=str(out/('page-'+label+'.png')),full_page=True)
  check('no external data or upload requests',not requests)
  check('no uncaught browser errors',not errors)
  browser.close()
 result={'browser':'Chromium','mode':'single-file equivalent via set_content / injected; explicit memory adapters','checks':records,'passed':sum(x['passed'] for x in records),'errors':errors,'external_requests':requests,'not_verified':['native HTTP/file navigation','native sessionStorage/localStorage persistence','actual reload','multi-file HTTP asset loading','GitHub Pages deployment','vivo/iPad devices','Safari/WebKit','automated daily market collection']}
 (out/'browser-tests.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
 print(json.dumps({'passed':result['passed'],'external_requests':len(requests),'errors':errors},ensure_ascii=False))

if __name__=='__main__':
 a=argparse.ArgumentParser();a.add_argument('--release',type=Path,default=ROOT/'dist/release-p1.1');a.add_argument('--output',type=Path,default=ROOT/'artifacts/release-browser');v=a.parse_args();run(v.release,v.output)
