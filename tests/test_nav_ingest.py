import json,unittest,tempfile
from pathlib import Path
from tools.collect_nav import parse_nav,plan
from tools.build_market_page import build,canonical
ROOT=Path(__file__).resolve().parents[1]
HTML='''<p>510330 SYNTHETIC TEST ONLY</p><table><tr><th>日期</th><th>单位净值(元)</th><th>累计净值</th></tr><tr><td>2026-01-02</td><td>1.0200</td><td>9.99</td></tr><tr><td>2026-01-01</td><td>1.0000</td><td>9.90</td></tr></table>'''
class IngestTests(unittest.TestCase):
 def test_table_not_cumulative(self):
  r=parse_nav(HTML,'510330','2026-01-01','2026-01-02');self.assertEqual([x['unit_nav_cny'] for x in r],['1.0000','1.0200'])
 def test_wrong_code(self):
  with self.assertRaises(ValueError):parse_nav(HTML,'159995','2026-01-01','2026-01-02')
 def test_JS_shell_is_failure(self):
  with self.assertRaises(ValueError):parse_nav('<p>510330</p><div id="app"></div>','510330','2026-01-01','2026-01-02')
 def test_empty_range_is_failure(self):
  with self.assertRaises(ValueError):parse_nav(HTML,'510330','2026-03-01','2026-03-02')
 def test_bad_value(self):
  with self.assertRaises(ValueError):parse_nav(HTML.replace('1.0200','NaN'),'510330','2026-01-01','2026-01-02')
 def test_conflict_rejected(self):
  with self.assertRaises(ValueError):parse_nav(HTML+HTML.replace('1.0200','2.0000'),'510330','2026-01-01','2026-01-02')
 def test_request_budget(self):
  config=json.loads((ROOT/'config/market-universe.json').read_text());self.assertEqual(len(plan(config,['159995','510330'])),2)
  with self.assertRaises(ValueError):plan(config,['159995']*5)
 def test_shell_is_data_free(self):
  with tempfile.TemporaryDirectory() as t:
   result=build(Path(t)/'release');self.assertFalse(result['market_data_published']);manifest=json.loads((Path(t)/'release/public/market.manifest.json').read_text());self.assertEqual(manifest['state'],'unpublished');self.assertFalse(any(p.name.startswith('market.') and p.name!='market.manifest.json' for p in (Path(t)/'release/public').iterdir()))
 def test_output_not_overwritten(self):
  with tempfile.TemporaryDirectory() as t:
   with self.assertRaises(ValueError):build(Path(t))
 def test_schema_invalid_build_rejected(self):
  with self.assertRaises(ValueError):canonical(b'{"schema":"unknown"}')
if __name__=='__main__':unittest.main()
