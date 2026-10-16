"""Real displayed inputs and clearly separated synthetic protection tests."""
import copy
import json
import socket
import tempfile
import unittest
from decimal import Decimal as D
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit

from tools.audit_share_flow import base_shares, build, number, validate
from tools.probe_share_sources import classify_error, plans, probe

ROOT = Path(__file__).resolve().parents[1]


class ShareEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sample = json.loads((ROOT/'research/p0/share_sample_20261016.json').read_text(encoding='utf-8'))

    def test_real_six_dates_five_intervals(self):
        result = build(self.sample)
        self.assertEqual(len(result['normalized']), 6)
        self.assertEqual(len(result['daily']), 5)

    def test_real_conditional_daily_values(self):
        actual = [D(r['conditional_flow_cny']) for r in build(self.sample)['daily']]
        self.assertEqual(actual, list(map(D, ['0','548500','-4368000','-2190000','-1092000'])))

    def test_real_conditional_sum(self):
        self.assertEqual(D(build(self.sample)['summary']['conditional_flow_sum_cny']), D('-7101500'))

    def test_real_share_unit_normalization(self):
        first = build(self.sample)['normalized'][0]
        self.assertEqual(D(first['shares_from_display']), D('137729800'))

    def test_event_unknown_never_admitted(self):
        result = build(self.sample)
        self.assertTrue(all(r['accepted_flow_cny'] is None for r in result['daily']))
        self.assertIsNone(result['summary']['accepted_flow_sum_cny'])
        self.assertFalse(result['historical_signal_eligibility'])

    def test_real_aum_change_is_not_flow(self):
        last = build(self.sample)['daily'][-1]
        self.assertEqual(D(last['aum_change_from_display_cny']), D('-1488689.4'))
        self.assertEqual(D(last['nav_component_from_display_cny']), D('-396689.4'))
        self.assertNotEqual(last['aum_change_from_display_cny'], last['conditional_flow_cny'])

    def test_corroborating_pcf_valuation_date(self):
        check = self.sample['corroboration']
        nav = next(r for r in self.sample['original_nav_rows'] if r['日期']==check['valuation_date'])
        self.assertEqual(D(check['reported_unit_nav_cny']), D(nav['单位净值(元)']))
        self.assertNotEqual(check['valuation_date'], check['pcf_announcement_date'])

    def test_deterministic(self):
        self.assertEqual(build(self.sample), build(copy.deepcopy(self.sample)))

    def test_missing_share_not_bridged_synthetic(self):
        self.sample['original_share_rows'].pop(3)
        result = build(self.sample)
        self.assertIsNone(result['daily'][2]['conditional_flow_cny'])
        self.assertIsNone(result['daily'][3]['conditional_flow_cny'])
        self.assertIsNone(result['summary']['conditional_flow_sum_cny'])

    def test_missing_nav_not_forward_filled_synthetic(self):
        self.sample['original_nav_rows'].pop()
        row = build(self.sample)['daily'][-1]
        self.assertIsNone(row['conditional_flow_cny'])
        self.assertEqual(D(row['displayed_share_change']), D('-1000000'))
        self.assertEqual(row['reason'], 'missing_same_date_nav')

    def test_calendar_cannot_remove_a_trade_day_synthetic(self):
        self.sample['sample_calendar'].remove('2026-10-13')
        for table in ('original_nav_rows','original_share_rows'):
            self.sample[table] = [r for r in self.sample[table] if r['日期']!='2026-10-13']
        with self.assertRaises(ValueError):
            build(self.sample)

    def test_duplicate_rejected_synthetic(self):
        self.sample['original_share_rows'].append(copy.deepcopy(self.sample['original_share_rows'][0]))
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_wrong_code_rejected_synthetic(self):
        self.sample['original_share_rows'][0]['code'] = '510300'
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_finite_numeric_string_required_synthetic(self):
        for value in ('NaN','Infinity','-Infinity','bad','', 1.2):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)

    def test_zero_nav_rejected_synthetic(self):
        self.sample['original_nav_rows'][0]['单位净值(元)'] = '0'
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_units_not_interchangeable_synthetic(self):
        self.assertEqual(base_shares('12.5','wan_share'), D('125000'))
        self.assertEqual(base_shares('12.5','share'), D('12.5'))
        for value, unit in (('1','unknown'),('-1','share')):
            with self.assertRaises(ValueError):
                base_shares(value,unit)

    def test_semantic_mislabel_rejected_synthetic(self):
        self.sample['sources']['sse-product-shares']['field'] = '当日累计可赎回份额上限'
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_no_public_export_switch_synthetic(self):
        self.sample['public_export_allowed'] = True
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_no_unreviewed_event_upgrade_synthetic(self):
        self.sample['event_basis_status'] = 'verified'
        with self.assertRaises(ValueError):
            validate(self.sample)

    def test_naive_timestamp_rejected_synthetic(self):
        self.sample['evidence_recorded_at'] = '2026-10-16T16:00:00'
        with self.assertRaises(ValueError):
            validate(self.sample)


class ShareProbeTests(unittest.TestCase):
    def test_szse_is_historical_not_current_snapshot(self):
        request = plans('2026-10-14','2026-10-15')[1]
        parsed = urlsplit(request['url'])
        query = parse_qs(parsed.query)
        self.assertEqual(parsed.netloc, 'www.szse.cn')
        self.assertEqual(query['CATALOGID'], ['scsj_fund_jjgm'])
        self.assertEqual(query['txtStart'], ['2026-10-14'])
        self.assertEqual(query['txtEnd'], ['2026-10-15'])
        self.assertEqual(request['raw_share_unit'], 'share')

    def test_sse_single_date_bounded_first_page(self):
        request = plans('2026-10-14','2026-10-15')[0]
        query = parse_qs(urlsplit(request['url']).query)
        self.assertEqual(query['STAT_DATE'], ['2026-10-15'])
        self.assertEqual(query['pageHelp.pageSize'], ['25'])
        self.assertEqual(request['raw_share_unit'], 'wan_share')

    def test_probe_range_guard_synthetic(self):
        for start,end in [('2026-10-16','2026-10-15'),('2026-01-01','2026-10-15'),('bad','2026-10-15')]:
            with self.assertRaises(ValueError):
                plans(start,end)

    def test_dns_classification_synthetic(self):
        error = URLError(socket.gaierror(-3,'test-only failure'))
        self.assertEqual(classify_error(error),'dns_resolution_failed')

    def test_network_failure_not_empty_success_synthetic(self):
        error = URLError(socket.gaierror(-3,'test-only failure'))
        with tempfile.TemporaryDirectory() as d, patch('tools.probe_share_sources.urlopen',side_effect=error):
            result = probe(plans('2026-10-14','2026-10-15')[1],Path(d),1)
            self.assertEqual(result['status'],'error')
            self.assertFalse(result['response_archived'])
            self.assertFalse(result['market_records_admitted'])


if __name__ == '__main__':
    unittest.main()
