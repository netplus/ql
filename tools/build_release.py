#!/usr/bin/env python3
"""Build a data-free Pages candidate and a separate private review bundle.

No upload, Pages configuration, paid runner, scheduler or market acquisition.
The public artifact does not bypass the P0 data redistribution gate.
"""
from __future__ import annotations
import argparse
import hashlib
import json
import shutil
import sys
import tempfile
from pathlib import Path
from zipfile import ZipFile, ZIP_DEFLATED

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools.build_page import make_payload

VERSION = 'p1.1-local-bundle/1'
PUBLIC_FILES = {'index.html', '.nojekyll', 'release.manifest.json', 'style.css', 'release.css', 'release.js', 'app.js', 'start.js'}
STYLE = '''
.dataset-bar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:16px;padding:14px 16px;background:var(--paper);border:1px solid var(--line);border-radius:12px}
.dataset-bar .dataset-info{flex:1;min-width:180px}.dataset-bar strong{font-size:13px;display:block}.dataset-bar small{color:var(--muted)}
#bundle-message{font-size:12px;color:var(--muted);width:100%;overflow-wrap:anywhere}#bundle-message:empty{display:none}#bundle-message[data-error=true]{color:var(--up)}
.release-welcome{padding:40px}.release-welcome h1{margin:14px 0}.release-welcome>.sub{max-width:700px}.release-welcome>.primary{margin:24px 0}.release-welcome .healthgrid{margin-top:18px}
@media(max-width:760px){.dataset-bar{padding:12px;gap:8px}.dataset-bar .dataset-info{flex-basis:100%}.dataset-bar button{flex:1;padding:8px}.release-welcome{padding:22px}.release-welcome h1{font-size:25px}}
'''
BAR = '''<section class="dataset-bar" aria-label="市场数据包">
<div class="dataset-info"><strong id="dataset-status">正在校验数据…</strong><small>文件仅在本机读取；非自动更新行情服务</small></div>
<button class="primary" id="bundle-open">载入数据 ↑</button><button id="bundle-clear" disabled>移除标签页数据</button>
<input id="bundle-file" type="file" accept=".json,application/json" hidden><p id="bundle-message" role="status" aria-live="polite"></p></section>'''
DIALOG = '''<dialog id="bundle-dialog" aria-labelledby="bundle-title"><div class="dialogtop"><h2 id="bundle-title">载入市场数据包</h2></div><div class="cardbody"><p id="bundle-confirm-text"></p><div class="personaltools gap"><button id="bundle-cancel">取消</button><button class="primary" id="bundle-accept">仅在本地载入</button></div></div></dialog>'''


