#!/usr/bin/env python3
"""Bounded P0 source probe. Default is dry-run. No scheduler, credentials or publishing."""
from __future__ import annotations

import argparse
import hashlib
import json
import socket
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

MAX_BYTES = 8 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def plans(start: str, end: str) -> list[dict]:
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    if first > last or (last-first).days > 7:
        raise ValueError('Probe allows only an ordered range of at most 7 calendar days')
    sse = {'isPagination':'true', 'pageHelp.pageSize':'25', 'pageHelp.pageNo':'1',
           'pageHelp.beginPage':'1', 'pageHelp.cacheSize':'1', 'pageHelp.endPage':'1',
           'sqlId':'COMMON_SSE_ZQPZ_ETFZL_XXPL_ETFGM_SEARCH_L', 'STAT_DATE':end}
    szse = {'SHOWTYPE':'xlsx', 'CATALOGID':'scsj_fund_jjgm', 'TABKEY':'tab1',
            'txtStart':start, 'txtEnd':end, 'jjlb':'ETF'}
    return [
        {'source':'sse', 'url':'https://query.sse.com.cn/commonQuery.do?'+urlencode(sse),
         'referer':'https://www.sse.com.cn/', 'format':'json', 'raw_share_unit':'wan_share',
         'coverage':'First 25 rows of end date only; not full-market or interval coverage'},
        {'source':'szse', 'url':'https://www.szse.cn/api/report/ShowReport?'+urlencode(szse),
         'referer':'https://www.szse.cn/market/fund/volume/etf/index.html',
         'format':'xlsx', 'raw_share_unit':'share',
         'coverage':'Requested short date interval; actual coverage requires content validation'}]


def classify_error(exc: Exception) -> str:
    cause = getattr(exc, 'reason', exc)
    if isinstance(cause, socket.gaierror):
        return 'dns_resolution_failed'
    if isinstance(cause, (TimeoutError, socket.timeout)):
        return 'timeout'
    if isinstance(exc, HTTPError):
        return f'http_{exc.code}'
    return 'network_or_response_error'


def probe(plan: dict, directory: Path, timeout: int) -> dict:
    result = {**plan, 'started_at':now(), 'response_archived':False,
              'market_records_admitted':False}
    request = Request(plan['url'], headers={'User-Agent':'ql-P0-source-probe/1.0',
                                            'Referer':plan['referer']})
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = response.read(MAX_BYTES+1)
            result['http_status'] = response.status
            if len(payload) > MAX_BYTES:
                raise ValueError('Response exceeds bounded probe budget')
            digest = hashlib.sha256(payload).hexdigest()
            path = directory/(plan['source']+'-'+digest+'.bin')
            path.write_bytes(payload)
            result.update(response_archived=True, sha256=digest, bytes=len(payload),
                          response_file=path.name,
                          content_type=response.headers.get('Content-Type'))
            # A successful download is not a schema/date/unit/coverage validation.
            result['status'] = 'downloaded_unvalidated'
    except (OSError, URLError, ValueError) as exc:
        result['status'] = 'error'
        result['error_class'] = classify_error(exc)
        # Do not persist arbitrary exception strings, proxy addresses or credentials.
    result['completed_at'] = now()
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--start', required=True)
    parser.add_argument('--end', required=True)
    parser.add_argument('--execute', action='store_true')
    parser.add_argument('--output-dir', type=Path, default=Path('artifacts/share-probe'))
    parser.add_argument('--timeout', type=int, default=8)
    args = parser.parse_args()
    try:
        if not 1 <= args.timeout <= 30:
            raise ValueError('Timeout must be 1..30 seconds')
        requests = plans(args.start, args.end)
        if not args.execute:
            print(json.dumps({'mode':'dry_run', 'requests':requests}, ensure_ascii=False, indent=2))
            return 0
        # Refuse to overwrite a prior acquisition batch or its evidence timestamps.
        args.output_dir.mkdir(parents=True, exist_ok=False)
        records = []
        for index, request in enumerate(requests):
            if index:
                time.sleep(1)
            records.append(probe(request, args.output_dir, args.timeout))
        report = {'schema_version':'ql.p0a.share-probe/1', 'timezone':'Asia/Shanghai',
                  'environment':'current_execution_container_not_user_target_runner',
                  'public_export_allowed':False, 'scheduled_acquisition_verified':False,
                  'records':records}
        (args.output_dir/'probe.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 2 if any(r['status']=='error' for r in records) else 0
    except (OSError, ValueError) as exc:
        parser.exit(2, f'Probe failed: {exc}\n')


if __name__ == '__main__':
    raise SystemExit(main())
