"""Release integration invariants; browser/HTTP execution is a separate CI step."""
import base64
import hashlib
import json
import tempfile
import unittest
from html.parser import HTMLParser
from pathlib import Path
from tools.build_market_page import build
from tools.test_market_http import fixture, write_fixture

class Assets(HTMLParser):
    def __init__(self):super().__init__();self.tags=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if (tag=='script' and 'src' in a) or (tag=='link' and a.get('rel')=='stylesheet'):
            self.tags.append((tag,a))

class HTTPBuildTests(unittest.TestCase):
    def test_all_external_assets_have_valid_sri(self):
        with tempfile.TemporaryDirectory() as d:
            build(Path(d)/'b');root=Path(d)/'b/public';parser=Assets()
            parser.feed((root/'index.html').read_text())
            self.assertEqual(len(parser.tags),5)
            for tag,a in parser.tags:
                path=a.get('src') or a['href'];self.assertTrue(path.startswith('./'))
                expected='sha384-'+base64.b64encode(hashlib.sha384((root/path[2:]).read_bytes()).digest()).decode()
                self.assertEqual(a['integrity'],expected)
            self.assertIn('market-boot.',parser.tags[1][1]['src'])
    def test_public_shell_stays_unpublished(self):
        with tempfile.TemporaryDirectory() as d:
            build(Path(d)/'b');r=Path(d)/'b/public'
            self.assertEqual(json.loads((r/'market.manifest.json').read_text())['state'],'unpublished')
            self.assertFalse(json.loads((r/'release.manifest.json').read_text())['market_data_included'])
    def test_synthetic_feed_is_content_addressed(self):
        with tempfile.TemporaryDirectory() as d:
            r=Path(d);write_fixture(r,'http-synthetic/1')
            m=json.loads((r/'market.manifest.json').read_text());b=(r/m['file']).read_bytes()
            self.assertEqual(hashlib.sha256(b).hexdigest(),m['sha256'])
            self.assertEqual(len(b),m['bytes'])
            self.assertIn('合成测试',b.decode())
    def test_fixture_has_no_holdings(self):
        b=fixture();self.assertNotIn('holdings',b);self.assertNotIn('notes',b)
        self.assertFalse(b['auto_updated'])
        self.assertTrue(all(p['name'].startswith('仅用于浏览器测试') for p in b['products']))
    def test_preview_also_contains_boot_guard(self):
        with tempfile.TemporaryDirectory() as d:
            build(Path(d)/'b')
            self.assertIn('QLMarketBoot', (Path(d)/'b/preview.html').read_text())

if __name__=='__main__':unittest.main()
