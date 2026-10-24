#!/usr/bin/env python3
"""Finite retries around the audited HTTP cycle; separate per-attempt evidence.

No scheduler, no TLS bypass, no public market feed. Source/validation failures
never become zero or successful snapshots. The existing single-cycle tool is
unchanged. All attempts keep separate local evidence for this run.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.market_calendar import latest_completed, window


def retryable(probe):
    """Transport-only allowlist. Auth, TLS, parsing and data gaps do not retry."""
    failures = [r for r in probe.get('results', []) if r.get('status') != 'observed']
    if not failures:
        return False
    for r in failures:
        message = str(r.get('reason', '')).lower()
        kind = r.get('error_class')
        if any(s in message for s in ('certificate','ssl','tls','permission','unauthorized','forbidden')):
            return False
        if kind == 'HTTPError':
            match = re.search(r'http error (\d{3})', message)
            code = r.get('http_status') or (int(match[1]) if match else None)
            # 429 is deliberately NOT retried: no Retry-After evidence in the old probe.
            if code not in (500,502,503,504):
                return False
        elif kind in ('TimeoutError','ConnectionResetError','ConnectionAbortedError'):
            continue
        elif kind == 'URLError' and any(s in message for s in
                ('timed out','name resolution','getaddrinfo','connection reset','connection refused','network is unreachable','temporary failure')):
            continue
        else:
            return False
    return True


def execute_reliable(config, planned, output, execute_one, sleep=time.sleep):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False, mode=0o700)
    record = {'schema':'ql.reliable-cycle/1','status':'blocked',
              'max_attempts':3,'max_source_requests':len(planned['requests'])*3,
              'selected_attempt':None,'attempts':[], 'daily_schedule_verified':False}
    for index in range(1,4):
        part = output/f'attempt-{index:02d}'
        summary = execute_one(config, planned, part)
        record['attempts'].append({'directory':part.name,'status':summary.get('status'),
                                   'failure_code':summary.get('failure_code')})
        if summary.get('private_preview_built') is True and summary.get('status')=='private_preview_ready':
            record.update(status='private_preview_ready',selected_attempt=part.name)
            break
        probe = part/'raw/probe.json'
        if index == 3 or not probe.is_file() or probe.stat().st_size>256*1024:
            break
        if not retryable(json.loads(probe.read_text(encoding='utf-8'))):
            break
        sleep((2,5)[index-1])
    (output/'cycle.json').write_text(json.dumps(record,sort_keys=True,indent=2)+'\n',encoding='utf-8')
    return record


def main():
    from tools.run_nav_cycle import make_plan, execute
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config',type=Path,default=ROOT/'config/market-universe.json')
    p.add_argument('--calendar',type=Path,default=ROOT/'config/market-calendar-2026.json')
    p.add_argument('--codes',default='159995,510330');p.add_argument('--start',required=True)
    p.add_argument('--end');p.add_argument('--execute',action='store_true');p.add_argument('--output',type=Path)
    a=p.parse_args()
    try:
        config=json.loads(a.config.read_text(encoding='utf-8'))
        spec=json.loads(a.calendar.read_text(encoding='utf-8'))
        latest=latest_completed(spec,datetime.now(timezone.utc))
        end=a.end or latest
        if end>latest:raise ValueError('future_or_incomplete_session')
        planned=make_plan(config,window(spec,a.start,end),a.codes.split(','),a.start,end)
        if not a.execute:
            print(json.dumps({'plan':planned,'max_attempts':3,'max_source_requests':len(planned['requests'])*3},ensure_ascii=False,indent=2));return 0
        if a.output is None:raise ValueError('output_required')
        result=execute_reliable(config,planned,a.output,execute)
        print(json.dumps(result,sort_keys=True))
        return 0 if result['status']=='private_preview_ready' else 2
    except Exception:
        p.exit(2,'Reliable cycle rejected configuration or acquisition.\n')

if __name__=='__main__':raise SystemExit(main())