def encoded(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('&', '\\u0026')


def render(payload: dict | None = None) -> str:
    template = (ROOT / 'web/index.template.html').read_text(encoding='utf-8')
    css = (ROOT / 'web/style.css').read_text(encoding='utf-8') + STYLE
    app = (ROOT / 'web/app.js').read_text(encoding='utf-8')
    loader = (ROOT / 'web/release.js').read_text(encoding='utf-8')
    if '</script' in (app + loader).lower():
        raise ValueError('Unsafe script terminator')
    for marker in ['/*__CSS__*/', '/*__APP__*/', '__PAYLOAD__']:
        if template.count(marker) != 1:
            raise ValueError('Unexpected template markers')
    script = 'window.qlStartApp=()=>{\n' + app + '\n};\n' + loader + '\nQLRelease.start(window.qlStartApp);'
    template = template.replace('<main id="content" tabindex="-1">', '<main id="content" tabindex="-1">\n' + BAR)
    template = template.replace('<div id="toast"', DIALOG + '\n<div id="toast"')
    template = template.replace('私人研究预览<small>真实样例 · 不自动更新', '本地数据工作台<small>页面与数据分离 · 不自动更新')
    template = template.replace('PAGE 01', 'PAGE 02').replace('class="chip">历史样例', 'class="chip">本地数据')
    return template.replace('/*__CSS__*/', css).replace('__PAYLOAD__', encoded(payload)).replace('/*__APP__*/', script)



def public_assets() -> dict[str, bytes]:
    # Static same-origin assets; app.js executes only after a local bundle is accepted.
    inline = render(None)
    a, b = inline.index('<style>'), inline.index('</style>') + len('</style>')
    inline = inline[:a] + '<link rel="stylesheet" href="./style.css"><link rel="stylesheet" href="./release.css">' + inline[b:]
    a, b = inline.index('<script>'), inline.rindex('</script>') + len('</script>')
    inline = inline[:a] + '<script defer src="./release.js"></script><script defer src="./start.js"></script>' + inline[b:]
    inline = inline.replace("script-src 'unsafe-inline'", "script-src 'self'")
    # Existing SVG/chart code creates inline styles; keep style-src narrowly local plus inline.
    inline = inline.replace("style-src 'unsafe-inline'", "style-src 'self' 'unsafe-inline'")
    start = """/* Load only our own application code after local data validation. */
QLRelease.start(()=>{
 const s=document.createElement('script');s.src='./app.js';
 s.onerror=()=>{document.querySelector('#bundle-message').textContent='应用脚本载入失败，请刷新重试；本地数据没有上传。';};
 document.body.appendChild(s);
});
"""
    return {'index.html': inline.encode('utf-8'), '.nojekyll': b'',
            'style.css': (ROOT/'web/style.css').read_bytes(), 'release.css': STYLE.encode('utf-8'),
            'release.js': (ROOT/'web/release.js').read_bytes(), 'app.js': (ROOT/'web/app.js').read_bytes(),
            'start.js': start.encode('utf-8')}


def public_manifest(assets: dict[str, bytes]) -> dict:
    return {'schema':'ql.public-shell/1', 'version':VERSION,
            'market_data_included':False, 'personal_data_included':False,
            'files':{name:digest(content) for name,content in sorted(assets.items())}}


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def audit_public(directory: Path) -> dict:
    """Verify content against a fresh data-free build, not just a self-declared hash."""
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError('Invalid public directory')
    entries = list(directory.iterdir())
    if {p.name for p in entries} != PUBLIC_FILES or any(p.is_symlink() or not p.is_file() for p in entries):
        raise ValueError('Public directory contains extra, missing or linked files')
    expected_assets = public_assets()
    for name, content in expected_assets.items():
        if (directory/name).read_bytes() != content:
            raise ValueError('Public content is not the exact data-free application')
    manifest = json.loads((directory / 'release.manifest.json').read_text(encoding='utf-8'))
    expected = public_manifest(expected_assets)
    if manifest != expected:
        raise ValueError('Public manifest mismatch')
    return manifest


def build_release(output: Path, nav_file: Path | None = None, share_file: Path | None = None) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('Output must be a new directory; previous versions are not overwritten')
    nav_file = nav_file or ROOT / 'research/p0/nav_sample_20261016.json'
    share_file = share_file or ROOT / 'research/p0/share_sample_20261016.json'
    raw = [p.read_bytes() for p in (nav_file, share_file)]
    payload = make_payload(*(json.loads(b) for b in raw))
    if len(payload['products']) != 6 or len(payload['dates']) != 6:
        raise ValueError('This release supports only the bounded P0 review-bundle contract')
    payload['version'] = VERSION
    bundle = {'schema': 'ql.review-bundle/1', 'payload': payload}
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix='.ql-stage-', dir=output.parent))
    try:
        public, private = stage / 'public', stage / 'private'
        public.mkdir(); private.mkdir()
        assets = public_assets()
        for name, content in assets.items():
            (public/name).write_bytes(content)
        manifest = public_manifest(assets)
        (public / 'release.manifest.json').write_text(json.dumps(manifest, indent=2) + '\n', encoding='utf-8')
        (private / 'ql-review.json').write_text(json.dumps(bundle, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        (private / 'ql-preview.html').write_text(render(payload), encoding='utf-8')
        (private / 'ql-shell-offline.html').write_text(render(None), encoding='utf-8')
        (private / 'evidence.manifest.json').write_text(json.dumps({
            'schema': 'ql.private-evidence/1', 'asof': payload['asof'],
            'input_sha256': {'nav': digest(raw[0]), 'shares': digest(raw[1])},
            'source_reverified_this_build': False, 'auto_updated': False,
            'public_export_allowed': False}, indent=2) + '\n', encoding='utf-8')
        audit_public(public)
        with ZipFile(stage / 'pages-public.zip', 'w', ZIP_DEFLATED) as archive:
            for name in sorted(PUBLIC_FILES):
                archive.write(public / name, name)
        # Atomic publication of a new local version; this is not a remote deployment.
        stage.rename(output)
        return {'version': VERSION, 'public_audit': 'passed', 'public_files': sorted(PUBLIC_FILES),
                'private_data_asof': payload['asof'], 'network_requests': 0, 'deployed': False}
    finally:
        if stage.exists():
            shutil.rmtree(stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'dist/release-p1.1')
    parser.add_argument('--nav-input', type=Path)
    parser.add_argument('--share-input', type=Path)
    args = parser.parse_args()
    try:
        print(json.dumps(build_release(args.output, args.nav_input, args.share_input), ensure_ascii=False, indent=2))
    except (OSError, ValueError, TypeError, KeyError) as exc:
        parser.exit(2, f'Release build failed: {exc}\n')
