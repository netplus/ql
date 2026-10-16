"""Private page contract tests; no market performance claims."""
import copy
import json
import tempfile
import unittest
from pathlib import Path
from tools.build_page import ROOT, make_payload, build, checked_source

class PageTests(unittest.TestCase):
 def setUp(self):
  self.nav=json.loads((ROOT/'research/p0/nav_sample_20261016.json').read_text())
  self.share=json.loads((ROOT/'research/p0/share_sample_20261016.json').read_text())
 def payload(self): return make_payload(self.nav,self.share)
 def test_six_products_and_36_navs(self):
  p=self.payload();self.assertEqual(len(p['products']),6);self.assertEqual(sum(len(x['nav']) for x in p['products']),36)
 def test_exact_five_day_display(self):
  p=self.payload()['products'][0];self.assertEqual(p['windows']['2026-10-15']['5']['value'],'-8.009564');self.assertEqual(p['windows']['2026-10-15']['5']['display'],'-8.01')
 def test_first_date_not_zero(self):
  for p in self.payload()['products']:self.assertIsNone(p['daily'][0])
 def test_unavailable_20_60(self):
  for p in self.payload()['products']:
   for d in self.nav['sample_calendar']:
    for h in ['20','60']:self.assertIsNone(p['windows'][d][h]['value'])
 def test_incomplete_window_not_shortened(self):
  for p in self.payload()['products']:self.assertIsNone(p['windows']['2026-10-14']['5']['value'])
 def test_dated_condition_flow(self):
  p=self.payload();self.assertEqual(p['flow_windows']['2026-10-15']['5'],'-710.15');self.assertEqual(p['flow_windows']['2026-10-15']['1'],'-109.20');self.assertIsNone(p['flow_windows']['2026-10-09']['5'])
 def test_official_flow_stays_null(self):self.assertIsNone(self.payload()['accepted_flow_cny'])
 def test_missing_share_not_zero(self):self.assertEqual(self.payload()['products'][0]['shares_wan'],[None]*6)
 def test_url_allowlist(self):
  for url in ['javascript:alert(1)','https://evil.example/data','http://www.sse.com.cn/data','https://user:secret@www.sse.com.cn/']:
   with self.assertRaises(ValueError):checked_source({'url':url},'2026-10-16')
 def test_missing_date_propagates(self):
  self.nav['original_rows']=[r for r in self.nav['original_rows'] if not(r['code']=='159995' and r['日期']=='2026-10-12')]
  p=self.payload()['products'][0];self.assertIsNone(p['windows']['2026-10-15']['5']['value'])
 def test_public_build_blocked(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):build(Path(t)/'public.html','public')
   self.assertFalse((Path(t)/'public.html').exists())
 def test_deterministic_standalone(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'index.html';m=build(p);a=p.read_bytes();build(p);self.assertEqual(a,p.read_bytes());self.assertLess(m['output_bytes'],150000)
   s=a.decode();self.assertNotIn('__PAYLOAD__',s);self.assertNotIn('src="http',s);self.assertIn("connect-src 'none'",s)
if __name__=='__main__':unittest.main()
