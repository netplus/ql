"""Synthetic recovery regressions; no real market requests or public exports."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

import test_history_cycle as fixtures
from tools import run_history_cycle as pipe
from tools import run_nav_cycle as nav
from tools.history_store import encode

ROOT = Path(__file__).resolve().parents[1]
T2 = fixtures.T2
checkpoint = fixtures.checkpoint


class DurableHistoryCycleTests(unittest.TestCase):
    setUp = fixtures.HistoryCycleTests.setUp
    run_cycle = fixtures.HistoryCycleTests.run_cycle
    pointer = fixtures.HistoryCycleTests.pointer

    def test_same_capture_with_wider_history_keeps_distinct_receipts(self):
        self.run_cycle(); self.time = T2
        calendar = copy.deepcopy(self.plan['calendar'])
        calendar['sessions'].insert(0, '2026-10-21')
        calendar['coverage_start'] = '2026-10-21'
        self.request = pipe.intent(self.config, self.plan, calendar)
        result = self.run_cycle()
        self.assertEqual(result['status'], 'private_snapshot_ready', result)
        self.assertEqual(result['inserted_facts'], 0)
        self.assertEqual(self.store.audit()['batches'], 1)
        self.assertEqual(result['coverage']['sessions'], 3)

    def test_same_capture_with_new_probe_keeps_distinct_receipts(self):
        self.run_cycle(); self.time = T2
        def extra_metadata(*args):
            result = checkpoint(*args)
            path = args[2] / 'attempt-01/raw/probe.json'
            probe = json.loads(path.read_bytes())
            probe['runtime_note'] = 'synthetic alternate checkpoint'
            path.write_bytes(encode(probe))
            return result
        result = self.run_cycle(collector=extra_metadata)
        self.assertEqual(result['status'], 'unchanged', result)
        self.assertEqual(result['inserted_facts'], 0)
        self.assertEqual(self.store.audit()['batches'], 1)

    def test_interrupted_snapshot_write_can_resume(self):
        original = pipe.private_file
        def interrupt(path, raw):
            if 'snapshot.private.json' in path.name:
                original(path, raw[:17])
                raise OSError('synthetic short write')
            return original(path, raw)
        with patch.object(pipe, 'private_file', side_effect=interrupt):
            first = self.run_cycle()
        self.assertEqual(first['status'], 'blocked')
        self.assertEqual(self.store.audit()['batches'], 1)
        self.time = T2
        second = pipe.pipeline(self.store, request=None, review=self.review,
                               resume=first['run_id'])
        self.assertEqual(second['status'], 'private_snapshot_ready', second)
        self.assertEqual(second['inserted_facts'], 0)

    def test_http_error_metadata_rejected_even_with_observed_flag(self):
        def wrong_status(*args):
            result = checkpoint(*args)
            path = args[2] / 'attempt-01/raw/probe.json'
            probe = json.loads(path.read_bytes())
            probe['results'][0]['http_status'] = 503
            path.write_bytes(encode(probe))
            return result
        result = self.run_cycle(collector=wrong_status)
        self.assertEqual(result['status'], 'blocked', result)
        self.assertEqual(self.store.audit()['batches'], 0)

    def test_failure_after_pointer_replace_is_idempotently_recoverable(self):
        self.run_cycle(); before = self.pointer(); self.time = T2
        def revised(*args):
            return checkpoint(*args, last='1.0400', captured='2026-10-24T03:40:00Z')
        real_sync, failed = pipe.sync_dir, []
        def fail_after_replace(directory):
            if directory == self.store.directory and not failed:
                failed.append(True)
                raise OSError('synthetic directory sync failure after rename')
            real_sync(directory)
        with patch.object(pipe, 'sync_dir', side_effect=fail_after_replace):
            first = self.run_cycle(collector=revised)
        self.assertEqual(first['status'], 'blocked', first)
        self.assertNotEqual(before, self.pointer())
        self.assertEqual(first['current_pointer_state'], 'not_assumed_unchanged_on_error')
        second = pipe.pipeline(self.store, request=None, review=self.review,
                               resume=first['run_id'])
        self.assertEqual(second['status'], 'unchanged', second)
        self.assertEqual(self.store.audit()['batches'], 2)

    def test_full_retry_collector_handoff_uses_actual_components(self):
        waits, calls = [], []
        def acquire(requests, start, end, output, *, runtime_id):
            calls.append(runtime_id)
            if len(calls) == 1:
                output.mkdir(parents=True)
                probe = {'results': [{**r, 'status': 'error', 'error_class': 'TimeoutError',
                                      'reason': 'synthetic timeout'} for r in requests]}
                (output / 'probe.json').write_bytes(encode(probe))
                return probe
            # Synthetic transport only; use the real retry wrapper, execute(),
            # parser, assembler, database and Page builder on this response.
            temp = output.parent / 'synthetic-input'
            checkpoint(self.config, self.plan, temp, None)
            source = temp / 'attempt-01/raw'
            source.rename(output)
            return json.loads((output / 'probe.json').read_bytes())
        def retry(config, planned, output, execute_one):
            return pipe.execute_reliable(config, planned, output, execute_one, sleep=waits.append)
        with patch.object(nav.collect_nav, 'acquire', side_effect=acquire):
            result = self.run_cycle(collector=retry)
        self.assertEqual(result['status'], 'private_snapshot_ready', result)
        self.assertEqual(len(calls), 2)
        self.assertEqual(waits, [2])
        self.assertEqual(self.store.audit()['raw_responses'], 2)
        cycle_path = self.store.directory / 'runs' / result['run_id'] / 'acquisition/cycle.json'
        self.assertEqual(json.loads(cycle_path.read_bytes())['selected_attempt'], 'attempt-02')

    def test_run_id_collision_does_not_reuse_existing_directory(self):
        first = self.run_cycle(); before = self.pointer()
        with patch.object(pipe.secrets, 'token_hex', side_effect=lambda n: first['run_id'] if n == 12 else 'f'*(n*2)):
            second = self.run_cycle()
        self.assertEqual(second['status'], 'blocked', second)
        self.assertEqual(second['failure_code'], 'run_id_collision')
        self.assertEqual(before, self.pointer())
        original_result = json.loads((self.store.directory/'runs'/first['run_id']/'result.json').read_bytes())
        self.assertEqual(original_result['status'], first['status'])

    def test_resume_missing_run_reports_preflight_not_ready_checkpoint(self):
        result = pipe.pipeline(self.store, request=None, review=self.review, resume='a'*24)
        self.assertEqual(result['status'], 'blocked')
        self.assertEqual(result['recovery'], 'fix_preflight')

    def test_process_exit_during_snapshot_write_then_cli_resume(self):
        script = r"""
