"""Fresh real NAV/PCF excerpts and explicitly synthetic negative tests."""
import copy
import json
import unittest
from decimal import Decimal as D
from pathlib import Path
from tools.reproduce_p0 import build, estimated_flow
from tools.audit_pcf import build_pcf, known_by

ROOT = Path(__file__).resolve().parents[1]


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.nav = json.loads((ROOT/'research/p0/nav_sample_20261016.json').read_text())
        self.pcf = json.loads((ROOT/'research/p0/pcf_sample_20261016.json').read_text())

    def test_five_products_thirty_observations(self):
        result = build(self.nav)
        self.assertEqual(len(result['normalized']), 30)
        self.assertEqual(len(result['summaries']), 5)

    def test_new_product_results(self):
        rows = {r['code']:r for r in build(self.nav)['summaries']}
        self.assertEqual(rows['512010']['changes']['5']['value'], '-1.076115')
        self.assertEqual(rows['159819']['changes']['5']['value'], '-9.886477')
        self.assertTrue(all(r['latest_daily_matches_reported_rounding'] for r in rows.values()))

    def test_new_flow_and_long_windows_missing(self):
        for row in build(self.nav)['summaries']:
            self.assertIsNone(row['estimated_flow_cny']['value'])
            for horizon in ('20','60'):
                self.assertIsNone(row['changes'][horizon]['value'])

    def test_pcf_conditional_precision(self):
        rows = build_pcf(self.pcf)['results']
        self.assertEqual(rows[0]['conditional_implied_nav_cny'], '0.37686052')
        self.assertEqual(rows[1]['conditional_implied_nav_cny'], '1.44473884')
        self.assertTrue(all(x['within_conditional_rounding_tolerance'] for x in rows))
        self.assertEqual(D(rows[1]['basket_rounding_residual_cny']), D('77.68'))

    def test_caps_are_not_observed_shares(self):
        for row in build_pcf(self.pcf)['results']:
            self.assertIsNone(row['observed_total_shares'])
            self.assertIsNone(row['estimated_net_flow_cny'])
        changed = copy.deepcopy(self.pcf)
        changed['records'][0]['redemption_limit_shares'] = '9999999999'
        self.assertEqual(build_pcf(changed)['results'], build_pcf(self.pcf)['results'])

    def test_cannot_smuggle_cap_into_total_shares(self):
        self.pcf['records'][0]['daily_total_shares'] = self.pcf['records'][0]['redemption_limit_shares']
        with self.assertRaises(ValueError):
            build_pcf(self.pcf)

    def test_pcf_missing_is_not_zero(self):
        self.assertTrue(build_pcf(self.pcf)['results'][0]['pcf_unit_nav_missing'])

    def test_no_historical_knowledge_backfill(self):
        self.assertFalse(any(r['eligible_at_20261015_close'] for r in build_pcf(self.pcf)['results']))
        self.assertFalse(known_by(self.pcf['evidence_recorded_at'], '2026-10-15T23:59:59+08:00'))
        self.assertTrue(known_by(self.pcf['evidence_recorded_at'], self.pcf['evidence_recorded_at']))
        with self.assertRaises(ValueError):
            known_by('2026-10-16T09:00:00', '2026-10-16T10:00:00+08:00')

    def test_pcf_wrong_date_rejected(self):
        self.pcf['records'][0]['valuation_date'] = '2026-10-16'
        with self.assertRaises(ValueError):
            build_pcf(self.pcf)

    def test_no_public_export(self):
        self.pcf['public_export_allowed'] = True
        with self.assertRaises(ValueError):
            build_pcf(self.pcf)

    def test_double_rounding_regression_synthetic(self):
        # True 0.0049996% -> 0.00%; rounding first to 6dp would incorrectly produce 0.01%.
        code = '159995'
        for row in self.nav['original_rows']:
            if row['code'] == code and row['日期'] == '2026-10-14':
                row['净值'] = '1'
            if row['code'] == code and row['日期'] == '2026-10-15':
                row['净值'] = '1.000049996'
        self.nav['sources']['chinaamc-159995']['latest_reported_daily_change_pct'] = '0.00'
        self.assertTrue(build(self.nav)['summaries'][0]['latest_daily_matches_reported_rounding'])

    def test_nonfinite_flow_rejected_synthetic(self):
        for bad in ('NaN', 'Infinity', '-Infinity'):
            for index in range(4):
                values = [D(100), D(110), D(5), D(1)]
                values[index] = D(bad)
                with self.assertRaises(ValueError):
                    estimated_flow(*values, adjacent=True, same_asof=True)


if __name__ == '__main__':
    unittest.main()
