#!/usr/bin/env python3
"""Offline PCF semantics audit; no download, share inference, or public export.

The unit-basket division is CONDITIONAL on creation-unit basis consistency.
The fixture does not independently establish that consistency or event history.
"""
from __future__ import annotations
import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def amount(value: str) -> Decimal:
    try:
        number = Decimal(value)
    except Exception as exc:
        raise ValueError("Invalid amount") from exc
    if not number.is_finite() or number < 0:
        raise ValueError("Amount must be finite and nonnegative")
    return number


def known_by(recorded_at: str, cutoff: str) -> bool:
    recorded, end = datetime.fromisoformat(recorded_at), datetime.fromisoformat(cutoff)
    if recorded.utcoffset() is None or end.utcoffset() is None:
        raise ValueError("Timezone-aware instants required")
    return recorded <= end


def build_pcf(sample: dict[str, Any]) -> dict[str, Any]:
    if sample['schema_version'] != 'ql.p0.pcf-audit/1' or sample['timezone'] != 'Asia/Shanghai':
        raise ValueError('Unexpected schema/timezone')
    if sample['public_export_allowed'] is not False:
        raise ValueError('Public export not cleared')
    known_by(sample['evidence_recorded_at'], sample['evidence_recorded_at'])
    results, seen = [], set()
    with localcontext() as ctx:
        ctx.prec = 34
        for row in sample['records']:
            if row['code'] in seen:
                raise ValueError('Duplicate PCF product')
            seen.add(row['code'])
            valuation = date.fromisoformat(row['valuation_date'])
            terms = date.fromisoformat(row['creation_terms_date'])
            publication = date.fromisoformat(row['announcement_date'])
            if not valuation < terms or publication != terms:
                raise ValueError('PCF date labels require review')
            for key in ('daily_total_shares', 'actual_redemption_shares', 'estimated_net_flow_cny'):
                if row[key] is not None:
                    raise ValueError('This fixture contains no observed daily share-flow fields')
            basket, units = amount(row['minimum_unit_nav_cny']), amount(row['creation_unit_shares'])
            nav = amount(row['nav_table_unit_nav_cny'])
            if min(basket, units, nav) <= 0:
                raise ValueError('Positive basket/unit/NAV required')
            amount(row['redemption_limit_shares'])
            conditional_nav = basket / units
            # Four-decimal NAV rounding alone can create a basket-value residual.
            residual = basket - units * nav
            bound = units * Decimal('0.00005') + Decimal('0.005')
            results.append({'code': row['code'], 'valuation_date': row['valuation_date'],
                'announcement_date': row['announcement_date'],
                'conditional_implied_nav_cny': str(conditional_nav),
                'basket_rounding_residual_cny': str(residual),
                'rounding_tolerance_cny': str(bound),
                'within_conditional_rounding_tolerance': abs(residual) <= bound,
                'status': 'conditional_arithmetic_only_creation_basis_unverified',
                'pcf_unit_nav_missing': row['pcf_unit_nav_raw'] == '无',
                'observed_total_shares': None, 'estimated_net_flow_cny': None,
                'eligible_at_20261015_close': known_by(sample['evidence_recorded_at'], '2026-10-15T15:00:00+08:00')})
    return {'schema_version':'ql.p0.pcf-results/1','public_export_allowed':False,
            'creation_unit_continuity_verified':sample['creation_unit_continuity_verified'], 'results':results}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, default=ROOT/'research/p0/pcf_sample_20261016.json')
    parser.add_argument('--output', type=Path, default=ROOT/'research/p0/pcf_computed_20261016.json')
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        result = build_pcf(json.loads(raw))
        result['input_sha256'] = hashlib.sha256(raw).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'PCF audit failed: {exc}\n')
    for row in result['results']:
        print(row['code'], 'conditional NAV:', row['conditional_implied_nav_cny'],
              'rounding residual:', row['basket_rounding_residual_cny'],
              'total shares:', row['observed_total_shares'], 'flow:', row['estimated_net_flow_cny'])
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
