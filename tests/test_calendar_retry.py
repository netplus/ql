"""Synthetic tests only; network acceptance is a separate workflow step."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from datetime import datetime
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from tools.market_calendar import sessions, window, latest_completed
from tools.retry_nav_cycle import retryable, execute_reliable


class CalendarTests(unittest.TestCase):
    def setUp(self):self.spec=json.loads((ROOT/'config/market-calendar-2026.json').read_text())
    def test_october_window(self):self.assertEqual(len(window(self.spec,'2026-10-08','2026-10-23')['sessions']),12)
    def test_makeup_weekend_closed(self):self.assertNotIn('2026-10-10',sessions(self.spec))
    def test_spring_closure(self):self.assertNotIn('2026-02-23',sessions(self.spec));self.assertIn('2026-02-24',sessions(self.spec))
    def test_national_day(self):self.assertNotIn('2026-10-07',sessions(self.spec))
    def test_before_close(self):self.assertEqual(latest_completed(self.spec,datetime.fromisoformat('2026-10-26T06:59:00+00:00')),'2026-10-23')
    def test_at_close(self):self.assertEqual(latest_completed(self.spec,datetime.fromisoformat('2026-10-26T07:00:00+00:00')),'2026-10-26')
    def test_weekend_cutoff(self):self.assertEqual(latest_completed(self.spec,datetime.fromisoformat('2026-10-24T23:00:00+00:00')),'2026-10-23')
    def test_unknown_year_rejected(self):
        with self.assertRaises(ValueError):latest_completed(self.spec,datetime.fromisoformat('2027-01-05T00:00:00+00:00'))
    def test_naive_time_rejected(self):
        with self.assertRaises(ValueError):latest_completed(self.spec,datetime(2026,10,24))
    def test_holiday_not_valid_endpoint(self):
        with self.assertRaises(ValueError):window(self.spec,'2026-10-01','2026-10-23')


class RetryTests(unittest.TestCase):
    def probe(self,kind='URLError',message='connection reset',status=None):
        return {'results':[{'status':'error','error_class':kind,'reason':message,'http_status':status}]}
    def test_transient(self):self.assertTrue(retryable(self.probe()))
    def test_tls_not_retried(self):self.assertFalse(retryable(self.probe(message='SSL certificate_verify_failed')))
    def test_403_not_retried(self):self.assertFalse(retryable(self.probe('HTTPError','HTTP Error 403: Forbidden',403)))
    def test_503_retried(self):self.assertTrue(retryable(self.probe('HTTPError','HTTP Error 503: Unavailable',503)))
    def test_429_not_hammered(self):self.assertFalse(retryable(self.probe('HTTPError','HTTP Error 429',429)))
    def test_schema_not_retried(self):self.assertFalse(retryable(self.probe('ValueError','invalid_NAV')))
    def test_stale_not_retried(self):self.assertFalse(retryable({'results':[{'status':'stale'}]}))
    def test_complete_summary_no_retry(self):self.assertFalse(retryable({'results':[{'status':'observed'}]}))
    def scenario(self,failures=1,probe=None):
        base=Path(tempfile.mkdtemp());self.addCleanup(shutil.rmtree,base);calls=[];sleeps=[]
        def execute(config,planned,out):
            out.mkdir();calls.append(out)
            if len(calls)<=failures:
                (out/'raw').mkdir();(out/'raw/probe.json').write_text(json.dumps(probe or self.probe()))
                return {'status':'blocked','private_preview_built':False}
            return {'status':'private_preview_ready','private_preview_built':True}
        result=execute_reliable({}, {'requests':[{},{}]},base/'cycle',execute,sleeps.append)
        return result,calls,sleeps
    def test_recovers_and_keeps_attempts(self):
        r,c,s=self.scenario();self.assertEqual(r['selected_attempt'],'attempt-02');self.assertEqual(s,[2]);self.assertTrue(c[0].exists())
    def test_three_attempt_cap(self):
        r,c,s=self.scenario(10);self.assertEqual(len(c),3);self.assertEqual(s,[2,5]);self.assertEqual(r['status'],'blocked')
    def test_parser_failure_stops_immediately(self):
        r,c,s=self.scenario(10,self.probe('ValueError','invalid_NAV'));self.assertEqual(len(c),1);self.assertEqual(s,[])


if __name__=='__main__':unittest.main()
