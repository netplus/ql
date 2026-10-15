#!/usr/bin/env python3
"""Offline P0 evidence reproduction. No acquisition, trading or public publishing.

Input numbers are transcribed from issuer pages, not saved raw HTTP responses.
All NAV changes are unadjusted numerical changes, NOT validated total returns.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP, localcontext
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]


def decimal_value(value: str | int | Decimal) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid decimal: {value!r}") from exc
    if not result.is_finite():
        raise ValueError("Non-finite number")
    return result


def formatted(value: Decimal, places: int = 6) -> str:
    return format(value.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP), "f")


def metric(value: Decimal | None, status: str, unit: str, reason: str | None = None) -> dict[str, Any]:
    return {"value": None if value is None else formatted(value), "status": status,
            "unit": unit, "reason": reason}


def validate(sample: dict[str, Any]) -> None:
    if sample["schema_version"] != "ql.p0.nav-sample/1":
        raise ValueError("Unsupported schema")
    if sample["timezone"] != "Asia/Shanghai":
        raise ValueError("Unexpected market timezone")
    stamp = datetime.fromisoformat(sample["evidence_recorded_at"])
    if stamp.utcoffset() is None:
        raise ValueError("Evidence timestamp must be timezone-aware")
    days = sample["sample_calendar"]
    if not days or days != sorted(set(days)):
        raise ValueError("Calendar must be non-empty, ordered and unique")
    for day in days:
        date.fromisoformat(day)
    instruments = {x["code"]: x for x in sample["instruments"]}
    if len(instruments) != len(sample["instruments"]) or sample["benchmark_proxy"] not in instruments:
        raise ValueError("Invalid instrument universe")
    seen = set()
    for row in sample["original_rows"]:
        key = (row["code"], row["日期"])
        if key in seen:
            raise ValueError("Duplicate instrument/date")
        seen.add(key)
        if row["code"] not in instruments or row["日期"] not in days:
            raise ValueError("Unknown instrument or out-of-calendar observation")
        source_id = instruments[row["code"]]["source_id"]
        if sample["sources"][source_id]["unit"] != "CNY/share":
            raise ValueError("Unexpected NAV unit")
        if decimal_value(row["净值"]) <= 0 or decimal_value(row["累计净值"]) <= 0:
            raise ValueError("NAV must be positive")
    if sample["public_export_allowed"] is not False:
        raise ValueError("This review fixture has not been cleared for public export")


def window_change(series: dict[str, Decimal], calendar: list[str], end: str,
                  horizon: int) -> dict[str, Any]:
    if horizon < 1:
        raise ValueError("Horizon must be positive")
    index = calendar.index(end)
    if index < horizon:
        return metric(None, "insufficient_history", "percent", "need_h_plus_1_observations")
    window = calendar[index-horizon:index+1]
    if any(day not in series for day in window):
        return metric(None, "unavailable", "percent", "missing_trading_date")
    if any(series[day] <= 0 for day in window):
        raise ValueError("NAV must be positive")
    return metric((series[end] / series[window[0]] - 1) * 100,
                  "calculated_unadjusted", "percent")


def shares_to_base(value: str, unit: str) -> Decimal:
    """Unit conversion only; does not establish a source's date or reliability."""
    factors = {"share": Decimal(1), "wan_share": Decimal(10000)}
    if unit not in factors:
        raise ValueError("Unknown share unit")
    number = decimal_value(value)
    if number < 0:
        raise ValueError("Share count must not be negative")
    return number * factors[unit]


