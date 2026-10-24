"""Synthetic wire/charset regression tests; no observed market NAV values."""
import gzip
import hashlib
import json
import tempfile
import unittest
from email.message import Message
from pathlib import Path
from unittest.mock import patch
from tools import collect_nav
from tools.nav_transport import decode_html, LIMIT

class DecodeTests(unittest.TestCase):
    def test_utf8(self):
        html, m = decode_html('日期'.encode()); self.assertEqual(html,'日期'); self.assertEqual(m['encoding'],'utf-8')
    def test_gbk_meta(self):
        text='<meta charset="gbk">日期'
        html,m=decode_html(text.encode('gbk')); self.assertEqual(html,text); self.assertEqual(m['encoding_source'],'html_meta')
    def test_legacy_meta(self):
        text='<META http-equiv="Content-Type" content="text/html; charset=gb2312">日期'
        self.assertEqual(decode_html(text.encode('gb2312'))[0],text)
    def test_gzip(self):
        self.assertEqual(decode_html(gzip.compress('日期'.encode()),None,'gzip')[0],'日期')
    def test_gzip_expansion_bound(self):
        with self.assertRaisesRegex(ValueError,'decoded_response_too_large'):
            decode_html(gzip.compress(b'x'*(LIMIT+1)),None,'gzip')
    def test_wire_bound(self):
        with self.assertRaisesRegex(ValueError,'response_too_large'): decode_html(b'x'*(LIMIT+1))
    def test_invalid_utf8_not_replaced(self):
        with self.assertRaises(UnicodeDecodeError):decode_html(b'\xff')
    def test_unknown_charset(self):
        with self.assertRaisesRegex(ValueError,'unsupported_encoding'):decode_html(b'x','iso-8859-1')
    def test_unknown_compression(self):
        with self.assertRaisesRegex(ValueError,'unsupported_content_encoding'):decode_html(b'x',None,'br')
    def test_undeclared_gzip(self):
        with self.assertRaisesRegex(ValueError,'undeclared_compressed_response'):decode_html(gzip.compress(b'x'))
    def test_conflicting_declarations(self):
        with self.assertRaisesRegex(ValueError,'conflicting_meta_charset'):
            decode_html(b'<meta charset="utf-8"><meta charset="gbk">')
    def test_bom(self):
        self.assertEqual(decode_html(b'\xef\xbb\xbfhello')[0],'hello')
        with self.assertRaisesRegex(ValueError,'conflicting_bom_charset'):decode_html(b'\xef\xbb\xbfhello','gbk')
    def test_archives_bytes_before_decode_failure(self):
        class Response:
            status=200
            headers=Message()
            headers['Content-Type']='text/html; charset=utf-8'
            def geturl(self):return 'https://www.chinaamc.com/fund/159995/index.shtml'
            def read(self,n):return b'\xff'
            def __enter__(self):return self
            def __exit__(self,*args):pass
        with tempfile.TemporaryDirectory() as tmp, patch.object(collect_nav.urllib.request,'build_opener') as op:
            op.return_value.open.return_value=Response()
            report=collect_nav.acquire([{'code':'159995','url':Response().geturl()}],'2026-10-22','2026-10-23',Path(tmp)/'raw')
            r=report['results'][0]
            self.assertEqual(r['error_class'],'UnicodeDecodeError');self.assertTrue(r['raw_response_archived'])
            self.assertEqual(r['raw_sha256'],hashlib.sha256(b'\xff').hexdigest())
    def test_cycle_reparse_gzip_and_gbk(self):
        from tools.run_nav_cycle import assemble,make_plan,stamp
        root=Path(__file__).resolve().parents[1]
        config=json.loads((root/'config/market-universe.json').read_text())
        calendar=json.loads((root/'config/calendar-2026-oct.json').read_text())
        plan=make_plan(config,calendar,['159995','510330'],'2026-10-22','2026-10-23')
        with tempfile.TemporaryDirectory() as tmp:
            d=Path(tmp);results=[]
            for item in plan['requests']:
                html=f'<meta charset="gbk"><h1>{item["code"]} synthetic</h1><table><tr><th>日期</th><th>净值</th></tr><tr><td>2026-10-22</td><td>1</td></tr><tr><td>2026-10-23</td><td>2</td></tr></table>'
                raw=gzip.compress(html.encode('gbk'));code=item['code']
                (d/(code+'.html')).write_bytes(raw)
                rows=collect_nav.parse_nav(html,code,plan['start'],plan['end'])
                (d/(code+'.rows.json')).write_text(json.dumps(rows))
                results.append({**item,'mode':'http_response','status':'observed','latest_observed_date':plan['end'],
                    'raw_response_archived':True,'raw_file':code+'.html','row_count':2,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                    'encoding':'gbk','header_charset':None,'content_encoding':'gzip','finished_at':stamp()})
            bundle,checks=assemble(config,plan,{'results':results},d)
            self.assertEqual(len(bundle['products']),2);self.assertEqual(len(checks),2)

class DivMarkupTests(unittest.TestCase):
    def grid(self,headers=('日期','净值','累计净值'),values=('2026-10-23','1.2345','9.8765')):
        row=lambda values:'<div class="tr">'+''.join('<div class="td"><span>'+v+'</span></div>' for v in values)+'</div>'
        return '<h1>159995 synthetic</h1><div class="table table3"><div class="th">'+row(headers)+'</div><div class="scroll-tab"><div class="tb">'+row(values)+'</div></div></div>'
    def parse(self,html):return collect_nav.parse_nav(html,'159995','2026-10-22','2026-10-23')
    def test_div_nav_not_cumulative(self):
        self.assertEqual(self.parse(self.grid())[0]['unit_nav_cny'],'1.2345')
    def test_cumulative_only_rejected(self):
        with self.assertRaisesRegex(ValueError,'no_dated_NAV_table'):
            self.parse(self.grid(('日期','累计净值'),('2026-10-23','9.8765')))
    def test_performance_grid_ignored(self):
        with self.assertRaisesRegex(ValueError,'no_dated_NAV_table'):
            self.parse(self.grid(('项目','净值增长率(%)'),('过去一周','1.23')))
    def test_conflicting_native_and_div_rejected(self):
        other='<table><tr><th>日期</th><th>净值</th></tr><tr><td>2026-10-23</td><td>2</td></tr></table>'
        with self.assertRaisesRegex(ValueError,'conflicting_duplicate'):self.parse(self.grid()+other)
    def test_negative_div_nav_rejected(self):
        with self.assertRaisesRegex(ValueError,'invalid_NAV'):self.parse(self.grid(values=('2026-10-23','-1','9')))
    def test_duplicate_equal_values_deduplicated(self):
        self.assertEqual(len(self.parse(self.grid()+self.grid())),1)
    def test_tableless_loose_rows_rejected(self):
        with self.assertRaisesRegex(ValueError,'no_dated_NAV_table'):
            self.parse(self.grid().replace('class="table table3"','class="not-a-table"'))

if __name__=='__main__':unittest.main()
