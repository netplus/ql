#!/usr/bin/env python3
"""Version and check an already audited data-free P1.1 release; no deployment.

Run tools/build_release.py first, then use its public/ directory as --source.
Only this existing bounded shell contract is supported, not arbitrary websites.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import shutil
import tempfile
from pathlib import Path

VERSION = "p1.2-pages-integrity/1"
LEGACY_FILES = {"index.html", ".nojekyll", "release.manifest.json", "app.js",
                "release.js", "start.js", "style.css", "release.css"}
# Explicitly approved empty-shell baseline. Update only after a new source audit.
APPROVED_INPUT = {'.nojekyll': 'e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855', 'app.js': '666b3d3f96e5dfb0fb7bde4202d53eea09d8c8017cbd3d29d27604c2415397ab', 'index.html': '3e0274e11dddfa81491f516e7f33ead5191664a941bb02062d3870a146c6874e', 'release.css': 'd4ec649c35467b4e5c5db26c653ea9c45bcc13f7ebc30751247e010f0c2c63e1', 'release.js': '84131af892a844aaa11fde7d979b07535dc07144741673bcae15c3d5c6bcbca1', 'start.js': 'e2ee806ac62b029c1f227af68be07341f51bd025ec6d1539db3ddc01755e7857', 'style.css': 'ded5129c89dca033fa85ae58a60c9c042a41f9e77b8103cf1158d3ecf713e567'}
ASSETS = ("app.js", "release.js", "style.css", "release.css")
BOOT_STATUS = '''<section id="boot-status" class="notice" role="status" aria-live="polite">
<span id="boot-text">正在启动工作台。若此提示一直保留，脚本可能未能加载；请刷新或检查浏览器设置。</span>
<button id="boot-retry" type="button" hidden>重新载入页面</button></section>'''


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def integrity(data: bytes) -> str:
    return "sha256-" + base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")


def fingerprint(name: str, data: bytes) -> str:
    path = Path(name)
    return f"{path.stem}.{digest(data)[:16]}{path.suffix}"


def read_legacy(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Source must be an ordinary directory")
    paths = list(directory.iterdir())
    if {p.name for p in paths} != LEGACY_FILES or any(p.is_symlink() or not p.is_file() for p in paths):
        raise ValueError("Unexpected, missing, or linked source files")
    values = {p.name: p.read_bytes() for p in paths}
    if any(len(b) > 512 * 1024 for b in values.values()):
        raise ValueError("Source file exceeds the bounded shell contract")
    manifest = json.loads(values.pop("release.manifest.json"))
    expected = {name: digest(b) for name, b in sorted(values.items())}
    if (manifest.get("schema") != "ql.public-shell/1"
            or manifest.get("version") != "p1.1-local-bundle/1"
            or manifest.get("market_data_included") is not False
            or manifest.get("personal_data_included") is not False
            or manifest.get("files") != expected or expected != APPROVED_INPUT):
        raise ValueError("Source manifest or byte hashes do not match")
    html = values["index.html"].decode("utf-8")
    if '<script id="ql-data" type="application/json">null</script>' not in html:
        raise ValueError("Source is not an empty shell")
    # Hashes check bytes, not trust or licensing. Retain the build_release.py audit.
    return values


def boot_script(app_name: str, app_sri: str) -> bytes:
    template = r'''/* ql startup: same-origin resources only; never remove stored user data. */
(() => {
'use strict';
const byId=id=>document.getElementById(id);
const status=byId('boot-status'),text=byId('boot-text'),retry=byId('boot-retry');
let failed=false, started=false, script=null, timer=null;
const stop=()=>{if(timer!==null){clearTimeout(timer);timer=null;}};
function showFailure(message){
 failed=true;stop();status.hidden=false;status.setAttribute('role','alert');
 text.textContent=message+' 本地数据未上传，也未被删除。';retry.hidden=false;
 const output=byId('bundle-message');if(output){output.textContent=text.textContent;output.dataset.error='true';}
}
function ready(){if(!failed){stop();status.hidden=true;}}
retry.addEventListener('click',()=>location.reload());
window.addEventListener('error',event=>{
 if(script&&event.filename&&event.filename.split('?')[0]===script.src.split('?')[0]){
  showFailure('工作台脚本执行失败，请重新载入页面。');
 }
});
function launch(){
 if(started)return;started=true;status.hidden=false;text.textContent='正在载入工作台…';
 script=document.createElement('script');script.src=__APP_PATH__;
 script.integrity=__APP_SRI__;script.crossOrigin='anonymous';
 script.addEventListener('error',()=>showFailure('应用资源未能加载或校验未通过，请重新载入页面。'));
 script.addEventListener('load',ready);
 timer=setTimeout(()=>showFailure('应用资源载入超时，请检查网络后重新载入。'),20000);
 document.body.appendChild(script);
}
try{
 if(!window.QLRelease||typeof window.QLRelease.start!=='function'){
  showFailure('数据加载组件未能启动，请重新载入页面。');return;
 }
 window.QLRelease.start(launch);if(!started)ready();
}catch{showFailure('页面初始化失败，请重新载入页面。');}
})();
'''
    return template.replace("__APP_PATH__", json.dumps("./" + app_name)).replace(
        "__APP_SRI__", json.dumps(app_sri)).encode("utf-8")


def make_candidate(legacy: dict[str, bytes]) -> dict[str, bytes]:
    if set(legacy) != LEGACY_FILES - {"release.manifest.json"}:
        raise ValueError("Unexpected source asset set")
    html = legacy["index.html"].decode("utf-8")
    names = {n: fingerprint(n, legacy[n]) for n in ASSETS}
    new = {names[n]: legacy[n] for n in ASSETS}
    boot = boot_script(names["app.js"], integrity(legacy["app.js"]))
    names["start.js"] = fingerprint("start.js", boot)
    new[names["start.js"]] = boot
    for n in ("style.css", "release.css"):
        old = f'<link rel="stylesheet" href="./{n}">'
        tag = f'<link rel="stylesheet" href="./{names[n]}" integrity="{integrity(legacy[n])}" crossorigin="anonymous">'
        if html.count(old) != 1:
            raise ValueError("Unexpected stylesheet entry")
        html = html.replace(old, tag)
    for n, content in (("release.js", legacy["release.js"]), ("start.js", boot)):
        old = f'<script defer src="./{n}"></script>'
        tag = f'<script defer src="./{names[n]}" integrity="{integrity(content)}" crossorigin="anonymous"></script>'
        if html.count(old) != 1:
            raise ValueError("Unexpected script entry")
        html = html.replace(old, tag)
    marker = '<main id="content" tabindex="-1">'
    if html.count(marker) != 1:
        raise ValueError("Unexpected main region")
    html = html.replace(marker, marker + "\n" + BOOT_STATUS)
    html = html.replace("PAGE 02", "PAGE 03")
    html = html.replace("正在校验内置样例…", "正在启动页面；此发布版本不内置市场数据。")
    new["index.html"] = html.encode("utf-8")
    new[".nojekyll"] = b""
    # One bounded compatibility generation, so a cached old index can still boot.
    previous = {n: legacy[n] for n in (*ASSETS, "start.js")}
    new.update(previous)
    manifest = {
        "schema": "ql.public-shell/2", "version": VERSION,
        "market_data_included": False, "personal_data_included": False,
        "entrypoints": names, "compatibility_files": sorted(previous),
        "files": {n: digest(b) for n, b in sorted(new.items())},
    }
    new["release.manifest.json"] = (json.dumps(manifest, indent=2) + "\n").encode()
    return new


def build(source: Path, output: Path) -> dict:
    if output.exists() or output.is_symlink():
        raise ValueError("Output must be a new directory")
    assets = make_candidate(read_legacy(source))
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".pages-candidate-", dir=output.parent))
    try:
        for name, content in assets.items():
            (stage / name).write_bytes(content)
        stage.rename(output)
    finally:
        if stage.exists():
            shutil.rmtree(stage)
    return {"version": VERSION, "files": len(assets), "deployed": False}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        print(json.dumps(build(args.source, args.output), indent=2))
    except (ValueError, OSError, KeyError, TypeError, UnicodeError) as exc:
        parser.exit(2, f"Pages candidate failed: {exc}\n")
