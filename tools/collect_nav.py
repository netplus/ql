#!/usr/bin/env python3
"""Bounded issuer HTML-table NAV probe. Dry run unless --execute is supplied.

Outputs immutable response evidence and dated NAV rows, NOT a public feed.
A JavaScript shell, DNS failure, stale table or empty response never becomes zero
or an automatic fallback to a media estimate. A browser-extracted text specimen
is a different acquisition mode and is not accepted here as raw HTTP evidence.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import re
import time
import urllib.request
from datetime import date, datetime, timezone
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

HOSTS = {'www.chinaamc.com','www.efunds.com.cn','www.fsfund.com'}
LIMIT = 2 * 1024 * 1024

class Tables(HTMLParser):
    def __init__(self):
        super().__init__();self.tables=[];self.table=None;self.row=None;self.cell=None
    def handle_starttag(self,tag,attrs):
        if tag=='table': self.table=[]
        elif tag=='tr' and self.table is not None:self.row=[]
        elif tag in ('td','th') and self.row is not None:self.cell=[]
    def handle_data(self,data):
        if self.cell is not None:self.cell.append(data)
    def handle_endtag(self,tag):
        if tag in ('td','th') and self.cell is not None:
            self.row.append(''.join(self.cell).strip());self.cell=None
        elif tag=='tr' and self.row is not None:
            if self.table is not None:self.table.append(self.row)
            self.row=None
        elif tag=='table' and self.table is not None:
            self.tables.append(self.table);self.table=None

def parse_nav(html:str,code:str,start:str,end:str)->list[dict]:
    if not re.fullmatch(r'\d{6}',code) or not re.search(r'(?<!\d)'+code+r'(?!\d)',html):
        raise ValueError('fund_code_not_confirmed')
    start_day,end_day=date.fromisoformat(start),date.fromisoformat(end)
    if start_day>end_day:raise ValueError('reversed_interval')
    p=Tables();p.feed(html);found={}
    for table in p.tables:
        nav_col=None;date_col=None
        for row in table:
            headings=[re.sub(r'\s+','',x) for x in row]
            if '日期' in headings:
                date_col=headings.index('日期');nav_col=next((i for i,h in enumerate(headings) if h in ('净值','单位净值','单位净值(元)','单位净值（元）')),None)
                continue
            if nav_col is None or date_col is None or len(row)<=max(nav_col,date_col):continue
            d=row[date_col]
            if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',d):continue
            stamp=date.fromisoformat(d)
            if not start_day<=stamp<=end_day:continue
            value=row[nav_col].strip()
            if not re.fullmatch(r'\d{1,14}(?:\.\d{1,8})?',value) or Decimal(value)<=0:raise ValueError('invalid_NAV')
            if d in found and Decimal(found[d])!=Decimal(value):raise ValueError('conflicting_duplicate')
            found[d]=value
    if not found:raise ValueError('no_dated_NAV_table_in_HTTP_response')
    return [{'code':code,'trade_date':d,'unit_nav_cny':v} for d,v in sorted(found.items())]

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):return None

def plan(config:dict,codes:list[str])->list[dict]:
    if not 1<=len(codes)<=4 or len(set(codes))!=len(codes):raise ValueError('select_1_to_4_unique_codes')
    records=config['products'];bycode={p['code']:p for p in records}
    result=[]
    for code in codes:
        if code not in bycode:raise ValueError('unknown_code')
        u=urlsplit(bycode[code]['nav_url'])
        if u.scheme!='https' or u.hostname not in HOSTS or u.port or u.username or u.password or u.fragment:
            raise ValueError('unreviewed_endpoint')
        result.append({'code':code,'url':bycode[code]['nav_url']})
    return result

def acquire(requests:list[dict],start:str,end:str,output:Path)->dict:
    date.fromisoformat(start);date.fromisoformat(end)
    if start>end:raise ValueError('reversed_interval')
    output.mkdir(parents=True,exist_ok=False)
    results=[];opener=urllib.request.build_opener(NoRedirect())
    for i,item in enumerate(requests):
        if i:time.sleep(1)
        now=lambda:datetime.now(timezone.utc).isoformat(timespec='seconds')
        result={**item,'started_at':now(),'status':'error','row_count':0,'raw_response_archived':False,'mode':'http_response'}
        try:
            req=urllib.request.Request(item['url'],headers={'User-Agent':'ql-personal-research/0.2 (bounded data feasibility probe)','Accept':'text/html'})
            with opener.open(req,timeout=12) as r:
                if r.geturl()!=item['url'] or r.status!=200:raise ValueError('unexpected_HTTP_status_or_redirect')
                if r.headers.get_content_type()!='text/html':raise ValueError('unexpected_MIME')
                raw=r.read(LIMIT+1)
                if len(raw)>LIMIT:raise ValueError('response_too_large')
                encoding=r.headers.get_content_charset() or 'utf-8'
                if encoding.lower() not in ('utf-8','utf8','gbk','gb2312','gb18030'):raise ValueError('unsupported_encoding')
                html=raw.decode(encoding)
            path=output/(item['code']+'.html');path.write_bytes(raw)
            result.update(raw_response_archived=True,raw_sha256=hashlib.sha256(raw).hexdigest(),raw_file=path.name)
            rows=parse_nav(html,item['code'],start,end)
            (output/(item['code']+'.rows.json')).write_text(json.dumps(rows,ensure_ascii=False,indent=2)+'\n')
            result.update(status='observed' if rows[-1]['trade_date']==end else 'stale',row_count=len(rows),latest_observed_date=rows[-1]['trade_date'])
        except Exception as e:
            result['error_class']=type(e).__name__;result['reason']=str(e)[:400]
        result['finished_at']=now();results.append(result)
    report={'requested_interval':[start,end],'target_runtime':'current_work_container','production_runner_verified':False,'results':results,'public_export_allowed':False}
    (output/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--codes',required=True);p.add_argument('--start',required=True);p.add_argument('--end',required=True);p.add_argument('--output',type=Path);p.add_argument('--execute',action='store_true');a=p.parse_args()
    try:
        reqs=plan(json.loads(a.config.read_text()),a.codes.split(','));date.fromisoformat(a.start);date.fromisoformat(a.end)
        if a.start>a.end:raise ValueError('reversed_interval')
        if not a.execute:print(json.dumps({'mode':'dry_run','requests':reqs,'interval':[a.start,a.end]},ensure_ascii=False,indent=2))
        else:
            if not a.output:raise ValueError('output_required')
            report=acquire(reqs,a.start,a.end,a.output);print(json.dumps(report,ensure_ascii=False,indent=2));raise SystemExit(0 if all(r['status']=='observed' for r in report['results']) else 2)
    except (OSError,ValueError,KeyError,TypeError) as exc:p.exit(2,f'Acquisition failed: {exc}\n')
