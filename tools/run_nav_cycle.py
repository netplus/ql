#!/usr/bin/env python3
"""One bounded NAV acceptance cycle, not a scheduler or public data publisher.

Default: print a request plan without network or filesystem mutation. --execute
collects official responses, reparses and hashes them, checks calendar coverage,
and builds a PRIVATE preview only when every requested input passes. Public
stdout/summary contains counts, dates, hashes and failure codes, never NAV values.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import collect_nav
from tools.build_market_page import build, canonical

class CycleError(ValueError):
    """A bounded, non-sensitive diagnostic code."""


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def digest(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def write_json(path: Path, obj: object) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def make_plan(config: dict, calendar: dict, codes: list[str], start: str, end: str) -> dict:
    if config.get('schema') != 'ql.universe/1':
        raise CycleError('universe_schema')
    products = config['products']
    if len({p['code'] for p in products}) != len(products):
        raise CycleError('duplicate_config_code')
    requests = collect_nav.plan(config, codes)
    if config['benchmark_code'] not in codes:
        raise CycleError('benchmark_not_selected')
    if date.fromisoformat(start) > date.fromisoformat(end):
        raise CycleError('reversed_interval')
    sessions = calendar['sessions']
    if (not sessions or len(sessions) > 520 or sessions != sorted(set(sessions)) or
            calendar['coverage_start'] != sessions[0] or calendar['coverage_end'] != sessions[-1]):
        raise CycleError('invalid_calendar')
    for value in sessions:
        if date.fromisoformat(value).isoformat() != value:
            raise CycleError('invalid_session_date')
    if start not in sessions or end not in sessions:
        raise CycleError('interval_outside_reviewed_calendar')
    days = [d for d in sessions if start <= d <= end]
    selected_calendar = {**calendar, 'sessions': days, 'coverage_start': start, 'coverage_end': end}
    return {'schema': 'ql.nav-cycle-plan/1', 'mode': 'dry_run', 'requests': requests,
            'start': start, 'end': end, 'calendar': selected_calendar,
            'expected_rows': len(days) * len(codes), 'max_requests': len(codes),
            'public_export_allowed': False}


def reason(result: dict) -> str | None:
    if result.get('status') in ('observed', 'stale'):
        return None
    message = str(result.get('reason', '')).lower()
    if 'name resolution' in message or 'getaddrinfo' in message:
        return 'dns_resolution_failed'
    if 'timed out' in message or 'timeout' in message:
        return 'request_timeout'
    if result.get('error_class') == 'HTTPError':
        return 'http_error'
    known = ('no_dated_NAV_table_in_HTTP_response', 'fund_code_not_confirmed',
             'conflicting_duplicate', 'invalid_NAV', 'unexpected_MIME',
             'unsupported_encoding', 'response_too_large', 'unexpected_HTTP_status_or_redirect')
    for code in known:
        if code.lower() in message:
            return code
    return 'acquisition_failed'


def assemble(config: dict, planned: dict, report: dict, raw_dir: Path) -> tuple[dict, list[dict]]:
    """Reject partial/stale/tampered evidence; do not fill gaps or publish it."""
    codes = [x['code'] for x in planned['requests']]
    results = report.get('results', [])
    if len(results) != len(codes) or {r.get('code') for r in results} != set(codes):
        raise CycleError('response_scope_mismatch')
    products_by_code = {p['code']: p for p in config['products']}
    requests = {x['code']: x['url'] for x in planned['requests']}
    days = planned['calendar']['sessions']
    sources, products, checks = {}, [], []
    for r in results:
        code = r['code']
        if r.get('status') != 'observed' or r.get('latest_observed_date') != planned['end']:
            raise CycleError('source_not_current')
        if (r.get('url') != requests[code] or r.get('mode') != 'http_response' or
                r.get('raw_response_archived') is not True or r.get('raw_file') != code + '.html'):
            raise CycleError('raw_evidence_required')
        raw_path = raw_dir / (code + '.html')
        rows_path = raw_dir / (code + '.rows.json')
        if raw_path.is_symlink() or rows_path.is_symlink():
            raise CycleError('linked_evidence_rejected')
        raw = raw_path.read_bytes()
        if len(raw) > collect_nav.LIMIT or digest(raw) != r.get('raw_sha256'):
            raise CycleError('raw_hash_mismatch')
        encoding = r.get('encoding')
        if not isinstance(encoding, str) or encoding.lower() not in ('utf-8', 'utf8', 'gbk', 'gb2312', 'gb18030'):
            raise CycleError('encoding_evidence_missing')
        rows = collect_nav.parse_nav(raw.decode(encoding), code, planned['start'], planned['end'])
        if rows_path.stat().st_size > collect_nav.LIMIT:
            raise CycleError('rows_too_large')
        if rows != json.loads(rows_path.read_text(encoding='utf-8')) or len(rows) != r.get('row_count'):
            raise CycleError('parsed_rows_mismatch')
        if [x['trade_date'] for x in rows] != days:
            raise CycleError('incomplete_or_off_calendar_rows')
        sid = f"nav-{code}-{r['raw_sha256'][:12]}"
        sources[sid] = {'provider': 'Issuer NAV page / ' + code, 'url': r['url'],
                        'recorded_at': r['finished_at'], 'published_at': None,
                        'mode': 'http_response', 'raw_response_archived': True,
                        'evidence_sha256': r['raw_sha256']}
        meta = products_by_code[code]
        products.append({**{k: meta[k] for k in ('code', 'exchange', 'label', 'name', 'group', 'basis', 'currency')},
                         'observations': {x['trade_date']: {'nav': x['unit_nav_cny'], 'shares': None,
                          'nav_source': sid, 'shares_source': None} for x in rows}})
        checks.append({'code': code, 'rows': len(rows), 'first_date': days[0], 'last_date': days[-1],
                       'raw_sha256': r['raw_sha256'], 'raw_bytes': len(raw)})
    bundle = {'schema': 'ql.market-bundle/2', 'version': 'http-acceptance/' + planned['end'],
              'timezone': 'Asia/Shanghai', 'audience': 'private-review', 'auto_updated': False,
              'observed_at': stamp(), 'asof': planned['end'], 'benchmark_code': config['benchmark_code'],
              'calendar': planned['calendar'], 'sources': sources, 'products': products}
    return canonical(json.dumps(bundle, ensure_ascii=False).encode('utf-8')), checks


def execute(config: dict, planned: dict, output: Path) -> dict:
    # A new directory prevents overwriting prior evidence or the last valid preview.
    output.mkdir(parents=True, exist_ok=False)
    runtime = 'github_hosted_acceptance' if os.environ.get('GITHUB_ACTIONS') == 'true' else 'current_work_container'
    summary = {'schema': 'ql.nav-cycle-summary/1', 'status': 'blocked', 'runtime': runtime,
               'run_id': os.environ.get('GITHUB_RUN_ID') if runtime.startswith('github_') else None,
               'started_at': stamp(), 'requested_interval': [planned['start'], planned['end']],
               'expected_rows': planned['expected_rows'], 'requests': [], 'private_preview_built': False,
               'market_data_published': False, 'daily_schedule_verified': False,
               'raw_retention': 'local_run_directory_only_not_long_term_archive'}
    try:
        report = collect_nav.acquire(planned['requests'], planned['start'], planned['end'],
                                     output / 'raw', runtime_id=runtime)
        for r in report['results']:
            summary['requests'].append({k: r.get(k) for k in (
                'code', 'status', 'row_count', 'latest_observed_date', 'raw_sha256',
                'http_status', 'raw_response_archived')})
            summary['requests'][-1]['reason_code'] = reason(r)
        bundle, checks = assemble(config, planned, report, output / 'raw')
        file = output / 'market.private.json'; write_json(file, bundle)
        result = build(output / 'build', file)
        if result['market_data_published']:
            raise CycleError('unexpected_publication')
        summary.update(status='private_preview_ready', private_preview_built=True, evidence_checks=checks,
                       private_bundle_sha256=digest(file.read_bytes()), products=result['products'])
    except Exception as exc:
        # Source response content and exception text must not enter public CI logs.
        summary['failure_code'] = str(exc) if isinstance(exc, CycleError) else 'cycle_validation_or_runtime_failed'
        summary['failure_type'] = type(exc).__name__
    summary['finished_at'] = stamp()
    write_json(output / 'summary.json', summary)
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--config', type=Path, default=ROOT / 'config/market-universe.json')
    p.add_argument('--calendar', type=Path, default=ROOT / 'config/calendar-2026-oct.json')
    p.add_argument('--codes', default='159995,510330')
    p.add_argument('--start', required=True); p.add_argument('--end', required=True)
    p.add_argument('--execute', action='store_true'); p.add_argument('--output', type=Path)
    a = p.parse_args()
    try:
        config = json.loads(a.config.read_text(encoding='utf-8'))
        planned = make_plan(config, json.loads(a.calendar.read_text(encoding='utf-8')), a.codes.split(','), a.start, a.end)
        if not a.execute:
            print(json.dumps(planned, ensure_ascii=False, indent=2)); return 0
        if a.output is None:
            raise CycleError('output_required')
        result = execute(config, planned, a.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['private_preview_built'] else 2
    except (OSError, ValueError, KeyError, TypeError):
        # Full debug traces remain local to a developer; stdout is a bounded public status.
        p.exit(2, 'NAV acceptance rejected invalid configuration or output.\n')

if __name__ == '__main__':
    raise SystemExit(main())
