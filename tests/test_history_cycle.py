"""Synthetic checkpoint tests. No issuer requests, licensed feeds or user notes."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from tools import run_history_cycle as pipe
from tools import run_nav_cycle as nav
from tools.history_store import Store, encode, instant, sha

ROOT = Path(__file__).resolve().parents[1]
T1 = datetime(2026, 10, 24, 3, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 24, 4, tzinfo=timezone.utc)
CAPTURE = '2026-10-24T01:00:00Z'


def synthetic_review(planned):
    return {'schema': 'ql.source-use-review/1', 'sources': {
        r['url']: {'status': 'approved', 'collection_allowed': True,
                   'local_raw_retention_allowed': True,
                   'review_reference': 'SYNTHETIC TEST ONLY; not an issuer license',
                   'reviewed_at': '2026-10-24T00:00:00Z', 'expires_at': '2026-12-31T00:00:00Z'}
        for r in planned['requests']}}


def checkpoint(config, planned, output, execute_one, *, last='1.0100', captured=CAPTURE):
    raw_dir = output / 'attempt-01/raw'
    raw_dir.mkdir(parents=True)
    results = []
    for request in planned['requests']:
        code = request['code']
        days = planned['calendar']['sessions']
        html = f'<h1>SYNTHETIC ONLY {code}</h1><table><tr><th>日期</th><th>单位净值(元)</th></tr>'
        for i, day in enumerate(days):
            html += f'<tr><td>{day}</td><td>{last if i == len(days)-1 else "1.0000"}</td></tr>'
        html += '</table>'
        raw = html.encode()
        (raw_dir / (code+'.html')).write_bytes(raw)
        rows = nav.collect_nav.parse_nav(html, code, planned['start'], planned['end'])
        (raw_dir / (code+'.rows.json')).write_bytes(encode(rows))
        results.append({**request, 'status': 'observed', 'mode': 'http_response',
            'row_count': len(rows), 'latest_observed_date': planned['end'],
            'raw_response_archived': True, 'raw_file': code+'.html',
            'encoding': 'utf-8', 'http_status': 200, 'raw_sha256': sha(raw),
            'finished_at': captured})
    (raw_dir / 'probe.json').write_bytes(encode({'results': results, 'synthetic': True}))
    result = {'status': 'private_preview_ready', 'selected_attempt': 'attempt-01'}
    (output / 'cycle.json').write_bytes(encode(result))
    return result


class HistoryCycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ql-checkpoint-test-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.time = T1
        self.store = Store.create(self.root/'state', clock=lambda: self.time)
        self.config = json.loads((ROOT/'config/market-universe.json').read_text())
        calendar = json.loads((ROOT/'config/calendar-2026-oct.json').read_text())
        self.plan = nav.make_plan(self.config, calendar, ['159995','510330'], '2026-10-22', '2026-10-23')
        self.request = pipe.intent(self.config, self.plan, self.plan['calendar'])
        self.review = synthetic_review(self.plan)

    def run_cycle(self, **kwargs):
        return pipe.pipeline(self.store, request=self.request, review=self.review,
                             collector=kwargs.pop('collector', checkpoint), **kwargs)

    def pointer(self):
        return (self.store.directory/'current.private.json').read_bytes()

    def test_complete_chain_raw_to_database_to_private_page(self):
        r = self.run_cycle()
        self.assertEqual(r['status'], 'private_snapshot_ready', r)
        self.assertEqual(self.store.audit()['facts'], 4)
        self.assertEqual(self.store.audit()['raw_responses'], 2)
        m = pipe.current(self.store)
        self.assertEqual(m['asof'], '2026-10-23')
        self.assertTrue((self.store.directory/m['preview']).is_file())
        self.assertFalse(r['market_data_published'])
        self.assertEqual(r['coverage']['latest_field_counts']['shares'], 0)

    def test_pending_review_stops_before_collector(self):
        self.review = {'schema':'ql.source-use-review/1', 'sources':{}}
        def forbidden(*args):
            raise AssertionError('collector must not execute')
        r = self.run_cycle(collector=forbidden)
        self.assertEqual(r['failure_code'], 'source_use_review_pending')
        self.assertFalse((self.store.directory/'runs').exists())
        self.assertEqual(self.store.audit()['facts'], 0)

    def test_expired_review_rejected(self):
        for d in self.review['sources'].values(): d['expires_at'] = '2026-10-23T00:00:00Z'
        self.assertEqual(self.run_cycle()['failure_code'], 'source_use_review_expired')

    def test_future_review_rejected(self):
        for d in self.review['sources'].values(): d['reviewed_at'] = '2026-11-01T00:00:00Z'
        self.assertEqual(self.run_cycle()['failure_code'], 'future_source_use_review')

    def test_same_checkpoint_replayed_without_new_batch_or_network(self):
        a = self.run_cycle(); before = self.pointer(); self.time = T2
        def forbidden(*args): raise AssertionError('resume must not collect')
        b = pipe.pipeline(self.store, request=None, review=self.review, resume=a['run_id'], collector=forbidden)
        self.assertEqual(b['status'], 'unchanged', b)
        self.assertEqual(b['inserted_facts'], 0)
        self.assertEqual(a['known_at'], b['known_at'])
        self.assertEqual(before, self.pointer())
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_rebuilt_timestamp_cannot_make_a_duplicate(self):
        a = self.run_cycle(); self.time = T2
        with patch.object(nav, 'stamp', return_value='2026-10-24T02:59:59Z'):
            b = pipe.pipeline(self.store, request=None, review=self.review, resume=a['run_id'])
        self.assertEqual(a['batch_id'], b['batch_id'])
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_raw_tampering_rejected_and_current_preserved(self):
        a = self.run_cycle(); before = self.pointer()
        raw = self.store.directory/'runs'/a['run_id']/'acquisition/attempt-01/raw/159995.html'
        raw.write_bytes(raw.read_bytes()+b'changed')
        b = pipe.pipeline(self.store, request=None, review=self.review, resume=a['run_id'])
        self.assertEqual(b['failure_code'], 'raw_hash_mismatch')
        self.assertEqual(before, self.pointer())
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_parser_output_tampering_rejected(self):
        def altered(*args):
            r = checkpoint(*args)
            (args[2]/'attempt-01/raw/159995.rows.json').write_text('[]')
            return r
        r = self.run_cycle(collector=altered)
        self.assertEqual(r['failure_code'], 'parsed_rows_mismatch')
        self.assertEqual(self.store.audit()['facts'], 0)

    def test_partial_acquisition_does_not_insert(self):
        def partial(*args):
            r = checkpoint(*args)
            f = args[2]/'attempt-01/raw/probe.json'; p=json.loads(f.read_bytes())
            p['results'][0]['status']='stale'; f.write_bytes(encode(p)); return r
        self.assertEqual(self.run_cycle(collector=partial)['failure_code'], 'source_not_current')
        self.assertEqual(self.store.audit()['batches'], 0)
        self.assertFalse((self.store.directory/'current.private.json').exists())

    def test_failed_acquisition_keeps_last_good_snapshot(self):
        self.run_cycle(); before=self.pointer()
        def failed(config, planned, output, execute_one):
            output.mkdir(); r={'status':'blocked','selected_attempt':None}
            (output/'cycle.json').write_bytes(encode(r)); return r
        r=self.run_cycle(collector=failed)
        self.assertEqual(r['failure_code'], 'acquisition_not_ready')
        self.assertEqual(before,self.pointer())
        self.assertEqual(json.loads((self.store.directory/'last-run.json').read_bytes())['status'], 'blocked')

    def test_database_commit_then_build_failure_can_resume(self):
        def fail_build(*args): raise OSError('synthetic SECRET should not be printed')
        a=self.run_cycle(builder=fail_build)
        self.assertEqual(a['status'],'blocked');self.assertNotIn('SECRET',json.dumps(a))
        self.assertEqual(self.store.audit()['batches'],1)
        self.assertFalse((self.store.directory/'current.private.json').exists())
        self.time=T2
        b=pipe.pipeline(self.store,request=None,review=self.review,resume=a['run_id'])
        self.assertEqual(b['status'],'private_snapshot_ready',b)
        self.assertEqual(b['inserted_facts'],0)
        self.assertEqual(self.store.audit()['batches'],1)

    def test_new_revision_failure_preserves_current_then_recovers(self):
        self.run_cycle();before=self.pointer();self.time=T2
        def revised(*args): return checkpoint(*args,last='1.0200',captured='2026-10-24T03:30:00Z')
        def failed(*args): raise OSError('synthetic output unavailable')
        a=self.run_cycle(collector=revised,builder=failed)
        self.assertEqual(a['status'],'blocked');self.assertEqual(before,self.pointer())
        self.assertEqual(self.store.audit()['batches'],2)
        b=pipe.pipeline(self.store,request=None,review=self.review,resume=a['run_id'])
        self.assertEqual(b['inserted_facts'],0);self.assertNotEqual(before,self.pointer())
        self.assertEqual(self.store.audit()['numeric_revisions'],2)

    def test_promote_failure_before_replace_preserves_current(self):
        self.run_cycle(); before=self.pointer(); self.time=T2
        def revised(*args): return checkpoint(*args,last='1.0300',captured='2026-10-24T03:40:00Z')
        original = pipe.replace_json
        def reject_current(path,obj):
            if path.name=='current.private.json': raise OSError('synthetic rename failure')
            return original(path,obj)
        with patch.object(pipe,'replace_json',side_effect=reject_current): a=self.run_cycle(collector=revised)
        self.assertEqual(a['status'],'blocked');self.assertEqual(before,self.pointer())
        b=pipe.pipeline(self.store,request=None,review=self.review,resume=a['run_id'])
        self.assertEqual(b['status'],'private_snapshot_ready',b)

    def test_corrupt_current_blocks_implicit_overwrite(self):
        self.run_cycle(); (self.store.directory/'current.private.json').write_text('{}')
        r=self.run_cycle();self.assertEqual(r['failure_code'],'invalid_current_manifest')
        self.assertEqual((self.store.directory/'current.private.json').read_text(),'{}')

    def test_raw_symlink_rejected(self):
        def linked(*args):
            r=checkpoint(*args);p=args[2]/'attempt-01/raw/159995.html'
            saved=p.with_suffix('.copy');p.rename(saved);p.symlink_to(saved);return r
        r=self.run_cycle(collector=linked)
        self.assertEqual(r['status'],'blocked');self.assertEqual(self.store.audit()['facts'],0)

    def test_attempt_traversal_rejected(self):
        def traversed(*args):
            r=checkpoint(*args);r['selected_attempt']='../../outside'
            (args[2]/'cycle.json').write_bytes(encode(r));return r
        self.assertEqual(self.run_cycle(collector=traversed)['failure_code'],'acquisition_not_ready')

    def test_resume_path_traversal_rejected(self):
        r=pipe.pipeline(self.store,request=None,review=self.review,resume='../bad')
        self.assertEqual(r['failure_code'],'invalid_run_id')

    def test_intent_hash_rechecked(self):
        a=self.run_cycle(); f=self.store.directory/'runs'/a['run_id']/'intent.json'
        b=json.loads(f.read_bytes());b['body']['plan']['end']='2026-10-22';f.write_bytes(encode(b))
        r=pipe.pipeline(self.store,request=None,review=self.review,resume=a['run_id'])
        self.assertEqual(r['failure_code'],'intent_hash_mismatch')

    def test_concurrent_process_refused(self):
        with pipe.writer(self.store): r=self.run_cycle()
        self.assertEqual(r['failure_code'],'pipeline_busy')
        self.assertFalse((self.store.directory/'runs').exists())

    def test_permissions_private(self):
        self.run_cycle()
        for p in self.store.directory.rglob('*'):
            self.assertEqual(p.stat().st_mode & 0o077,0,str(p))

    def test_history_window_keeps_gaps_not_forward_fills(self):
        calendar=copy.deepcopy(self.plan['calendar']);calendar['sessions'].insert(0,'2026-10-21');calendar['coverage_start']='2026-10-21'
        self.request=pipe.intent(self.config,self.plan,calendar)
        r=self.run_cycle();self.assertEqual(r['status'],'private_snapshot_ready',r)
        m=pipe.current(self.store);b=json.loads((self.store.directory/m['file']).read_bytes())
        self.assertIsNone(b['products'][0]['observations']['2026-10-21']['nav'])
        self.assertEqual(r['coverage']['field_counts']['nav'],4)
        self.assertEqual(r['coverage']['expected_rows'],6)

    def test_old_checkpoint_cannot_roll_back_current_day(self):
        self.run_cycle();before=self.pointer();self.time=T2
        calendar=json.loads((ROOT/'config/calendar-2026-oct.json').read_bytes())
        planned=nav.make_plan(self.config,calendar,['159995','510330'],'2026-10-20','2026-10-21')
        self.request=pipe.intent(self.config,planned,planned['calendar'])
        r=self.run_cycle()
        self.assertEqual(r['status'],'stored_not_promoted',r);self.assertEqual(before,self.pointer())
        self.assertEqual(self.store.audit()['facts'],8)

    def test_dry_run_no_store_or_network(self):
        p=subprocess.run([sys.executable,str(ROOT/'tools/run_history_cycle.py'),'--history-root',str(self.root/'unused'),'--start','2026-10-22','--end','2026-10-23'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr);self.assertEqual(json.loads(p.stdout)['mode'],'dry_run')
        self.assertFalse((self.root/'unused').exists())

    def test_resume_in_separate_process(self):
        a=self.run_cycle();before=self.pointer();review=self.root/'synthetic-review.json';review.write_bytes(encode(self.review))
        p=subprocess.run([sys.executable,str(ROOT/'tools/run_history_cycle.py'),'--history-root',str(self.store.directory),'--resume',a['run_id'],'--source-review',str(review),'--execute'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)
        self.assertEqual(json.loads(p.stdout)['inserted_facts'],0);self.assertEqual(before,self.pointer())

    def test_database_backup_restores_same_snapshot(self):
        a=self.run_cycle();m=pipe.current(self.store);original=(self.store.directory/m['file']).read_bytes()
        self.store.backup(self.root/'backup'); restored=Store.restore(self.root/'backup',self.root/'restored')
        b,r=restored.snapshot(self.plan['calendar'],['159995','510330'],'510330',cutoff=m['knowledge_cutoff'])
        self.assertEqual(original,encode(b));self.assertEqual(restored.audit()['raw_responses'],2)

if __name__=='__main__': unittest.main()
