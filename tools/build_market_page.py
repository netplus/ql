#!/usr/bin/env python3
"""Build an extensible ql Page, independent of the legacy six-by-six preview.

Local preview may embed a validated private snapshot. Public assets contain no
market records unless a separately reviewed, exact-byte publication approval is
provided for a public-market bundle. This tool never deploys or changes GitHub.
"""
from __future__ import annotations
import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLE = '''
.market-bar{display:flex;gap:12px;align-items:center;flex-wrap:wrap;padding:16px;border:1px solid var(--line);border-radius:12px;margin-bottom:16px;background:var(--paper)}
.market-bar strong{flex:1;min-width:200px;font-size:13px;overflow-wrap:anywhere}.market-bar p{flex-basis:100%;margin:0;font-size:12px;color:var(--muted);overflow-wrap:anywhere}.market-bar p:empty{display:none}.market-bar p[data-error=true]{color:var(--up)}
@media(max-width:760px){.market-bar{padding:12px;gap:8px}.market-bar strong{flex-basis:100%}.market-bar button{flex:1}}
'''
BAR = '''<section class="market-bar" aria-label="数据与更新"><strong id="market-status">正在校验数据…</strong><button id="market-refresh">检查本站更新</button><button id="market-open" class="primary">载入本地数据</button><input id="market-file" type="file" accept=".json,application/json" hidden><p id="market-message" role="status" aria-live="polite"></p></section>'''
DIALOG = '''<dialog id="market-dialog" aria-labelledby="market-title"><div class="dialogtop"><h2 id="market-title">载入观察数据</h2></div><div class="cardbody"><p id="market-confirm"></p><div class="personaltools"><button id="market-cancel">取消</button><button id="market-accept" class="primary">确认载入</button></div></div></dialog>'''


def encoded(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(',', ':')).replace('<', '\\u003c').replace('&', '\\u0026')


def canonical(raw: bytes) -> dict:
    if len(raw) > 2 * 1024 * 1024:
        raise ValueError('Bundle exceeds 2 MiB')
    if not shutil.which('node'):
        raise ValueError('Node.js is required for build-time schema/decimal validation only')
    script = "const m=require(process.argv[1]);let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{try{process.stdout.write(JSON.stringify(m.parse(s)));}catch(e){console.error(e.message);process.exitCode=2;}});"
    p = subprocess.run(['node', '-e', script, str(ROOT/'web/market-data.js')], input=raw, capture_output=True, timeout=30)
    if p.returncode:
        raise ValueError(p.stderr.decode('utf-8', 'replace').strip())
    return json.loads(p.stdout)


def template(transport: str) -> str:
    text = (ROOT/'web/index.template.html').read_text(encoding='utf-8')
    text = text.replace('<html lang="zh-CN">', f'<html lang="zh-CN" data-transport="{transport}">')
    text = text.replace('<main id="content" tabindex="-1">', '<main id="content" tabindex="-1">'+BAR)
    text = text.replace('<div id="toast"', DIALOG+'<div id="toast"')
    text = text.replace('私人研究预览', 'ETF研究工作台').replace('真实样例 · 不自动更新', '取证快照 · 采集待接通').replace('PAGE 01','PAGE 03').replace('历史样例','取证快照')
    text = text.replace('id="ql-data" type="application/json">__PAYLOAD__', 'id="ql-data" type="application/json">null</script><script id="market-data" type="application/json">__PAYLOAD__')
    return text


