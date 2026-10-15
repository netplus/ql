"""Offline fixture/formula tests, not network or production-system tests."""
import copy
import json
import unittest
from decimal import Decimal as D
from pathlib import Path
from tools.reproduce_p0 import build, estimated_flow, shares_to_base, validate

ROOT = Path(__file__).resolve().parents[1]


class P0Tests(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads((ROOT / "research/p0/nav_sample.json").read_text())

    def test_fixture_count(self):
        self.assertEqual(len(build(self.sample)["normalized"]), 18)

    def test_latest_daily_rounding(self):
        self.assertTrue(all(r["latest_daily_matches_reported_rounding"] for r in build(self.sample)["summaries"]))

    def test_five_intervals(self):
        self.assertEqual(build(self.sample)["summaries"][0]["changes"]["5"]["value"], "-8.009564")

    def test_missing_long_history(self):
        for row in build(self.sample)["summaries"]:
            for horizon in ("20", "60"):
                self.assertIsNone(row["changes"][horizon]["value"])
                self.assertEqual(row["changes"][horizon]["status"], "insufficient_history")

    def test_flow_missing_is_not_zero(self):
        for row in build(self.sample)["summaries"]:
            self.assertIsNone(row["estimated_flow_cny"]["value"])

    def test_duplicate_rejected(self):
        self.sample["original_rows"].append(copy.deepcopy(self.sample["original_rows"][0]))
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_gap_not_bridged(self):
        self.sample["original_rows"].pop(2)
        result = build(self.sample)
        self.assertIsNone(result["summaries"][0]["changes"]["5"]["value"])
        self.assertEqual(result["summaries"][0]["changes"]["5"]["reason"], "missing_trading_date")

    def test_bad_nav_rejected(self):
        for number in ("0", "-1", "NaN", "Infinity"):
            sample = copy.deepcopy(self.sample)
            sample["original_rows"][0]["净值"] = number
            with self.assertRaises(ValueError):
                validate(sample)

    def test_wrong_calendar_rejected(self):
        self.sample["original_rows"][0]["日期"] = "2026-10-10"
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_cumulative_is_preserved_not_used(self):
        result = build(self.sample)
        first = next(x for x in result["normalized"] if x["code"] == "510330")
        self.assertEqual(first["unit_nav_cny"], "4.5699")
        self.assertEqual(first["reported_cumulative_nav_cny"], "2.2145")
        self.sample["original_rows"][12]["累计净值"] = "8.0000"
        self.assertEqual(build(self.sample)["summaries"], result["summaries"])

    def test_no_public_export(self):
        self.assertFalse(build(self.sample)["public_export_allowed"])
        self.sample["public_export_allowed"] = True
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_timestamp_timezone(self):
        self.sample["evidence_recorded_at"] = "2026-10-15T22:00:00"
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_unit_conversion_synthetic(self):
        self.assertEqual(shares_to_base("12.50", "wan_share"), D("125000"))
        with self.assertRaises(ValueError):
            shares_to_base("12", "unknown")

    def test_split_does_not_create_flow_synthetic(self):
        result = estimated_flow(D(100), D(200), D(5), D(2), adjacent=True, same_asof=True)
        self.assertEqual(result["value"], "0.000000")
        self.assertEqual(result["status"], "estimated")

    def test_dates_must_align_synthetic(self):
        for adjacent, same_asof in ((False, True), (True, False)):
            result = estimated_flow(D(100), D(110), D(5), D(1), adjacent=adjacent, same_asof=same_asof)
            self.assertIsNone(result["value"])
            self.assertEqual(result["status"], "quarantined")

    def test_event_basis_required_synthetic(self):
        result = estimated_flow(D(100), D(110), D(5), None, adjacent=True, same_asof=True)
        self.assertIsNone(result["value"])

    def test_negative_flow_synthetic(self):
        result = estimated_flow(D(100), D(90), D(5), D(1), adjacent=True, same_asof=True)
        self.assertEqual(result["value"], "-50.000000")

    def test_deterministic(self):
        self.assertEqual(build(self.sample), build(self.sample))


if __name__ == "__main__":
    unittest.main()