import json, os, sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests'))
from test_history_cycle import T1, checkpoint
from tools import run_history_cycle as pipe
from tools.history_store import Store
payload = json.loads(Path(sys.argv[1]).read_bytes())
original = pipe.private_file
def terminate(path, raw):
    if 'snapshot.private.json' in path.name:
        original(path, raw[:17])
        os._exit(23)
    return original(path, raw)
pipe.private_file = terminate
pipe.pipeline(Store(Path(payload['store']), clock=lambda: T1),
    request=payload['request'], review=payload['review'], collector=checkpoint)
raise SystemExit(99)
"""
        payload = self.root / 'process-exit-input.json'
        payload.write_bytes(encode({'store': str(self.store.directory),
                                    'request': self.request, 'review': self.review}))
        crashed = subprocess.run([sys.executable, '-c', script, str(payload)],
                                 cwd=ROOT, capture_output=True, text=True, timeout=30)
        self.assertEqual(crashed.returncode, 23, crashed.stderr)
        self.assertEqual(self.store.audit()['batches'], 1)
        self.assertFalse((self.store.directory / 'current.private.json').exists())
        runs = list((self.store.directory / 'runs').iterdir())
        self.assertEqual(len(runs), 1)
        review = self.root / 'synthetic-review.json'
        review.write_bytes(encode(self.review))
        resumed = subprocess.run([sys.executable, str(ROOT/'tools/run_history_cycle.py'),
            '--history-root', str(self.store.directory), '--resume', runs[0].name,
            '--source-review', str(review), '--execute'], cwd=ROOT,
            capture_output=True, text=True, timeout=30)
        self.assertEqual(resumed.returncode, 0, resumed.stdout + resumed.stderr)
        report = json.loads(resumed.stdout)
        self.assertEqual(report['status'], 'private_snapshot_ready')
        self.assertEqual(report['inserted_facts'], 0)
        self.assertEqual(self.store.audit()['batches'], 1)
        self.assertIsNotNone(pipe.current(self.store))

if __name__ == '__main__':
    unittest.main()
