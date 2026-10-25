#!/usr/bin/env python3
"""Join reviewed collection, append-only history and a private current snapshot.

Default is a no-write plan. Execute requires an initialized history store and an
explicit, current source-use review. Resume never performs source requests.
No scheduler, cloud credentials, public export or Pages deployment is included.
Linux/local filesystems only: this lock is not a multi-host/NFS guarantee.
"""
from __future__ import annotations
import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import secrets
import stat
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import run_nav_cycle as nav
from tools.build_market_page import build, canonical
from tools.history_store import Store, HistoryError, encode, instant, now, outside_repo, private_file, sha
from tools.market_calendar import latest_completed, window
from tools.retry_nav_cycle import execute_reliable

LIMIT = 2 * 1024 * 1024
RUN_ID = re.compile(r'[a-f0-9]{24}\Z')

class PipelineError(ValueError):
    pass


def read(path: Path, limit: int = LIMIT) -> bytes:
    outside_repo(path)
    s = path.stat(follow_symlinks=False)
    if not stat.S_ISREG(s.st_mode) or s.st_nlink != 1 or s.st_size > limit:
        raise PipelineError('invalid_checkpoint_file')
    with path.open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise PipelineError('checkpoint_too_large')
    return raw


def sync_dir(path: Path) -> None:
    fd = os.open(path, os.O_RDONLY | getattr(os, 'O_DIRECTORY', 0))
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def write_once(path: Path, raw: bytes) -> None:
    if path.exists() or path.is_symlink():
        if read(path, max(LIMIT, len(raw))) != raw:
            raise PipelineError('immutable_file_mismatch')
    else:
        private_file(path, raw)
        sync_dir(path.parent)


def replace_json(path: Path, obj: dict) -> None:
    outside_repo(path)
    temporary = path.with_name('.' + path.name + '.' + secrets.token_hex(8))
    try:
        private_file(temporary, encode(obj))
        os.replace(temporary, path)
        sync_dir(path.parent)
    finally:
        if temporary.exists():
            temporary.unlink()


@contextmanager
def writer(store: Store):
    if os.name != 'posix':
        raise PipelineError('local_posix_runtime_required')
    import fcntl
    path = outside_repo(store.directory / '.pipeline.lock')
    flags = os.O_RDWR | os.O_CREAT | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    previous = None
    try:
        s = os.fstat(fd)
        if s.st_nlink != 1 or not stat.S_ISREG(s.st_mode) or stat.S_IMODE(s.st_mode) & 0o077:
            raise PipelineError('invalid_pipeline_lock')
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise PipelineError('pipeline_busy') from exc
        previous = os.umask(0o077)
        yield
    finally:
        if previous is not None:
            os.umask(previous)
        os.close(fd)


def local_directory(parent: Path, name: str) -> Path:
    p = outside_repo(parent / name)
    p.mkdir(mode=0o700, exist_ok=True)
    if not p.is_dir() or stat.S_IMODE(p.stat().st_mode) & 0o077:
        raise PipelineError('state_permissions_not_private')
    return p


def review_sources(planned: dict, review: dict, at: datetime) -> None:
    """A review record is a prerequisite, not a license created by this program."""
    if review.get('schema') != 'ql.source-use-review/1':
        raise PipelineError('source_use_review_required')
    decisions = review.get('sources', {})
    for request in planned['requests']:
        decision = decisions.get(request['url'], {})
        if (decision.get('status') != 'approved' or
            decision.get('collection_allowed') is not True or
            decision.get('local_raw_retention_allowed') is not True or
            not isinstance(decision.get('review_reference'), str) or
            not decision['review_reference'].strip()):
            raise PipelineError('source_use_review_pending')
        if instant(decision.get('reviewed_at')) > instant(at):
            raise PipelineError('future_source_use_review')
        if instant(decision.get('expires_at')) <= instant(at):
            raise PipelineError('source_use_review_expired')