def estimated_flow(previous_shares: Decimal | None, current_shares: Decimal | None,
                   nav: Decimal | None, split_ratio: Decimal | None,
                   *, adjacent: bool, same_asof: bool) -> dict[str, Any]:
    """Formula guard for synthetic tests only; this fixture has no daily shares.

    split_ratio converts previous shares to the current per-share basis.
    Caller must separately validate other corporate actions and source semantics.
    """
    if previous_shares is None or current_shares is None or nav is None:
        return metric(None, "unavailable", "CNY", "missing_daily_shares_or_nav")
    if not adjacent or not same_asof:
        return metric(None, "quarantined", "CNY", "date_alignment_failed")
    if split_ratio is None:
        return metric(None, "quarantined", "CNY", "event_basis_unverified")
    if min(previous_shares, current_shares) < 0 or nav <= 0 or split_ratio <= 0:
        raise ValueError("Invalid flow inputs")
    return metric((current_shares - previous_shares * split_ratio) * nav,
                  "estimated", "CNY")


def build(sample: dict[str, Any]) -> dict[str, Any]:
    validate(sample)
    with localcontext() as context:
        context.prec = 34
        days = sample["sample_calendar"]
        universe = {x["code"]: x for x in sample["instruments"]}
        series = {code: {} for code in universe}
        normalized = []
        for row in sorted(sample["original_rows"], key=lambda r: (r["code"], r["日期"])):
            code, day = row["code"], row["日期"]
            series[code][day] = decimal_value(row["净值"])
            normalized.append({"code": code, "trade_date": day,
                               "unit_nav_cny": row["净值"],
                               "reported_cumulative_nav_cny": row["累计净值"],
                               "shares": None, "source_id": universe[code]["source_id"],
                               "evidence_recorded_at": sample["evidence_recorded_at"]})
        summaries, chart = [], []
        benchmark = sample["benchmark_proxy"]
        benchmark_change = window_change(series[benchmark], days, days[-1], 5)
        for code, instrument in universe.items():
            changes = {str(h): window_change(series[code], days, days[-1], h) for h in (1, 5, 20, 60)}
            if changes["5"]["value"] is not None and benchmark_change["value"] is not None:
                # Compute from full precision, not from rounded display metrics.
                relative = (series[code][days[-1]] / series[code][days[-6]] -
                            series[benchmark][days[-1]] / series[benchmark][days[-6]]) * 100
                relative_result = metric(relative, "calculated_unadjusted", "percentage_point")
            else:
                relative_result = metric(None, "unavailable", "percentage_point", "incomplete_window")
            source = sample["sources"][instrument["source_id"]]
            daily = changes["1"]["value"]
            reported = decimal_value(source["latest_reported_daily_change_pct"])
            matches = None if daily is None else formatted(decimal_value(daily), 2) == formatted(reported, 2)
            summaries.append({"code": code, "name": instrument["name"], "changes": changes,
                              "relative_to_510330_5_interval_pp": relative_result,
                              "latest_daily_matches_reported_rounding": matches,
                              "estimated_flow_cny": estimated_flow(None, None, None, None,
                                                                    adjacent=True, same_asof=True)})
        for day in days:
            chart.append({"trade_date": day, "rebased_nav": {
                code: formatted(series[code][day] / series[code][days[0]] * 100)
                if day in series[code] and days[0] in series[code] else None for code in universe}})
        return {"schema_version": "ql.p0.results/1", "data_version": sample["data_version"],
                "method_version": sample["method_version"], "asof": days[-1],
                "basis": "unadjusted_NAV_not_total_return_or_market_price",
                "historical_signal_eligibility": False, "public_export_allowed": False,
                "normalized": normalized, "summaries": summaries, "chart": chart}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ROOT / "research/p0/nav_sample.json")
    parser.add_argument("--output", type=Path, default=ROOT / "research/p0/computed.json")
    args = parser.parse_args()
    try:
        raw = args.input.read_bytes()
        result = build(json.loads(raw))
        result["input_sha256"] = hashlib.sha256(raw).hexdigest()
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError, InvalidOperation) as exc:
        parser.exit(2, f"P0 reproduction failed: {exc}\n")
    for row in result["summaries"]:
        print(row["code"], "1 interval:", row["changes"]["1"]["value"],
              "5 intervals:", row["changes"]["5"]["value"],
              "relative pp:", row["relative_to_510330_5_interval_pp"]["value"],
              "flow:", row["estimated_flow_cny"]["value"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
