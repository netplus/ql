"""Deployment packaging tests; HTTP fixtures are synthetic, not a live Pages site."""
import base64
import copy
import hashlib
import json
import os
import tempfile
import threading
import unittest
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError
import socket

from tools.build_pages_candidate import (build, boot_script, digest, fingerprint,
                                        integrity, make_candidate, read_legacy)
from tools.verify_pages import base_url, expected_files, verify


def source_assets():
    directory = os.getenv('QL_LEGACY_DIR')
    if directory:
        return read_legacy(Path(directory))
    # Use the actual source build on a normal repository checkout.
    from tools.build_release import public_assets
    return public_assets()


class CandidateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.legacy = source_assets()

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root/'legacy'
        self.source.mkdir()
        for n, b in self.legacy.items():
            (self.source/n).write_bytes(b)
        m={'schema':'ql.public-shell/1','version':'p1.1-local-bundle/1',
           'market_data_included':False,'personal_data_included':False,
           'files':{n:digest(b) for n,b in sorted(self.legacy.items())}}
        (self.source/'release.manifest.json').write_text(json.dumps(m))
        self.target = self.root/'candidate'
        build(self.source, self.target)
        self.candidate = make_candidate(self.legacy)

    def tearDown(self):
        self.tmp.cleanup()

    def test_deterministic(self):
        self.assertEqual(self.candidate,make_candidate(self.legacy))

    def test_fingerprint_changes_on_content_change(self):
        self.assertNotEqual(fingerprint('app.js',b'a'),fingerprint('app.js',b'b'))

    def test_sri_hash_matches(self):
        self.assertEqual(integrity(b'abc'),'sha256-'+base64.b64encode(hashlib.sha256(b'abc').digest()).decode())

    def test_manifest_checks_all_local_bytes(self):
        checked=expected_files(self.target)
        self.assertEqual(len(checked),12)
        self.assertIn('index.html',checked)

    def test_empty_payload_and_same_origin_csp(self):
        html=self.candidate['index.html'].decode()
        self.assertIn('<script id="ql-data" type="application/json">null</script>',html)
        self.assertIn("connect-src 'none'",html)
        self.assertIn("script-src 'self'",html)
        self.assertEqual(html.count(' integrity="sha256-'),4)

    def test_old_resources_retained_byte_for_byte(self):
        for n in ['app.js','release.js','start.js','style.css','release.css']:
            self.assertEqual(self.candidate[n],self.legacy[n])

    def test_new_start_references_exact_app_hash(self):
        manifest=json.loads(self.candidate['release.manifest.json'])
        start=self.candidate[manifest['entrypoints']['start.js']].decode()
        self.assertIn(manifest['entrypoints']['app.js'],start)
        self.assertIn(integrity(self.legacy['app.js']),start)
        self.assertNotIn('removeItem',start)
        self.assertNotIn('setItem',start)

    def test_existing_output_rejected(self):
        with self.assertRaises(ValueError):build(self.source,self.target)

    def test_extra_source_file_rejected(self):
        (self.source/'private.json').write_text('{}')
        with self.assertRaises(ValueError):read_legacy(self.source)

    def test_tampered_source_rejected_even_with_rehashed_manifest(self):
        (self.source/'app.js').write_text('window.unreviewed=true;')
        path=self.source/'release.manifest.json'
        m=json.loads(path.read_text());m['files']['app.js']=digest((self.source/'app.js').read_bytes())
        path.write_text(json.dumps(m))
        with self.assertRaises(ValueError):read_legacy(self.source)

    def test_symlink_source_rejected(self):
        p=self.source/'app.js'; p.unlink();p.symlink_to(self.source/'release.js')
        with self.assertRaises(ValueError):read_legacy(self.source)

    def test_local_build_tamper_rejected(self):
        (self.target/'app.js').write_text('different')
        with self.assertRaises(ValueError):expected_files(self.target)

    def test_unsafe_local_manifest_path_rejected(self):
        p=self.target/'release.manifest.json';m=json.loads(p.read_text())
        m['files']['../outside.js']='0'*64;p.write_text(json.dumps(m))
        with self.assertRaises(ValueError):expected_files(self.target)

    def test_https_required(self):
        with self.assertRaises(ValueError):base_url('http://example.com/ql/',False)
        with self.assertRaises(ValueError):base_url('http://127.0.0.1/ql/',False)

    def test_only_explicit_loopback_allowed(self):
        self.assertEqual(base_url('http://127.0.0.1:123/ql',True),'http://127.0.0.1:123/ql/')
        with self.assertRaises(ValueError):base_url('http://example.com/ql',True)

    def test_credentials_and_queries_rejected(self):
        for url in ('https://user:password@site.test/ql/','https://site.test/ql/?x=1',
                    'https://site.test/ql/#data','https://site.test/a/../ql/'):
            with self.assertRaises(ValueError):base_url(url,False)

    def test_network_failure_classified_not_called_site_down(self):
        with patch('tools.verify_pages.build_opener') as o:
            o.return_value.open.side_effect=URLError(socket.gaierror(-3,'synthetic DNS failure'))
            r=verify('https://site.test/ql/',self.target)
        self.assertFalse(r['http_verified'])
        self.assertEqual(r['result'],'dns_error')
        self.assertEqual(len(r['checks']),1)

    def test_invalid_timeout_rejected(self):
        with self.assertRaises(ValueError):verify('https://site.test/',self.target,timeout=0)

    def http_case(self, mode):
        assets=self.candidate
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*a):pass
            def do_GET(self):
                name=self.path.removeprefix('/ql/') or 'index.html'
                if mode=='redirect' and name=='index.html':
                    self.send_response(302);self.send_header('Location','https://outside.invalid/');self.end_headers();return
                if mode=='404' and name=='index.html':
                    self.send_response(404);self.end_headers();return
                if mode=='missing_asset' and name.startswith('app.'):
                    self.send_response(404);self.end_headers();return
                content=assets[name]
                if mode=='old_index' and name=='index.html':content=b'<html>old or wrong branch</html>'
                if mode=='oversize' and name=='index.html':content=b'x'*(512*1024+1)
                if mode=='bad_asset' and name.startswith('app.') and name!='app.js':content=b'tampered'
                mime={'html':'text/html','css':'text/css','js':'text/javascript','json':'application/json'}[name.rsplit('.',1)[1]]
                if mode=='mime' and name=='index.html':mime='text/plain'
                self.send_response(200);self.send_header('Content-Type',mime);self.end_headers();self.wfile.write(content)
        server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:return verify(f'http://127.0.0.1:{server.server_port}/ql/',self.target,allow_loopback=True)
        finally:server.shutdown();server.server_close();thread.join()

    def test_http_success_is_not_browser_acceptance(self):
        r=self.http_case('ok');self.assertTrue(r['http_verified']);self.assertFalse(r['browser_verified'])
        self.assertEqual(len(r['checks']),12)

    def test_404_not_called_pages_disabled(self):
        r=self.http_case('404');self.assertEqual(r['result'],'http_error');self.assertEqual(r['checks'][0]['http_status'],404)

    def test_wrong_branch_or_old_index(self):
        self.assertEqual(self.http_case('old_index')['result'],'content_mismatch')

    def test_redirect_not_followed(self):
        self.assertEqual(self.http_case('redirect')['result'],'redirect_rejected')

    def test_missing_asset(self):
        self.assertEqual(self.http_case('missing_asset')['result'],'http_error')

    def test_changed_asset(self):
        self.assertEqual(self.http_case('bad_asset')['result'],'content_mismatch')

    def test_wrong_mime(self):
        self.assertEqual(self.http_case('mime')['result'],'wrong_content_type')

    def test_oversized_response(self):
        self.assertEqual(self.http_case('oversize')['result'],'response_too_large')


if __name__=='__main__':unittest.main()