def intent(config: dict, planned: dict, snapshot_calendar: dict) -> dict:
    codes = [r['code'] for r in planned['requests']]
    if nav.make_plan(config, planned['calendar'], codes, planned['start'], planned['end']) != planned:
        raise PipelineError('plan_mismatch')
    nav.make_plan(config, snapshot_calendar, codes,
                  snapshot_calendar['coverage_start'], snapshot_calendar['coverage_end'])
    if (snapshot_calendar['coverage_end'] != planned['end'] or
        not set(planned['calendar']['sessions']).issubset(snapshot_calendar['sessions'])):
        raise PipelineError('snapshot_window_mismatch')
    body = {'config': config, 'plan': planned, 'snapshot_calendar': snapshot_calendar}
    return {'schema': 'ql.history-cycle-intent/1', 'body': body, 'sha256': sha(encode(body))}


def load_intent(run: Path) -> dict:
    obj = json.loads(read(run / 'intent.json'))
    if obj.get('schema') != 'ql.history-cycle-intent/1' or sha(encode(obj['body'])) != obj.get('sha256'):
        raise PipelineError('intent_hash_mismatch')
    b = obj['body']
    if intent(b['config'], b['plan'], b['snapshot_calendar']) != obj:
        raise PipelineError('intent_mismatch')
    return b


def verified_checkpoint(run: Path, body: dict) -> tuple[dict, dict[str, bytes], dict]:
    cycle = json.loads(read(run / 'acquisition/cycle.json', 65536))
    attempt = cycle.get('selected_attempt')
    if cycle.get('status') != 'private_preview_ready' or attempt not in ('attempt-01', 'attempt-02', 'attempt-03'):
        raise PipelineError('acquisition_not_ready')
    source = outside_repo(run / 'acquisition' / attempt / 'raw')
    probe = json.loads(read(source / 'probe.json', 256 * 1024))
    planned = body['plan']
    # Freeze raw bytes and parser output once. Reparse and store those same bytes;
    # neither a claimed green summary nor a precomputed market bundle is trusted.
    raw_by_code = {}
    with tempfile.TemporaryDirectory(prefix='.verify-', dir=run) as temporary:
        frozen = Path(temporary)
        for request in planned['requests']:
            code = request['code']
            raw_by_code[code] = read(source / (code + '.html'), nav.collect_nav.LIMIT)
            private_file(frozen / (code + '.html'), raw_by_code[code])
            private_file(frozen / (code + '.rows.json'), read(source / (code + '.rows.json')))
        bundle, checks = nav.assemble(body['config'], planned, probe, frozen)
    # assemble() stamps its rebuild time. Use stable capture evidence instead so
    # replay after a crash has the same batch id and original first-import time.
    bundle['observed_at'] = max(instant(s['recorded_at']) for s in bundle['sources'].values())
    bundle = canonical(encode(bundle))
    responses = {}
    for p in bundle['products']:
        sid = p['observations'][planned['end']]['nav_source']
        responses[sid] = raw_by_code[p['code']]
    receipt = {'schema': 'ql.history-checkpoint/1', 'intent_sha256': sha(encode(body)),
               'probe': probe, 'checks': checks, 'bundle_sha256': sha(encode(bundle))}
    return bundle, responses, receipt


def current(store: Store) -> dict | None:
    path = store.directory / 'current.private.json'
    if not path.exists() and not path.is_symlink():
        return None
    m = json.loads(read(path, 16384))
    checksum = m.get('bundle_sha256', '')
    if (m.get('schema') != 'ql.private-current/1' or m.get('audience') != 'private-review' or
        not re.fullmatch(r'[a-f0-9]{64}', checksum) or
        m.get('file') != f'exports/{checksum}/snapshot.private.json' or
        m.get('preview') != f'exports/{checksum}/build/preview.html'):
        raise PipelineError('invalid_current_manifest')
    raw = read(store.directory / m['file'])
    if sha(raw) != checksum or len(raw) != m.get('bytes'):
        raise PipelineError('current_snapshot_hash_mismatch')
    b = canonical(raw)
    if b['asof'] != m['asof'] or b['observed_at'] != m['knowledge_cutoff'] or b['audience'] != 'private-review':
        raise PipelineError('current_snapshot_metadata_mismatch')
    if sha(read(store.directory / m['preview'], 4 * LIMIT)) != m.get('preview_sha256'):
        raise PipelineError('current_preview_hash_mismatch')
    return m


