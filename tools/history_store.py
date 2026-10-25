#!/usr/bin/env python3
"""Local, append-only history of validated market bundles; never a publisher.

SQLite is a small single-writer persistence adapter, not a cloud storage claim.
System knowledge begins at import time. Source capture time is a separate field.
No network, credentials, encryption, scheduler, or public upload is implemented.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import stat
import sys
from contextlib import closing
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_market_page import canonical

MAX_BUNDLE = 2 * 1024 * 1024
MAX_RAW_TOTAL = 8 * 1024 * 1024
SCHEMA = """
PRAGMA user_version=1;
CREATE TABLE batches (
 id TEXT PRIMARY KEY, known_at TEXT NOT NULL, source_observed_at TEXT NOT NULL,
 asof TEXT NOT NULL, input_sha256 TEXT NOT NULL, payload BLOB NOT NULL
);
CREATE INDEX batch_time ON batches(known_at);
CREATE TABLE products (
 batch_id TEXT NOT NULL REFERENCES batches(id), code TEXT NOT NULL,
 metadata TEXT NOT NULL, PRIMARY KEY(batch_id,code)
);
CREATE TABLE facts (
 batch_id TEXT NOT NULL REFERENCES batches(id), code TEXT NOT NULL,
 trade_date TEXT NOT NULL, field TEXT NOT NULL CHECK(field IN ('nav','shares')),
 value TEXT NOT NULL, value_key TEXT NOT NULL, source_id TEXT NOT NULL,
 source_at TEXT NOT NULL, source_url TEXT NOT NULL,
 PRIMARY KEY(batch_id,code,trade_date,field)
);
CREATE INDEX fact_lookup ON facts(code,trade_date,field,source_at);
CREATE TABLE raw_responses (
 sha256 TEXT PRIMARY KEY, content BLOB NOT NULL
);
CREATE TABLE raw_links (
 batch_id TEXT NOT NULL REFERENCES batches(id), source_id TEXT NOT NULL,
 sha256 TEXT NOT NULL REFERENCES raw_responses(sha256),
 PRIMARY KEY(batch_id,source_id)
);
"""
TABLES = ('batches', 'products', 'facts', 'raw_responses', 'raw_links')


class HistoryError(ValueError):
    """A short, non-sensitive diagnostic; do not print source data."""


def now() -> datetime:
    return datetime.now(timezone.utc)


def instant(value: str | datetime) -> str:
    try:
        d = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace('Z', '+00:00'))
        if d.tzinfo is None or d.utcoffset() is None:
            raise ValueError
        return d.astimezone(timezone.utc).isoformat(timespec='microseconds').replace('+00:00', 'Z')
    except (ValueError, AttributeError, TypeError) as exc:
        raise HistoryError('invalid_knowledge_time') from exc


def encode(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def numeric_key(value: str) -> str:
    return format(Decimal(value).normalize(), 'f')


def outside_repo(path: Path) -> Path:
    """Never store history in this source tree or follow pre-existing links.

    Requires a locally owned, trusted parent directory. This is not an OS sandbox
    against another process changing the parent concurrently.
    """
    path = Path(os.path.abspath(path.expanduser()))
    for p in (path, *path.parents):
        if p.is_symlink():
            raise HistoryError('symlink_path_rejected')
    if path == ROOT or ROOT in path.parents:
        raise HistoryError('history_must_be_outside_source_tree')
    return path


def private_file(path: Path, data: bytes) -> None:
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def fact_rows(b: dict, bid: str) -> list[tuple]:
    rows = []
    for p in b['products']:
        for day, observation in p['observations'].items():
            for field in ('nav', 'shares'):
                value = observation[field]
                if value is not None:
                    sid = observation[field + '_source']
                    source = b['sources'][sid]
                    rows.append((bid, p['code'], day, field, value, numeric_key(value), sid,
                                 instant(source['recorded_at']), source['url']))
    return rows


def product_rows(b: dict, bid: str) -> list[tuple]:
    return [(bid, p['code'], encode({k: v for k, v in p.items() if k != 'observations'}).decode())
            for p in b['products']]


class Store:
    def __init__(self, directory: Path, *, clock: Callable[[], datetime] = now):
        self.directory = outside_repo(directory)
        self.path = self.directory / 'history.sqlite3'
        self.clock = clock
        if not self.directory.is_dir() or self.path.is_symlink() or not self.path.is_file():
            raise HistoryError('store_not_initialized')
        if self.path.stat().st_nlink != 1:
            raise HistoryError('hardlinked_store_rejected')
        if os.name == 'posix' and any(stat.S_IMODE(p.stat().st_mode) & 0o077
                                      for p in (self.directory, self.path)):
            raise HistoryError('store_permissions_not_private')

    @classmethod
    def create(cls, directory: Path, **kwargs) -> 'Store':
        directory = outside_repo(directory)
        if not directory.parent.is_dir():
            raise HistoryError('parent_directory_required')
        directory.mkdir(mode=0o700, exist_ok=False)
        path = directory / 'history.sqlite3'
        private_file(path, b'')
        with closing(sqlite3.connect(path)) as db:
            db.executescript(SCHEMA)
            for table in TABLES:
                for action in ('UPDATE', 'DELETE'):
                    db.execute(f"CREATE TRIGGER {table}_{action.lower()} BEFORE {action} ON {table} "
                               "BEGIN SELECT RAISE(ABORT,'append_only'); END")
            db.commit()
        return cls(directory, **kwargs)

    def connect(self, *, write: bool = False) -> sqlite3.Connection:
        # Recheck before opening; the explicit mode prevents accidental creation.
        Store(self.directory)
        db = sqlite3.connect(self.path.as_uri() + ('?mode=rw' if write else '?mode=ro'),
                             uri=True, isolation_level=None, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        if db.execute('PRAGMA user_version').fetchone()[0] != 1:
            db.close()
            raise HistoryError('unsupported_history_schema')
        if write:
            db.execute('PRAGMA synchronous=FULL')
        return db

    def ingest(self, raw: bytes, *, responses: dict[str, bytes] | None = None) -> dict:
        if len(raw) > MAX_BUNDLE:
            raise HistoryError('bundle_too_large')
        bundle = canonical(raw)  # Same exact field/decimal validator as the Page.
        payload = encode(bundle)
        bid = sha(payload)
        at = instant(self.clock())
        if instant(bundle['observed_at']) > at:
            raise HistoryError('future_observation')
        responses = responses or {}
        expected_raw = {sid for sid, s in bundle['sources'].items() if s['raw_response_archived']}
        if set(responses) != expected_raw:
            raise HistoryError('claimed_raw_evidence_missing_or_extra')
        if sum(len(v) for v in responses.values()) > MAX_RAW_TOTAL:
            raise HistoryError('raw_evidence_budget')
        for sid, value in responses.items():
            if not isinstance(value, bytes) or len(value) > MAX_BUNDLE:
                raise HistoryError('invalid_raw_evidence')
            if sha(value) != bundle['sources'][sid]['evidence_sha256']:
                raise HistoryError('raw_evidence_hash_mismatch')
        rows = fact_rows(bundle, bid)
        products = product_rows(bundle, bid)
        with closing(self.connect(write=True)) as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                existing = db.execute('SELECT known_at FROM batches WHERE id=?', (bid,)).fetchone()
                if existing:
                    db.rollback()
                    return {'status': 'unchanged', 'batch_id': bid, 'known_at': existing['known_at'],
                            'inserted_facts': 0, 'market_data_published': False}
                last = db.execute('SELECT MAX(known_at) FROM batches').fetchone()[0]
                if last and at <= last:
                    raise HistoryError('nonmonotonic_import_clock')
                # Exchange/currency/basis cannot be reinterpreted by a later file.
                for _, code, metadata in products:
                    previous = db.execute('SELECT metadata FROM products WHERE code=? LIMIT 1', (code,)).fetchone()
                    if previous:
                        old, new = json.loads(previous[0]), json.loads(metadata)
                        if any(old[k] != new[k] for k in ('exchange', 'currency', 'basis', 'group')):
                            raise HistoryError('product_identity_changed')
                for row in rows:
                    _, code, day, field, value, key, _, source_at, source_url = row
                    conflict = db.execute('SELECT value_key FROM facts WHERE code=? AND trade_date=? '
                                          'AND field=? AND source_at=? AND source_url=? AND value_key<>? LIMIT 1',
                                          (code, day, field, source_at, source_url, key)).fetchone()
                    if conflict:
                        raise HistoryError('same_capture_conflicting_value')
                db.execute('INSERT INTO batches VALUES (?,?,?,?,?,?)',
                           (bid, at, instant(bundle['observed_at']), bundle['asof'], sha(raw), payload))
                db.executemany('INSERT INTO products VALUES (?,?,?)', products)
                db.executemany('INSERT INTO facts VALUES (?,?,?,?,?,?,?,?,?)', rows)
                for sid, value in responses.items():
                    checksum = sha(value)
                    db.execute('INSERT OR IGNORE INTO raw_responses VALUES (?,?)', (checksum, value))
                    db.execute('INSERT INTO raw_links VALUES (?,?,?)', (bid, sid, checksum))
                db.commit()
            except Exception:
                db.rollback()
                raise
        return {'status': 'inserted', 'batch_id': bid, 'known_at': at, 'products': len(products),
                'inserted_facts': len(rows), 'raw_responses': len(responses),
                'retention_scope': 'local_database', 'market_data_published': False}

    def audit(self) -> dict:
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
                raise HistoryError('database_integrity_failed')
            for batch in db.execute('SELECT * FROM batches ORDER BY known_at,id'):
                payload = bytes(batch['payload'])
                if sha(payload) != batch['id']:
                    raise HistoryError('batch_hash_mismatch')
                b = json.loads(payload)
                if instant(b['observed_at']) != batch['source_observed_at'] or b['asof'] != batch['asof']:
                    raise HistoryError('batch_metadata_mismatch')
                if instant(batch['known_at']) < instant(b['observed_at']):
                    raise HistoryError('invalid_first_seen_time')
                expected = sorted(fact_rows(b, batch['id']))
                actual = sorted(tuple(r) for r in db.execute('SELECT * FROM facts WHERE batch_id=?', (batch['id'],)))
                if expected != actual:
                    raise HistoryError('fact_index_mismatch')
                actual_products = sorted(tuple(r) for r in db.execute('SELECT * FROM products WHERE batch_id=?', (batch['id'],)))
                if actual_products != sorted(product_rows(b, batch['id'])):
                    raise HistoryError('product_index_mismatch')
                expected_links = sorted((batch['id'], sid, s['evidence_sha256'])
                                        for sid, s in b['sources'].items() if s['raw_response_archived'])
                actual_links = sorted(tuple(r) for r in db.execute('SELECT * FROM raw_links WHERE batch_id=?', (batch['id'],)))
                if expected_links != actual_links:
                    raise HistoryError('raw_link_mismatch')
            raw_count = 0
            for r in db.execute('SELECT * FROM raw_responses'):
                if len(r['content']) > MAX_BUNDLE or sha(r['content']) != r['sha256']:
                    raise HistoryError('raw_hash_mismatch')
                raw_count += 1
            counts = {t: db.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0] for t in ('batches', 'facts', 'products')}
            distinct = db.execute('SELECT COUNT(*) FROM (SELECT DISTINCT code,trade_date,field FROM facts)').fetchone()[0]
            revisions = db.execute('SELECT COALESCE(SUM(n-1),0) FROM (SELECT COUNT(DISTINCT value_key) n '
                                   'FROM facts GROUP BY code,trade_date,field,source_url)').fetchone()[0]
            result = {'schema': 'ql.history-audit/1', 'status': 'passed', **counts,
                      'distinct_fields': distinct, 'numeric_revisions': revisions,
                      'raw_responses': raw_count, 'market_data_published': False,
                      'remote_persistence_verified': False}
            db.rollback()
            return result

    def snapshot(self, calendar: dict, codes: list[str], benchmark: str, *, cutoff: str | None = None) -> tuple[dict, dict]:
        at = instant(cutoff or self.clock())
        if at > instant(self.clock()):
            raise HistoryError('future_knowledge_cutoff')
        if not codes or len(codes) != len(set(codes)) or benchmark not in codes:
            raise HistoryError('invalid_snapshot_scope')
        days = calendar.get('sessions', [])
        if not days or len(days) > 520 or len(codes) * len(days) > 16384:
            raise HistoryError('invalid_snapshot_calendar')
        # Single read transaction: metadata and facts see one consistent database state.
        with closing(self.connect()) as db:
            db.execute('BEGIN')
            batches = {r['id']: (r['known_at'], json.loads(r['payload'])) for r in
                       db.execute('SELECT id,known_at,payload FROM batches WHERE known_at<=? ORDER BY known_at,id', (at,))}
            if not batches:
                raise HistoryError('no_data_known_at_cutoff')
            metas = {}
            for _, b in batches.values():
                for p in b['products']:
                    if p['code'] in codes:
                        metas[p['code']] = {k: v for k, v in p.items() if k != 'observations'}
            if set(codes) - set(metas):
                raise HistoryError('unknown_product_at_cutoff')
            wanted_days, wanted_codes = set(days), set(codes)
            chosen, authorities = {}, {}
            query = ('SELECT f.*,b.known_at FROM facts f JOIN batches b ON b.id=f.batch_id '
                     'WHERE b.known_at<=? AND f.trade_date BETWEEN ? AND ? '
                     'ORDER BY f.source_at,b.known_at,b.id')
            for r in db.execute(query, (at, days[0], days[-1])):
                if r['code'] not in wanted_codes or r['trade_date'] not in wanted_days:
                    continue
                key = (r['code'], r['trade_date'], r['field'])
                authorities.setdefault(key, {})[r['source_url']] = r['value_key']
                chosen[key] = dict(r)
            # No implicit provider precedence. Contradictory authorities require review.
            if any(len(set(values.values())) > 1 for values in authorities.values()):
                raise HistoryError('unresolved_cross_source_conflict')
            products, sources = [], {}
            for code in codes:
                observations = {}
                for day in days:
                    o = {'nav': None, 'shares': None, 'nav_source': None, 'shares_source': None}
                    for field in ('nav', 'shares'):
                        selected = chosen.get((code, day, field))
                        if selected:
                            source = batches[selected['batch_id']][1]['sources'][selected['source_id']]
                            sid = 'history-' + sha(encode(source))[:32]
                            sources[sid] = source
                            o[field], o[field + '_source'] = selected['value'], sid
                    observations[day] = o
                products.append({**metas[code], 'observations': observations})
            if not sources:
                raise HistoryError('no_observations_in_window')
            bundle = {'schema': 'ql.market-bundle/2', 'version': 'history/pending',
                      'timezone': 'Asia/Shanghai', 'audience': 'private-review', 'auto_updated': False,
                      'observed_at': at, 'asof': days[-1], 'benchmark_code': benchmark,
                      'calendar': calendar, 'sources': sources, 'products': products}
            # Include actual selected values and provenance in the revision identity.
            bundle['version'] = 'history/' + sha(encode({'products': products, 'sources': sources,
                                                        'calendar': calendar, 'benchmark': benchmark}))[:24]
            bundle = canonical(encode(bundle))
            counts = {f: sum(p['observations'][d][f] is not None for p in products for d in days)
                      for f in ('nav', 'shares')}
            latest = {f: sum(p['observations'][days[-1]][f] is not None for p in products)
                      for f in ('nav', 'shares')}
            report = {'schema': 'ql.history-snapshot/1', 'asof': days[-1], 'knowledge_cutoff': at,
                      'products': len(codes), 'sessions': len(days), 'field_counts': counts,
                      'latest_field_counts': latest, 'expected_rows': len(codes) * len(days),
                      'known_at_semantics': 'first_import_into_this_store_not_historical_source_publication',
                      'bundle_sha256': sha(encode(bundle)), 'market_data_published': False,
                      'source_entries': len(sources), 'raw_response_count': sum(s['raw_response_archived'] for s in sources.values())}
            db.rollback()
            return bundle, report

    def backup(self, destination: Path) -> dict:
        destination = outside_repo(destination)
        if not destination.parent.is_dir():
            raise HistoryError('parent_directory_required')
        destination.mkdir(mode=0o700, exist_ok=False)
        target = destination / 'history.sqlite3'
        private_file(target, b'')
        # SQLite's online backup API makes a consistent database, not a raw file copy.
        with closing(self.connect()) as src, closing(sqlite3.connect(target)) as dst:
            src.backup(dst)
        audit = Store(destination).audit()
        metadata = {'schema': 'ql.history-backup/1', 'created_at': instant(self.clock()),
                    'database_sha256': sha(target.read_bytes()), 'audit': audit}
        private_file(destination / 'backup.json', encode(metadata))
        return metadata

    @classmethod
    def restore(cls, backup_directory: Path, destination: Path) -> 'Store':
        source = cls(backup_directory)
        manifest = source.directory / 'backup.json'
        if manifest.is_symlink() or manifest.stat().st_size > 16384:
            raise HistoryError('invalid_backup_manifest')
        m = json.loads(manifest.read_bytes())
        if m.get('schema') != 'ql.history-backup/1' or sha(source.path.read_bytes()) != m.get('database_sha256'):
            raise HistoryError('backup_hash_mismatch')
        source.audit()
        source.backup(destination)
        restored = cls(destination)
        restored.audit()
        return restored
