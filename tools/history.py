#!/usr/bin/env python3
"""Explicit local history operations. Default is dry-run; no network or publication.

The storage directory must be outside the source repository, in an existing
private/trusted parent. --execute is required for writes (including snapshots).
Source permissions and persistent-host selection are separate operational gates.
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.history_store import Store, HistoryError, encode, private_file, outside_repo, MAX_BUNDLE


def read_file(path: Path, limit: int = MAX_BUNDLE) -> bytes:
    if path.is_symlink() or not path.is_file() or path.stat().st_size > limit:
        raise HistoryError('invalid_or_oversized_input')
    with path.open('rb') as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise HistoryError('input_too_large')
    return data


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['init', 'ingest', 'snapshot', 'audit', 'backup', 'restore'])
    parser.add_argument('--store', type=Path, required=True)
    parser.add_argument('--input', type=Path)
    parser.add_argument('--calendar', type=Path)
    parser.add_argument('--codes', help='Comma-separated configured product codes')
    parser.add_argument('--benchmark', default='510330')
    parser.add_argument('--cutoff', help='Knowledge time with timezone, not a trade date')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--responses-dir', type=Path,
                        help='Optional local raw evidence files named <sha256>.bin')
    parser.add_argument('--execute', action='store_true')
    args = parser.parse_args(argv)
    try:
        outside_repo(args.store)
        if args.operation == 'ingest' and not args.input:
            raise HistoryError('input_required')
        if args.operation == 'snapshot' and not all([args.calendar, args.codes, args.output]):
            raise HistoryError('calendar_codes_output_required')
        if args.operation in ('backup', 'restore') and not args.output:
            raise HistoryError('new_destination_required')
        if not args.execute:
            print(json.dumps({'schema': 'ql.history-plan/1', 'operation': args.operation,
                              'mode': 'dry_run', 'writes': False, 'network': False,
                              'remote_persistence_verified': False, 'market_data_published': False}))
            return 0
        if args.operation == 'init':
            result = Store.create(args.store).audit()
        elif args.operation == 'restore':
            result = Store.restore(args.store, args.output).audit()
        else:
            store = Store(args.store)
            if args.operation == 'ingest':
                raw = read_file(args.input)
                responses = {}
                # Only explicitly referenced digest-named files may be read.
                b = json.loads(raw)
                for sid, source in b.get('sources', {}).items():
                    if source.get('raw_response_archived'):
                        import re
                        checksum = source.get('evidence_sha256')
                        if not args.responses_dir or not isinstance(checksum, str) or not re.fullmatch(r'[a-f0-9]{64}', checksum):
                            raise HistoryError('raw_evidence_directory_required')
                        directory = outside_repo(args.responses_dir)
                        responses[sid] = read_file(directory / (checksum + '.bin'))
                result = store.ingest(raw, responses=responses)
            elif args.operation == 'audit':
                result = store.audit()
            elif args.operation == 'backup':
                result = store.backup(args.output)
            else:
                calendar = json.loads(read_file(args.calendar, 131072))
                output = outside_repo(args.output)
                if not output.parent.is_dir():
                    raise HistoryError('parent_directory_required')
                if output.exists() or output.is_symlink():
                    raise HistoryError('snapshot_output_exists')
                bundle, result = store.snapshot(calendar, args.codes.split(','), args.benchmark,
                                                 cutoff=args.cutoff)
                private_file(output, encode(bundle))
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    except Exception as exc:
        # No raw rows, paths, URLs, or arbitrary exception details in shared logs.
        code = str(exc) if isinstance(exc, HistoryError) else 'history_operation_failed'
        print(json.dumps({'status': 'failed', 'reason_code': code,
                          'error_type': type(exc).__name__, 'market_data_published': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