def finish(store: Store, run: Path, body: dict, *, builder=build) -> dict:
    previous = current(store)
    bundle, responses, receipt = verified_checkpoint(run, body)
    imported = store.ingest(encode(bundle), responses=responses)
    receipts = local_directory(store.directory, 'receipts')
    write_once(receipts / (imported['batch_id'] + '.json'), encode(receipt))
    store.audit()
    with closing(store.connect()) as db:
        cutoff = db.execute('SELECT MAX(known_at) FROM batches').fetchone()[0]
    planned = body['plan']
    snapshot, coverage = store.snapshot(body['snapshot_calendar'],
        [x['code'] for x in planned['requests']], body['config']['benchmark_code'], cutoff=cutoff)
    if coverage['latest_field_counts']['nav'] != coverage['products']:
        raise PipelineError('latest_nav_incomplete')
    raw = encode(snapshot)
    checksum = sha(raw)
    exports = local_directory(store.directory, 'exports')
    release = local_directory(exports, checksum)
    write_once(release / 'snapshot.private.json', raw)
    target = release / 'build'
    if not target.exists():
        result = builder(target, release / 'snapshot.private.json')
        if result['market_data_published'] is not False:
            raise PipelineError('unexpected_publication')
    if json.loads(read(target / 'public/market.manifest.json')).get('state') != 'unpublished':
        raise PipelineError('unexpected_publication')
    if canonical(read(target / 'private-bundle.json')) != snapshot:
        raise PipelineError('built_snapshot_mismatch')
    manifest = {'schema': 'ql.private-current/1', 'audience': 'private-review',
        'asof': snapshot['asof'], 'version': snapshot['version'], 'knowledge_cutoff': cutoff,
        'bundle_sha256': checksum, 'bytes': len(raw),
        'file': f'exports/{checksum}/snapshot.private.json',
        'preview': f'exports/{checksum}/build/preview.html',
        'preview_sha256': sha(read(target / 'preview.html', 4 * LIMIT)), 'market_data_published': False}
    # An old checkpoint may enrich history, but must not roll back the active day.
    if previous and (manifest['asof'] < previous['asof'] or cutoff < previous['knowledge_cutoff']):
        state = 'stored_not_promoted'
    elif manifest == previous:
        state = 'unchanged'
    else:
        replace_json(store.directory / 'current.private.json', manifest)
        state = 'private_snapshot_ready'
    return {'status': state, 'batch_id': imported['batch_id'],
        'inserted_facts': imported['inserted_facts'], 'known_at': imported['known_at'],
        'snapshot_sha256': checksum, 'asof': snapshot['asof'],
        'coverage': coverage, 'raw_responses': len(responses),
        'market_data_published': False, 'daily_schedule_verified': False,
        'persistent_host_bound': False}


def error_result(result: dict, exc: Exception, run: Path | None) -> None:
    result.update(status='blocked', failure_type=type(exc).__name__)
    code = str(exc)
    result['failure_code'] = code if isinstance(exc, (PipelineError, HistoryError, nav.CycleError)) and re.fullmatch(r'[a-z_]{1,80}', code) else 'pipeline_validation_or_io_failed'
    result['recovery'] = 'resume_checkpoint_without_source_requests' if run else 'fix_preflight'
    # Database commit and pointer promotion are separate commits. Do not assert
    # that either was rolled back, particularly after a post-rename I/O error.
    result['current_pointer_state'] = 'not_assumed_unchanged_on_error'


