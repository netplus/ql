"""Strict, bounded HTML decoding. No encoding guesses or lossy replacement."""
from __future__ import annotations
import gzip
import io
import re
from html.parser import HTMLParser

LIMIT = 2 * 1024 * 1024
ENCODINGS = {'utf8': 'utf-8', 'utf-8': 'utf-8', 'gbk': 'gbk',
             'gb2312': 'gb2312', 'gb18030': 'gb18030'}

class MetaCharset(HTMLParser):
    def __init__(self):
        super().__init__(); self.labels = []
    def handle_starttag(self, tag, attrs):
        if tag != 'meta': return
        a = dict(attrs)
        if a.get('charset'):
            self.labels.append(a['charset'])
        elif a.get('http-equiv', '').lower() == 'content-type':
            m = re.search(r'charset\s*=\s*[\"\']?([\w-]+)', a.get('content', ''), re.I)
            if m: self.labels.append(m.group(1))


def decode_html(raw: bytes, charset: str | None = None,
                content_encoding: str | None = None) -> tuple[str, dict]:
    if len(raw) > LIMIT: raise ValueError('response_too_large')
    transport = (content_encoding or 'identity').strip().lower()
    if transport not in ('identity', 'gzip'):
        raise ValueError('unsupported_content_encoding')
    body = raw
    if transport == 'gzip':
        with gzip.GzipFile(fileobj=io.BytesIO(raw), mode='rb') as f:
            body = f.read(LIMIT + 1)
        if len(body) > LIMIT: raise ValueError('decoded_response_too_large')
    elif raw.startswith(b'\x1f\x8b'):
        raise ValueError('undeclared_compressed_response')
    # Latin-1 here is a byte-preserving way to inspect ASCII metadata only.
    # Actual HTML is decoded strictly using its declared encoding below.
    p = MetaCharset(); p.feed(body[:8192].decode('latin-1'))
    labels = {x.strip().lower() for x in p.labels}
    if len(labels) > 1: raise ValueError('conflicting_meta_charset')
    meta = next(iter(labels), None)
    header = charset.strip().lower() if charset else None
    if body.startswith(b'\xef\xbb\xbf'):
        encoding, basis = 'utf-8', 'utf8_bom'
        if header and ENCODINGS.get(header) != 'utf-8': raise ValueError('conflicting_bom_charset')
    elif header:
        encoding, basis = ENCODINGS.get(header), 'http_header'
    elif meta:
        encoding, basis = ENCODINGS.get(meta), 'html_meta'
    else:
        encoding, basis = 'utf-8', 'default_utf8_strict'
    if not encoding: raise ValueError('unsupported_encoding')
    html = body.decode(encoding)
    if html.startswith('\ufeff'): html = html[1:]
    return html, {'encoding': encoding, 'encoding_source': basis,
                  'content_encoding': transport, 'header_charset': header,
                  'meta_charset': meta, 'decoded_bytes': len(body)}
