#!/usr/bin/env python3
"""Build a self-contained PRIVATE research page from frozen P0 evidence.

No collection, publication or dependency installation is performed. Public builds
are deliberately refused until a separate field-level release policy is reviewed.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import sys
from decimal import Decimal, localcontext
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.reproduce_p0 import validate as validate_nav, formatted
from tools.audit_share_flow import build as share_build

ALLOWED_HOSTS = {'www.chinaamc.com', 'www.efunds.com.cn', 'www.fsfund.com', 'www.sse.com.cn'}
BASELINE = 'c0aa09216d59e8ae02ac2f9af7e1894a34eb2cbd'
LABELS = {'159995':'半导体芯片', '515030':'新能源汽车', '510330':'沪深300',
          '512010':'沪深300医药', '159819':'人工智能', '510030':'180价值'}
GROUPS = {'sector_product':'行业相关', 'cross_industry_theme':'主题',
          'broad_market_proxy':'宽基', 'style_index_product':'风格'}


def checked_source(s: dict, recorded: str) -> dict:
    u = urlparse(s['url'])
    if u.scheme != 'https' or u.hostname not in ALLOWED_HOSTS or u.username or u.password:
        raise ValueError('Source URL not allowlisted')
    return {'provider':s['provider'], 'url':s['url'], 'recorded_at':recorded,
            'published_at':None, 'raw_response_archived':False}


def make_payload(nav: dict, share: dict) -> dict:
    validate_nav(nav)
    sb = share_build(share)
    days = nav['sample_calendar']
    if days != share['sample_calendar']:
        raise ValueError('Evidence calendars differ')
    sources = {k:checked_source(v, nav['evidence_recorded_at']) for k,v in nav['sources'].items()}
    sources.update({k:checked_source(v, share['evidence_recorded_at']) for k,v in share['sources'].items()})
    products = []
    for p in nav['instruments']:
        rows = {r['日期']:r['净值'] for r in nav['original_rows'] if r['code']==p['code']}
        products.append({'code':p['code'],'name':p['name'], 'label':LABELS[p['code']],
                         'group':GROUPS[p['bucket_type']], 'source_ids':[p['source_id']],
                         'nav':[rows.get(d) for d in days], 'shares_wan':[None]*len(days)})
    snav = {r['日期']:r['单位净值(元)'] for r in share['original_nav_rows']}
    ss = {r['日期']:r['总份额（万份）'] for r in share['original_share_rows']}
    products.append({'code':'510030','name':share['instrument']['legal_name'],'label':LABELS['510030'],
                     'group':'风格','source_ids':list(share['sources']),
                     'nav':[snav.get(d) for d in days],'shares_wan':[ss.get(d) for d in days]})
    with localcontext() as ctx:
        ctx.prec=34
        for p in products:
            p['windows']={}
            for i,d in enumerate(days):
                result={}
                for h in (1,5,20,60):
                    row={'value':None, 'relative_pp':None, 'rebased':[], 'start':None,
                         'reason':'insufficient_history', 'display':None, 'relative_display':None}
                    if i>=h:
                        values=p['nav'][i-h:i+1]
                        benchmark=next(x for x in products if x['code']=='510330')['nav'][i-h:i+1]
                        if all(x is not None for x in values+benchmark):
                            start=Decimal(values[0]); last=Decimal(values[-1])
                            relative=(last/start-Decimal(benchmark[-1])/Decimal(benchmark[0]))*100
                            row={'value':formatted((last/start-1)*100), 'display':formatted((last/start-1)*100,2), 'relative_pp':formatted(relative), 'relative_display':formatted(relative,2),
                                 'rebased':[formatted(Decimal(v)/start*100) for v in values],
                                 'start':i-h, 'reason':None}
                        else:
                            row['reason']='missing_trading_date'
                    result[str(h)]=row
                p['windows'][d]=result
            p['daily']=[p['windows'][d]['1']['value'] for d in days]
    flow_windows={}
    for i,d in enumerate(days):
        flow_windows[d]={}
        for h in (1,5,20,60):
            rows=sb['daily'][i-h:i] if i>=h else []
            values=[r['conditional_flow_cny'] for r in rows]
            flow_windows[d][str(h)]=formatted(sum((Decimal(v) for v in values),Decimal(0))/10000,2) if len(values)==h and all(v is not None for v in values) else None
    return {'schema':'ql.page/1','version':'p1-page-preview/1','evidence_commit':BASELINE,
            'timezone':'Asia/Shanghai','dates':days,'asof':days[-1], 'report_status':'historical_sample',
            'public_export_allowed':False,'auto_updated':False,'sources':sources,
            'products':products,'flow_windows':flow_windows,'share_daily':sb['daily'], 'accepted_flow_cny':None,
            'scope':'六只ETF验证观察池；不是全A股或正式行业横截面。',
            'warnings':['单位净值未复权，非总收益或可成交价格。','份额事件核验未完成，正式资金指标停用。',
                        '样例取自官方页面文本摘录，非原始HTTP响应。','六个观察日不支持20/60日窗口。']}


def build(output: Path, audience: str='private-review') -> dict:
    if audience != 'private-review':
        raise ValueError('Public export blocked: source redistribution clearance is absent')
    files=['research/p0/nav_sample_20261016.json','research/p0/share_sample_20261016.json']
    raw=[(ROOT/f).read_bytes() for f in files]
    payload=make_payload(*(json.loads(b) for b in raw))
    payload['input_sha256']={f:hashlib.sha256(b).hexdigest() for f,b in zip(files,raw)}
    encoded=json.dumps(payload,ensure_ascii=False,separators=(',',':')).replace('<','\\u003c').replace('&','\\u0026')
    template=(ROOT/'web/index.template.html').read_text(encoding='utf-8')
    css=(ROOT/'web/style.css').read_text(encoding='utf-8')
    js=(ROOT/'web/app.js').read_text(encoding='utf-8')
    if '</script' in js.lower():
        raise ValueError('Unsafe embedded script terminator')
    html=template.replace('/*__CSS__*/',css).replace('__PAYLOAD__',encoded).replace('/*__APP__*/',js)
    output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(html,encoding='utf-8')
    manifest={'schema':'ql.page-build/1','audience':audience,'public_export_allowed':False,
              'asof':payload['asof'],'version':payload['version'],'input_sha256':payload['input_sha256'],
              'output_sha256':hashlib.sha256(output.read_bytes()).hexdigest(),
              'output_bytes':output.stat().st_size,'build_is_network_free':True}
    output.with_suffix('.manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return manifest

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,default=ROOT/'dist/index.html')
    parser.add_argument('--audience',choices=['private-review','public'],default='private-review')
    args=parser.parse_args()
    try:
        print(json.dumps(build(args.output,args.audience),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,TypeError) as exc:
        parser.exit(2,f'Page build failed: {exc}\n')
