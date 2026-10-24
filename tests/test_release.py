"""Release boundary tests. Synthetic mutations are not market observations."""
import copy
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile
from tools.build_page import ROOT, make_payload
from tools.build_release import build_release, audit_public, render, PUBLIC_FILES

class ReleaseTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.payload=make_payload(json.loads((ROOT/'research/p0/nav_sample_20261016.json').read_text()),json.loads((ROOT/'research/p0/share_sample_20261016.json').read_text()))
 def node_validate(self,p,good=True):
  raw=json.dumps({'schema':'ql.review-bundle/1','payload':p},ensure_ascii=False)
  code="global.window={};require('./web/release.js');let t='';process.stdin.on('data',x=>t+=x);process.stdin.on('end',()=>{try{const p=window.QLRelease.parseBundle(t);console.log(JSON.stringify(p));}catch(e){console.error(e.message);process.exitCode=2;}});"
  r=subprocess.run(['node','-e',code],input=raw,text=True,cwd=ROOT,capture_output=True,timeout=10)
  self.assertEqual(r.returncode,0 if good else 2,r.stderr)
  return json.loads(r.stdout) if good else r.stderr
 def mutate(self,f):
  p=copy.deepcopy(self.payload);f(p);self.node_validate(p,False)
 def test_valid_bundle_matches_decimal(self):
  p=self.node_validate(self.payload)
  self.assertEqual(p['flow_windows']['2026-10-15']['5'],'-710.15')
  for x in p['products']:
   old=next(y for y in self.payload['products'] if y['code']==x['code'])
   self.assertEqual(x['windows'],old['windows']);self.assertEqual(x['daily'],old['daily'])
 def test_normalized_bundle_reloads(self):self.node_validate(self.node_validate(self.payload))
 def test_tampered_return_rejected(self):self.mutate(lambda p:p['products'][0]['windows']['2026-10-15']['5'].__setitem__('display','99.99'))
 def test_tampered_relative_rejected(self):self.mutate(lambda p:p['products'][0]['windows']['2026-10-15']['5'].__setitem__('relative_pp','0.000000'))
 def test_tampered_flow_rejected(self):self.mutate(lambda p:p['flow_windows']['2026-10-15'].__setitem__('5','0.00'))
 def test_bad_code_rejected(self):self.mutate(lambda p:p['products'][0].__setitem__('code','__proto__'))
 def test_duplicate_product_rejected(self):self.mutate(lambda p:p['products'].__setitem__(1,p['products'][0]))
 def test_xss_label_rejected(self):self.mutate(lambda p:p['products'][0].__setitem__('label','<img src=x onerror=alert(1)>'))
 def test_xss_name_rejected(self):self.mutate(lambda p:p['products'][0].__setitem__('name','<script>alert(1)</script>'))
 def test_unsafe_url_rejected(self):self.mutate(lambda p:p['sources']['chinaamc-159995'].__setitem__('url','javascript:alert(1)'))
 def test_embedded_credentials_rejected(self):self.mutate(lambda p:p['sources']['chinaamc-159995'].__setitem__('url','https://user:secret@www.chinaamc.com/'))
 def test_zero_nav_rejected(self):self.mutate(lambda p:p['products'][0]['nav'].__setitem__(0,'0'))
 def test_nonfinite_rejected(self):self.mutate(lambda p:p['products'][0]['nav'].__setitem__(0,'Infinity'))
 def test_invalid_date_rejected(self):self.mutate(lambda p:p['dates'].__setitem__(0,'2026-02-30'))
 def test_duplicate_date_rejected(self):self.mutate(lambda p:p['dates'].__setitem__(1,p['dates'][0]))
 def test_asof_mismatch_rejected(self):self.mutate(lambda p:p.__setitem__('asof','2026-10-14'))
 def test_public_flag_not_admitted(self):self.mutate(lambda p:p.__setitem__('public_export_allowed',True))
 def test_auto_update_claim_rejected(self):self.mutate(lambda p:p.__setitem__('auto_updated',True))
 def test_unverified_flow_cannot_be_admitted(self):self.mutate(lambda p:p.__setitem__('accepted_flow_cny','1'))
 def test_missing_history_cannot_be_filled(self):self.mutate(lambda p:p['products'][0]['windows']['2026-10-15']['60'].__setitem__('value','0.000000'))
 def test_unknown_personal_fields_not_forwarded(self):
  p=copy.deepcopy(self.payload);p['personal']={'cost':'secret'};self.assertNotIn('personal',self.node_validate(p))
 def test_half_up_synthetic(self):
  code="global.window={};require('./web/release.js');const r=window.QLRelease.rounded;console.log(JSON.stringify([r(49996n,10000000n,2),r(-1n,10000n,2),r(5n,1000n,2)]));"
  r=subprocess.run(['node','-e',code],capture_output=True,text=True,cwd=ROOT,check=True,timeout=10)
  self.assertEqual(json.loads(r.stdout),['0.00','-0.00','0.01'])
 def test_public_has_null_payload_no_market_values(self):
  s=render(None);self.assertIn('type="application/json">null</script>',s)
  for raw in ['1.0038','13772.98','2026-10-15','public_export_allowed":false']:
   self.assertNotIn(raw,s)
 def test_public_archive_separate_from_private(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'release';build_release(out)
   self.assertEqual(set(p.name for p in (out/'public').iterdir()),PUBLIC_FILES)
   with ZipFile(out/'pages-public.zip') as z:self.assertEqual(set(z.namelist()),PUBLIC_FILES)
   self.assertTrue((out/'private/ql-review.json').is_file());audit_public(out/'public')
 def test_public_audit_rejects_extra_private_file(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'release';build_release(out);(out/'public/private.json').write_text('secret')
   with self.assertRaises(ValueError):audit_public(out/'public')
 def test_public_audit_rejects_fake_manifest(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'release';build_release(out);(out/'public/index.html').write_text(render(self.payload))
   with self.assertRaises(ValueError):audit_public(out/'public')
 def test_previous_version_not_overwritten(self):
  with tempfile.TemporaryDirectory() as t:
   out=Path(t)/'release';build_release(out)
   with self.assertRaises(ValueError):build_release(out)
 def test_public_content_independent_of_private_values(self):
  with tempfile.TemporaryDirectory() as t:
   t=Path(t);nav=json.loads((ROOT/'research/p0/nav_sample_20261016.json').read_text())
   nav['original_rows'][0]['净值']='1.1000';nf=t/'nav.json';nf.write_text(json.dumps(nav))
   build_release(t/'first');build_release(t/'second',nav_file=nf)
   for name in PUBLIC_FILES:self.assertEqual((t/'first/public'/name).read_bytes(),(t/'second/public'/name).read_bytes())
   self.assertNotEqual((t/'first/private/ql-review.json').read_bytes(),(t/'second/private/ql-review.json').read_bytes())
 def test_longer_unreviewed_contract_rejected(self):
  self.mutate(lambda p:p['dates'].append('2026-10-16'))
if __name__=='__main__':unittest.main()