def pipeline(store: Store, *, request: dict | None, review: dict, resume: str | None = None,
             collector=execute_reliable, builder=build) -> dict:
    result = {'schema': 'ql.history-cycle-result/1', 'status': 'blocked', 'stage': 'preflight',
              'run_id': resume, 'market_data_published': False, 'daily_schedule_verified': False,
              'persistent_host_bound': False}
    run = None
    try:
        with writer(store):
            try:
                if resume:
                    if not RUN_ID.fullmatch(resume):
                        raise PipelineError('invalid_run_id')
                    run = outside_repo(store.directory / 'runs' / resume)
                    body = load_intent(run)
                else:
                    if request is None:
                        raise PipelineError('request_required')
                    body = request['body']
                    if intent(body['config'], body['plan'], body['snapshot_calendar']) != request:
                        raise PipelineError('intent_mismatch')
                review_sources(body['plan'], review, store.clock())
                current(store)  # An unknown/corrupt current pointer is not overwritten.
                if not resume:
                    runs = local_directory(store.directory, 'runs')
                    result['run_id'] = secrets.token_hex(12)
                    run = local_directory(runs, result['run_id'])
                    write_once(run / 'intent.json', encode(request))
                    result['stage'] = 'acquisition'
                    collector(body['config'], body['plan'], run / 'acquisition', nav.execute)
                result['stage'] = 'handoff'
                result.update(finish(store, run, body, builder=builder))
                result['stage'] = 'complete'
            except Exception as exc:
                error_result(result, exc, run)
            try:
                if run is not None and run.is_dir() and RUN_ID.fullmatch(run.name):
                    replace_json(run / 'result.json', result)
                replace_json(store.directory / 'last-run.json', result)
            except Exception:
                result['status_record_failed'] = True
    except Exception as exc:
        error_result(result, exc, run)
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--history-root', type=Path, required=True)
    p.add_argument('--config', type=Path, default=ROOT / 'config/market-universe.json')
    p.add_argument('--calendar', type=Path, default=ROOT / 'config/market-calendar-2026.json')
    p.add_argument('--source-review', type=Path, default=ROOT / 'config/source-use-review.json')
    p.add_argument('--codes', default='159995,510330')
    p.add_argument('--start'); p.add_argument('--end'); p.add_argument('--history-start')
    p.add_argument('--resume'); p.add_argument('--execute', action='store_true')
    a = p.parse_args()
    try:
        request = None
        if a.resume:
            if not RUN_ID.fullmatch(a.resume):
                raise PipelineError('invalid_run_id')
        else:
            if not a.start:
                raise PipelineError('start_required')
            config = json.loads(a.config.read_bytes())
            spec = json.loads(a.calendar.read_bytes())
            latest = latest_completed(spec, now())
            end = a.end or latest
            if end > latest:
                raise PipelineError('future_or_incomplete_session')
            planned = nav.make_plan(config, window(spec, a.start, end), a.codes.split(','), a.start, end)
            request = intent(config, planned, window(spec, a.history_start or a.start, end))
        if not a.execute:
            print(json.dumps({'schema': 'ql.history-cycle-plan/1', 'mode': 'dry_run',
                'resume': a.resume, 'request': request, 'max_attempts': 3,
                'source_use_review_required': True, 'market_data_published': False}, ensure_ascii=False))
            return 0
        review = json.loads(a.source_review.read_bytes())
        result = pipeline(Store(a.history_root), request=request, review=review, resume=a.resume)
        print(json.dumps(result, ensure_ascii=False))
        return 0 if result['status'] in ('private_snapshot_ready', 'unchanged', 'stored_not_promoted') else 2
    except Exception:
        p.exit(2, 'History cycle rejected configuration or uninitialized private store.\n')

if __name__ == '__main__':
    raise SystemExit(main())