def build(output: Path, data_file: Path | None = None, approval_file: Path | None = None) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError('Use a new output directory; previous releases are not overwritten')
    bundle = canonical(data_file.read_bytes()) if data_file else None
    css = (ROOT/'web/style.css').read_text(encoding='utf-8') + STYLE
    boot = (ROOT/'web/market-boot.js').read_text(encoding='utf-8')
    engine = (ROOT/'web/market-data.js').read_text(encoding='utf-8')
    loader = (ROOT/'web/market-loader.js').read_text(encoding='utf-8')
    app = (ROOT/'web/market-app.js').read_text(encoding='utf-8')
    bootstrap = 'window.qlStartMarketApp=()=>{\n'+app+'\n};\nif(!window.QLMarketData||!window.QLMarketLoader){window.QLMarketBoot.fail();}else{QLMarketLoader.start(window.qlStartMarketApp);}'
    if '</script' in (boot+engine+loader+bootstrap).lower():
        raise ValueError('Unsafe script terminator')
    content = {'market-boot.js':boot.encode(), 'market-data.js':engine.encode(), 'market-loader.js':loader.encode(), 'market-app.js':bootstrap.encode(), 'style.css':css.encode()}
    assets = {}; names = {}
    for name, raw in content.items():
        stem, suffix = name.rsplit('.',1)
        new = stem+'.'+hashlib.sha256(raw).hexdigest()[:16]+'.'+suffix
        assets[new] = raw; names[name] = new
    shell = template('same-origin').replace("connect-src 'none'", "connect-src 'self'").replace("script-src 'unsafe-inline'", "script-src 'self'").replace("style-src 'unsafe-inline'", "style-src 'self' 'unsafe-inline'")
    integrity = lambda n: 'sha384-'+base64.b64encode(hashlib.sha384(content[n]).digest()).decode()
    shell = shell.replace('<style>/*__CSS__*/</style>', f'<link rel="stylesheet" href="./{names["style.css"]}" integrity="{integrity("style.css")}">').replace('__PAYLOAD__','null')
    scripts = ''.join(f'<script defer src="./{names[n]}" integrity="{integrity(n)}"></script>' for n in ['market-boot.js','market-data.js','market-loader.js','market-app.js'])
    shell = shell.replace('<script>/*__APP__*/</script>',scripts)
    assets['index.html'] = shell.encode(); assets['.nojekyll'] = b''
    manifest = {'schema':'ql.market-manifest/2','state':'unpublished'}
    if approval_file:
        approval = json.loads(approval_file.read_text(encoding='utf-8'))
        if not bundle or bundle['audience'] != 'public-market':
            raise ValueError('Private-review data must not enter public assets')
        data = encoded(bundle).encode()
        sha = hashlib.sha256(data).hexdigest()
        if (approval.get('schema')!='ql.publication-approval/1' or approval.get('canonical_data_sha256')!=sha or
                set(approval.get('source_ids',[]))!=set(bundle['sources']) or not approval.get('review_reference')):
            raise ValueError('A complete, exact-bundle publication review is required')
        filename=f'market.{sha}.json'; assets[filename]=data
        manifest={'schema':'ql.market-manifest/2','state':'ready','file':filename,'sha256':sha,'bytes':len(data),'version':bundle['version'],'asof':bundle['asof']}
    assets['market.manifest.json'] = encoded(manifest).encode()
    assets['release.manifest.json'] = encoded({'schema':'ql.market-release/2','market_data_included':manifest['state']=='ready','files':{n:hashlib.sha256(v).hexdigest() for n,v in assets.items()}}).encode()
    output.parent.mkdir(parents=True,exist_ok=True)
    stage=Path(tempfile.mkdtemp(prefix='.market-build-',dir=output.parent))
    try:
        public=stage/'public'; public.mkdir()
        for name,raw in assets.items(): (public/name).write_bytes(raw)
        preview=template('embedded').replace('/*__CSS__*/',css).replace('__PAYLOAD__',encoded(bundle)).replace('/*__APP__*/',boot+'\n'+engine+'\n'+loader+'\n'+bootstrap)
        (stage/'preview.html').write_text(preview,encoding='utf-8')
        if bundle: (stage/'private-bundle.json').write_text(encoded(bundle),encoding='utf-8')
        stage.rename(output)
    finally:
        if stage.exists(): shutil.rmtree(stage)
    return {'public_files':sorted(assets),'market_data_published':manifest['state']=='ready','deployed':False,'products':len(bundle['products']) if bundle else 0,'asof':bundle['asof'] if bundle else None}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True);p.add_argument('--input',type=Path);p.add_argument('--publication-approval',type=Path);a=p.parse_args()
    try: print(json.dumps(build(a.output,a.input,a.publication_approval),ensure_ascii=False,indent=2))
    except (OSError,ValueError,KeyError,TypeError,subprocess.TimeoutExpired) as exc: p.exit(2,f'Build failed: {exc}\n')
