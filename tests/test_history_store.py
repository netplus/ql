"""Synthetic history fixtures only. No observed market prices or private notes."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from tools.history_store import Store, HistoryError, encode, instant, sha, ROOT

T1 = datetime(2026, 10, 16, 10, tzinfo=timezone.utc)
T2 = datetime(2026, 10, 17, 10, tzinfo=timezone.utc)
T3 = datetime(2026, 10, 18, 10, tzinfo=timezone.utc)
DAYS = ['2026-10-08', '2026-10-09', '2026-10-12', '2026-10-13', '2026-10-14', '2026-10-15']


def fixture(*, version='synthetic/1', captured='2026-10-16T01:00:00Z', nav='1.0050'):
    source = {'provider': 'SYNTHETIC TEST ONLY', 'url': 'https://www.chinaamc.com/fund/510330/index.shtml',
              'recorded_at': captured, 'published_at': None, 'mode': 'web_text_transcription',
              'raw_response_archived': False, 'evidence_sha256': None}
    product = {'code': '510330', 'exchange': 'SSE', 'name': 'SYNTHETIC NOT A QUOTE', 'label': 'SYNTHETIC',
               'group': '宽基', 'basis': 'unadjusted_nav', 'currency': 'CNY',
               'observations': {d: {'nav': f'1.{i:04}', 'shares': None,
                                    'nav_source': 'synthetic-nav', 'shares_source': None}
                                for i, d in enumerate(DAYS)}}
    product['observations'][DAYS[-1]]['nav'] = nav
    return {'schema': 'ql.market-bundle/2', 'version': version, 'timezone': 'Asia/Shanghai',
            'audience': 'private-review', 'auto_updated': False, 'observed_at': captured,
            'asof': DAYS[-1], 'benchmark_code': '510330', 'sources': {'synthetic-nav': source},
            'calendar': {'version': 'synthetic-calendar', 'source_url': 'https://www.sse.com.cn/disclosure/dealinstruc/closed/',
                         'coverage_start': DAYS[0], 'coverage_end': DAYS[-1], 'sessions': DAYS},
            'products': [product]}


class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='ql-history-test-')
        self.base = Path(self.tmp.name)
        self.time = T1
        self.store = Store.create(self.base/'state', clock=lambda: self.time)
        self.b = fixture()

    def tearDown(self):
        self.tmp.cleanup()

    def ingest(self, b=None, **kw):
        return self.store.ingest(encode(b or self.b), **kw)

    def snap(self, **kw):
        return self.store.snapshot(self.b['calendar'], ['510330'], '510330', **kw)

    def test_disk_reopen(self):
        self.ingest()
        fresh = Store(self.base/'state', clock=lambda: T2)
        b, r = fresh.snapshot(self.b['calendar'], ['510330'], '510330')
        self.assertEqual(r['field_counts']['nav'], 6)
        self.assertEqual(b['products'][0]['observations'][DAYS[-1]]['nav'], '1.0050')

    def test_idempotence(self):
        a = self.ingest()
        self.time = T2
        b = self.ingest()
        self.assertEqual(a['batch_id'], b['batch_id'])
        self.assertEqual(b['status'], 'unchanged')
        self.assertEqual(b['known_at'], instant(T1))
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_revision_preserved_and_cutoff(self):
        self.ingest()
        self.time = T2
        self.ingest(fixture(version='synthetic/2', captured='2026-10-17T01:00:00Z', nav='1.0060'))
        old, _ = self.snap(cutoff=instant(T1))
        new, _ = self.snap(cutoff=instant(T2))
        self.assertEqual(old['products'][0]['observations'][DAYS[-1]]['nav'], '1.0050')
        self.assertEqual(new['products'][0]['observations'][DAYS[-1]]['nav'], '1.0060')
        self.assertNotEqual(old['version'], new['version'])
        self.assertEqual(self.store.audit()['numeric_revisions'], 1)

    def test_late_backfill_does_not_replace_new_capture(self):
        self.ingest(fixture(captured='2026-10-16T03:00:00Z', nav='1.0060'))
        self.time = T2
        self.ingest(fixture(version='late-old', captured='2026-10-16T01:00:00Z', nav='1.0040'))
        b, _ = self.snap()
        self.assertEqual(b['products'][0]['observations'][DAYS[-1]]['nav'], '1.0060')

    def test_does_not_backdate_first_seen(self):
        self.ingest()
        with self.assertRaisesRegex(HistoryError, 'no_data_known'):
            self.snap(cutoff='2026-10-16T02:00:00Z')

    def test_same_capture_conflict_rolls_back(self):
        self.ingest()
        self.time = T2
        with self.assertRaisesRegex(HistoryError, 'same_capture_conflicting'):
            self.ingest(fixture(version='bad', nav='9.9999'))
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_cross_authority_conflict_not_arbitrarily_resolved(self):
        self.ingest()
        other = fixture(version='other', captured='2026-10-17T01:00:00Z', nav='9.9999')
        other['sources']['synthetic-nav']['url'] = 'https://www.sse.com.cn/market/'
        self.time = T2
        self.ingest(other)
        with self.assertRaisesRegex(HistoryError, 'cross_source_conflict'):
            self.snap()

    def test_failure_mid_transaction_rolls_back(self):
        b = fixture()
        b['products'][0]['observations'][DAYS[0]].update(shares='10', shares_source='synthetic-nav')
        db = self.store.connect(write=True)
        db.execute("CREATE TRIGGER test_abort BEFORE INSERT ON facts WHEN NEW.field='shares' "
                   "BEGIN SELECT RAISE(ABORT,'synthetic fault'); END")
        db.close()
        with self.assertRaises(sqlite3.IntegrityError):
            self.ingest(b)
        self.assertEqual(self.store.audit()['batches'], 0)
        self.assertEqual(self.store.audit()['facts'], 0)

    def test_missing_is_not_zero_or_forward_filled(self):
        self.b['products'][0]['observations'][DAYS[2]]['nav'] = None
        self.b['products'][0]['observations'][DAYS[3]]['shares'] = '0'
        self.b['products'][0]['observations'][DAYS[3]]['shares_source'] = 'synthetic-nav'
        self.ingest()
        b, report = self.snap()
        o = b['products'][0]['observations']
        self.assertIsNone(o[DAYS[2]]['nav'])
        self.assertEqual(o[DAYS[3]]['shares'], '0')
        self.assertIsNone(o[DAYS[4]]['shares'])
        self.assertEqual(report['field_counts'], {'nav': 5, 'shares': 1})

    def test_later_missing_fetch_does_not_retract_known_same_day(self):
        self.ingest()
        self.time = T2
        b = fixture(version='later-gap', captured='2026-10-17T01:00:00Z')
        b['products'][0]['observations'][DAYS[-1]]['nav'] = None
        self.ingest(b)
        current, _ = self.snap()
        self.assertEqual(current['products'][0]['observations'][DAYS[-1]]['nav'], '1.0050')

    def test_calendar_gap_survives_append(self):
        self.ingest()
        calendar = copy.deepcopy(self.b['calendar'])
        calendar['sessions'] = DAYS + ['2026-10-16']
        calendar['coverage_end'] = '2026-10-16'
        b, report = self.store.snapshot(calendar, ['510330'], '510330')
        self.assertIsNone(b['products'][0]['observations']['2026-10-16']['nav'])
        self.assertEqual(report['latest_field_counts']['nav'], 0)

    def test_snapshot_is_private_even_for_public_input(self):
        self.b['audience'] = 'public-market'
        self.ingest()
        b, r = self.snap()
        self.assertEqual(b['audience'], 'private-review')
        self.assertFalse(b['auto_updated'])
        self.assertFalse(r['market_data_published'])

    def test_raw_claim_requires_bytes(self):
        self.b['sources']['synthetic-nav'].update(mode='http_response', raw_response_archived=True,
                                                 evidence_sha256=sha(b'SYNTHETIC HTTP'))
        with self.assertRaisesRegex(HistoryError, 'claimed_raw_evidence_missing'):
            self.ingest()
        self.assertEqual(self.store.audit()['batches'], 0)

    def test_raw_hash_mismatch_rejected(self):
        self.b['sources']['synthetic-nav'].update(mode='http_response', raw_response_archived=True,
                                                 evidence_sha256=sha(b'SYNTHETIC HTTP'))
        with self.assertRaisesRegex(HistoryError, 'hash_mismatch'):
            self.ingest(responses={'synthetic-nav': b'wrong'})

    def test_raw_evidence_round_trip(self):
        raw = b'SYNTHETIC HTTP BODY, NOT SOURCE EVIDENCE'
        self.b['sources']['synthetic-nav'].update(mode='http_response', raw_response_archived=True, evidence_sha256=sha(raw))
        self.ingest(responses={'synthetic-nav': raw})
        self.assertEqual(self.store.audit()['raw_responses'], 1)
        self.store.backup(self.base/'backup')
        restored = Store.restore(self.base/'backup', self.base/'restored')
        self.assertEqual(restored.audit()['raw_responses'], 1)

    def test_backup_restore_exact_snapshot(self):
        self.ingest()
        before, _ = self.snap(cutoff=instant(T1))
        self.store.backup(self.base/'backup')
        restored = Store.restore(self.base/'backup', self.base/'restored')
        after, _ = restored.snapshot(self.b['calendar'], ['510330'], '510330', cutoff=instant(T1))
        self.assertEqual(encode(before), encode(after))

    def test_backup_tamper_rejected(self):
        self.ingest()
        self.store.backup(self.base/'backup')
        p = self.base/'backup/history.sqlite3'
        with p.open('ab') as f:
            f.write(b'TAMPER')
        with self.assertRaisesRegex(HistoryError, 'backup_hash_mismatch'):
            Store.restore(self.base/'backup', self.base/'restored')
        self.assertFalse((self.base/'restored').exists())

    def test_backup_no_overwrite(self):
        self.ingest()
        self.store.backup(self.base/'backup')
        with self.assertRaises(FileExistsError):
            self.store.backup(self.base/'backup')

    def test_no_source_tree_storage(self):
        with self.assertRaisesRegex(HistoryError, 'outside_source_tree'):
            Store.create(ROOT/'private-history-not-allowed')

    def test_symlink_rejected(self):
        (self.base/'linked').symlink_to(self.base/'state', target_is_directory=True)
        with self.assertRaisesRegex(HistoryError, 'symlink'):
            Store(self.base/'linked')

    def test_private_permissions(self):
        if os.name != 'posix':
            self.skipTest('POSIX mode test')
        self.assertEqual(self.store.path.stat().st_mode & 0o777, 0o600)
        self.store.directory.chmod(0o755)
        with self.assertRaisesRegex(HistoryError, 'permissions'):
            Store(self.store.directory)

    def test_future_bundle_rejected(self):
        with self.assertRaisesRegex(HistoryError, 'future_observation'):
            self.ingest(fixture(captured='2026-10-20T01:00:00Z'))

    def test_time_reversal_rejected(self):
        self.ingest()
        with self.assertRaisesRegex(HistoryError, 'nonmonotonic'):
            self.ingest(fixture(version='same-clock'))

    def test_future_cutoff_rejected(self):
        self.ingest()
        with self.assertRaisesRegex(HistoryError, 'future_knowledge'):
            self.snap(cutoff=instant(T3))

    def test_product_identity_change_rejected(self):
        self.ingest()
        self.time = T2
        b = fixture(version='identity')
        b['products'][0]['exchange'] = 'SZSE'
        with self.assertRaisesRegex(HistoryError, 'identity_changed'):
            self.ingest(b)

    def test_append_only_sql_guards(self):
        self.ingest()
        with self.store.connect(write=True) as db:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE facts SET value='2'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM batches')

    def test_same_value_precision_not_revision(self):
        self.ingest()
        self.time = T2
        self.ingest(fixture(version='precision', captured='2026-10-17T01:00:00Z', nav='1.005000'))
        self.assertEqual(self.store.audit()['numeric_revisions'], 0)

    def test_cli_dry_run_has_no_writes(self):
        target = self.base/'never-created'
        r = subprocess.run([sys.executable, str(ROOT/'tools/history.py'), 'init', '--store', str(target)],
                           text=True, capture_output=True)
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertFalse(target.exists())
        self.assertEqual(json.loads(r.stdout)['mode'], 'dry_run')

    def test_snapshot_passes_page_and_missing_window(self):
        self.b['products'][0]['observations'][DAYS[2]]['nav'] = None
        self.ingest()
        b, _ = self.snap()
        script = "const M=require('./web/market-data.js');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{const m=M.model(M.parse(s));console.log(JSON.stringify(m.products[0].windows[m.asof]['5']));});"
        r = subprocess.run(['node', '-e', script], input=encode(b), capture_output=True, cwd=ROOT)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNone(json.loads(r.stdout)['value'])

    def test_unknown_fields_not_archived(self):
        self.b['private_note'] = 'THIS MUST NOT ENTER THE HISTORY'
        self.ingest()
        with self.store.connect() as db:
            payload = db.execute('SELECT payload FROM batches').fetchone()[0]
        self.assertNotIn(b'THIS MUST', payload)


if __name__ == '__main__':
    unittest.main()
