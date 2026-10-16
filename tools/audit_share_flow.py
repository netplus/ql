#!/usr/bin/env python3
"""Reproduce P0-A displayed-share arithmetic; never emit admitted flow signals."""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
# Frozen specimen calendar, not a generic weekday-based exchange calendar.
SAMPLE_DATES = ['2026-10-08', '2026-10-09', '2026-10-12',
                '2026-10-13', '2026-10-14', '2026-10-15']


def number(value: str) -> Decimal:
    if not isinstance(value, str):
        raise ValueError('Raw numeric fields must remain strings')
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal string') from exc
    if not result.is_finite():
        raise ValueError('Non-finite value')
    return result


def base_shares(value: str, unit: str) -> Decimal:
    factors = {'share': Decimal(1), 'wan_share': Decimal(10000)}
    if unit not in factors:
        raise ValueError('Unknown share unit')
    result = number(value) * factors[unit]
    if result < 0:
        raise ValueError('Negative total shares')
    return result


def text(value: Decimal | None) -> str | None:
    return None if value is None else format(value, 'f')


def validate(sample: dict[str, Any]) -> None:
    if sample['schema_version'] != 'ql.p0a.share-sample/1':
        raise ValueError('Unsupported schema')
    if sample['method_version'] != 'conditional-displayed-share-flow/1':
        raise ValueError('Unsupported method')
    if sample['timezone'] != 'Asia/Shanghai':
        raise ValueError('Unexpected market timezone')
    if sample['public_export_allowed'] is not False:
        raise ValueError('Public export is not cleared')
    if sample['event_basis_status'] != 'unverified':
        raise ValueError('This method only supports explicitly conditional arithmetic')
    if datetime.fromisoformat(sample['evidence_recorded_at']).utcoffset() is None:
        raise ValueError('Evidence timestamp must be timezone-aware')
    days = sample['sample_calendar']
    if days != SAMPLE_DATES:
        raise ValueError('Calendar differs from the frozen six-date specimen')
    for day in days:
        date.fromisoformat(day)
    for table, field, nav in [('original_share_rows', '总份额（万份）', False),
                              ('original_nav_rows', '单位净值(元)', True)]:
        seen = set()
        for row in sample[table]:
            day = row['日期']
            if day in seen or day not in days or row['code'] != sample['instrument']['code']:
                raise ValueError('Duplicate, out-of-calendar or wrong-instrument row')
            seen.add(day)
            source = sample['sources'][row['source_id']]
            if source['field'] != field or source['field_basis_verified'] is not True:
                raise ValueError('Unverified field semantics')
            if nav:
                if source['unit'] != 'CNY/share' or number(row[field]) <= 0:
                    raise ValueError('Invalid NAV or NAV unit')
            else:
                if source['unit'] != 'wan_share':
                    raise ValueError('This raw field is explicitly in wan-share units')
                base_shares(row[field], source['unit'])


def build(sample: dict[str, Any]) -> dict[str, Any]:
    validate(sample)
    with localcontext() as ctx:
        ctx.prec = 34
        days = sample['sample_calendar']
        share_rows = {r['日期']: r for r in sample['original_share_rows']}
        nav_rows = {r['日期']: r for r in sample['original_nav_rows']}
        shares = {d: base_shares(r['总份额（万份）'], sample['sources'][r['source_id']]['unit'])
                  for d, r in share_rows.items()}
        nav = {d: number(r['单位净值(元)']) for d, r in nav_rows.items()}
        normalized = [{'trade_date': d, 'shares_from_display': text(shares.get(d)),
                       'unit_nav_cny': text(nav.get(d)),
                       'shares_source': share_rows.get(d, {}).get('source_id'),
                       'nav_source': nav_rows.get(d, {}).get('source_id')}
                      for d in days]
        daily = []
        for previous, current in zip(days, days[1:]):
            delta = None
            conditional = None
            aum_change = None
            nav_component = None
            reason = 'missing_adjacent_shares'
            if previous in shares and current in shares:
                delta = shares[current] - shares[previous]
                reason = 'missing_same_date_nav'
                if current in nav:
                    conditional = delta * nav[current]
                    reason = 'event_basis_unverified'
                    if previous in nav:
                        aum_change = shares[current] * nav[current] - shares[previous] * nav[previous]
                        nav_component = shares[previous] * (nav[current] - nav[previous])
                        if aum_change != conditional + nav_component:
                            raise ValueError('AUM decomposition failed')
            daily.append({'previous_trade_date': previous, 'trade_date': current,
                          'displayed_share_change': text(delta),
                          'conditional_flow_cny': text(conditional),
                          'accepted_flow_cny': None, 'reason': reason,
                          'aum_change_from_display_cny': text(aum_change),
                          'nav_component_from_display_cny': text(nav_component)})
        flows = [number(row['conditional_flow_cny']) for row in daily
                 if row['conditional_flow_cny'] is not None]
        total = sum(flows, Decimal(0)) if len(flows) == len(daily) else None
        return {'schema_version': 'ql.p0a.share-results/1',
                'method_version': sample['method_version'],
                'code': sample['instrument']['code'], 'asof': days[-1],
                'evidence_recorded_at': sample['evidence_recorded_at'],
                'origin_http_response_archived': False,
                'public_export_allowed': False, 'historical_signal_eligibility': False,
                'assumption': sample['conditional_assumption'],
                'precision_note': sample['precision_note'],
                'normalized': normalized, 'daily': daily,
                'summary': {'intervals': len(daily), 'computed_intervals': len(flows),
                            'conditional_flow_sum_cny': text(total),
                            'accepted_flow_sum_cny': None,
                            'admission': 'blocked_event_basis_unverified'}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'research/p0/share_sample_20261016.json')
    parser.add_argument('--output', type=Path, default=ROOT/'research/p0/share_computed_20261016.json')
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        result = build(json.loads(raw))
        result['input_sha256'] = hashlib.sha256(raw).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        parser.exit(2, f'Share audit failed: {exc}\n')
    for row in result['daily']:
        print(row['trade_date'], 'share_change=', row['displayed_share_change'],
              'conditional_CNY=', row['conditional_flow_cny'], 'accepted=', row['accepted_flow_cny'])
    print('Summary:', json.dumps(result['summary'], ensure_ascii=False))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
