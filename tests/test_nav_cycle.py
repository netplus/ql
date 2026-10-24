"""Synthetic acceptance/control-flow tests, not real market observations."""
import copy
import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tools import run_nav_cycle as cycle

ROOT = Path(__file__).resolve().parents[1]

class NavCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = json.loads((ROOT/'config/market-universe.json').read_text())
        self.calendar = json.loads((ROOT/'config/calendar-2026-oct.json').read_text())
        self.planned = cycle.make_plan(self.config, self.calendar, ['159995','510330'], '2026-10-22','2026-10-23')

    def fixture(self, requests, start, end, output, *, runtime_id='synthetic'):
        output.mkdir()
        results = []
        for i, item in enumerate(requests):
            # Obvious synthetic table; never exported into real evidence fixtures.
            html = f'<h1>synthetic test {item["code"]}</h1><table><tr><th>日期</th><th>单位净值(元)</th></tr><tr><td>{start}</td><td>1.0000</td></tr><tr><td>{end}</td><td>{1+i}.0100</td></tr></table>'
            raw=html.encode(); (output/(item['code']+'.html')).write_bytes(raw)
            rows=cycle.collect_nav.parse_nav(html,item['code'],start,end)
            cycle.write_json(output/(item['code']+'.rows.json'),rows)
            results.append({**item,'status':'observed','mode':'http_response','row_count':2,
                'latest_observed_date':end,'raw_response_archived':True,'raw_file':item['code']+'.html',
                'encoding':'utf-8','http_status':200,'raw_sha256':hashlib.sha256(raw).hexdigest(),
                'finished_at':cycle.stamp()})
        return {'results':results,'target_runtime':runtime_id}

    def evidence(self):
        d=self.root/'raw'
        return self.fixture(self.planned['requests'],'2026-10-22','2026-10-23',d),d

    def test_dry_run_has_no_network_or_output(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/run_nav_cycle.py'),'--start','2026-10-22','--end','2026-10-23','--output',str(self.root/'new')],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['mode'],'dry_run')
        self.assertFalse((self.root/'new').exists())

    def test_invalid_range_rejected(self):
        for start,end in [('2026-10-10','2026-10-23'),('2026-10-22','2026-10-26'),('2026-10-23','2026-10-22')]:
            with self.assertRaises(ValueError):cycle.make_plan(self.config,self.calendar,['159995','510330'],start,end)

    def test_duplicate_universe_rejected(self):
        self.config['products'].append(self.config['products'][0])
        with self.assertRaises(cycle.CycleError):cycle.make_plan(self.config,self.calendar,['159995','510330'],'2026-10-22','2026-10-23')

    def test_benchmark_must_be_selected(self):
        with self.assertRaises(cycle.CycleError):cycle.make_plan(self.config,self.calendar,['159995'],'2026-10-22','2026-10-23')

    def test_bad_endpoint_rejected(self):
        self.config['products'][0]['nav_url']='https://example.com/private'
        with self.assertRaises(ValueError):cycle.make_plan(self.config,self.calendar,['159995','510330'],'2026-10-22','2026-10-23')

    def test_calendar_not_inferred_from_rows(self):
        self.planned['calendar']['sessions'].insert(1,'2026-10-22-INVALID')
        report,d=self.evidence()
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_response_code_scope(self):
        report,d=self.evidence();report['results'][1]['code']='159995'
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_raw_hash_required(self):
        report,d=self.evidence();(d/'159995.html').write_text('tamper')
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_parsed_rows_must_match_raw(self):
        report,d=self.evidence();cycle.write_json(d/'159995.rows.json',[])
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_stale_not_new_date(self):
        report,d=self.evidence();report['results'][0]['status']='stale'
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_non_http_evidence_rejected(self):
        report,d=self.evidence();report['results'][0]['mode']='web_text_transcription'
        with self.assertRaises(cycle.CycleError):cycle.assemble(self.config,self.planned,report,d)

    def test_failed_cycle_does_not_build_or_leak_error_content(self):
        report={'results':[{'code':x['code'],'status':'error','reason':'fake-secret-sentinel','error_class':'ValueError'} for x in self.planned['requests']]}
        with patch.object(cycle.collect_nav,'acquire',return_value=report):
            result=cycle.execute(self.config,self.planned,self.root/'failed')
        self.assertEqual(result['status'],'blocked');self.assertFalse((self.root/'failed/build').exists())
        self.assertNotIn('fake-secret-sentinel',json.dumps(result))

    def test_complete_synthetic_cycle_builds_private_preview(self):
        with patch.object(cycle.collect_nav,'acquire',side_effect=self.fixture):
            result=cycle.execute(self.config,self.planned,self.root/'success')
        self.assertEqual(result['status'],'private_preview_ready')
        self.assertFalse(result['market_data_published']);self.assertTrue((self.root/'success/build/preview.html').exists())
        bundle=json.loads((self.root/'success/market.private.json').read_text())
        self.assertEqual(bundle['audience'],'private-review');self.assertFalse(bundle['auto_updated'])
        self.assertEqual(len(bundle['products']),2)
        self.assertTrue(all(o['shares'] is None for p in bundle['products'] for o in p['observations'].values()))
        manifest=json.loads((self.root/'success/build/public/market.manifest.json').read_text())
        self.assertEqual(manifest['state'],'unpublished')
        self.assertNotIn('unit_nav_cny',json.dumps(result));self.assertNotIn('1.0000',json.dumps(result))

    def test_previous_evidence_not_overwritten(self):
        old=self.root/'old';old.mkdir();(old/'sentinel').write_text('retain')
        with patch.object(cycle.collect_nav,'acquire') as acquire:
            with self.assertRaises(FileExistsError):cycle.execute(self.config,self.planned,old)
            acquire.assert_not_called()
        self.assertEqual((old/'sentinel').read_text(),'retain')

    def test_runtime_identity_not_hardcoded_to_work_container(self):
        with patch.dict('os.environ',{'GITHUB_ACTIONS':'true','GITHUB_RUN_ID':'123'}),patch.object(cycle.collect_nav,'acquire',side_effect=self.fixture) as fn:
            result=cycle.execute(self.config,self.planned,self.root/'runner')
        self.assertEqual(result['runtime'],'github_hosted_acceptance');self.assertEqual(result['run_id'],'123')
        self.assertEqual(fn.call_args.kwargs['runtime_id'],'github_hosted_acceptance')

    def test_finite_request_budget(self):
        self.assertEqual(self.planned['max_requests'],2)
        with self.assertRaises(ValueError):cycle.make_plan(self.config,self.calendar,[p['code'] for p in self.config['products']],'2026-10-22','2026-10-23')

if __name__=='__main__':unittest.main()
