#!/usr/bin/env python3
"""Read-only byte-level Pages deployment check; never claims browser acceptance.

The expected directory is a locally reviewed build. The remote manifest is not a
trust root. No credentials, uploads, retries, cross-origin redirects or third-
party calls. On the first failure stop, preserving its exact classification.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import socket
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse, urljoin
from urllib.request import HTTPRedirectHandler, Request, build_opener

LIMIT = 512 * 1024
NAME = re.compile(r"[a-zA-Z0-9][a-zA-Z0-9_.-]*\Z")


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def expected_files(directory: Path) -> dict[str, bytes]:
    if directory.is_symlink() or not directory.is_dir():
        raise ValueError("Expected directory must be an ordinary directory")
    manifest_path = directory / "release.manifest.json"
    if manifest_path.is_symlink():
        raise ValueError("Linked manifest rejected")
    raw = manifest_path.read_bytes()
    if len(raw) > LIMIT:
        raise ValueError("Oversized manifest")
    manifest = json.loads(raw)
    if manifest.get("schema") != "ql.public-shell/2" or not isinstance(manifest.get("files"), dict):
        raise ValueError("Expected a versioned shell manifest")
    if manifest.get("market_data_included") is not False or manifest.get("personal_data_included") is not False:
        raise ValueError("Only the data-free shell is in scope")
    files = manifest["files"]
    if not 3 <= len(files) <= 30 or "index.html" not in files or ".nojekyll" not in files:
        raise ValueError("Invalid file inventory")
    if set(p.name for p in directory.iterdir()) != set(files) | {"release.manifest.json"}:
        raise ValueError("Extra or missing expected files")
    values = {}
    for name, checksum in files.items():
        if name != ".nojekyll" and not NAME.fullmatch(name):
            raise ValueError("Unsafe asset name")
        p = directory / name
        if p.is_symlink() or not p.is_file() or not isinstance(checksum, str) or not re.fullmatch(r"[a-f0-9]{64}", checksum):
            raise ValueError("Invalid local asset")
        content = p.read_bytes()
        if len(content) > LIMIT or hashlib.sha256(content).hexdigest() != checksum:
            raise ValueError("Local build hash mismatch")
        # .nojekyll is a build marker, not a required public HTTP resource.
        if name != ".nojekyll":
            values[name] = content
    values["release.manifest.json"] = raw
    return values


def base_url(url: str, allow_loopback: bool) -> str:
    p = urlparse(url)
    if p.username or p.password or p.query or p.fragment or not p.hostname:
        raise ValueError("Use a credential-free base URL with no query or fragment")
    if p.scheme != "https":
        if not (allow_loopback and p.scheme == "http" and p.hostname in ("127.0.0.1", "localhost", "::1")):
            raise ValueError("HTTPS required; HTTP loopback is only for explicit local tests")
    if ".." in p.path.split("/") or "%" in p.path:
        raise ValueError("Unexpected base path")
    return url.rstrip("/") + "/"


def mime_ok(name: str, mime: str) -> bool:
    if name.endswith(".html"):
        return mime == "text/html"
    if name.endswith(".css"):
        return mime == "text/css"
    if name.endswith(".js"):
        return mime in ("application/javascript", "text/javascript")
    if name.endswith(".json"):
        return mime == "application/json"
    return False


def verify(url: str, directory: Path, *, allow_loopback: bool = False, timeout: float = 8.0) -> dict:
    if not 0 < timeout <= 30:
        raise ValueError("Timeout must be in (0, 30] seconds")
    base = base_url(url, allow_loopback)
    expected = expected_files(directory)
    report = {"schema": "ql.pages-http-check/1", "checked_at": datetime.now(timezone.utc).isoformat(),
              "base_url": base, "http_verified": False, "browser_verified": False,
              "scope": "Exact bytes of reviewed shell and assets; not data freshness or browser behavior",
              "checks": []}
    opener = build_opener(NoRedirect())
    names = ["index.html"] + sorted(n for n in expected if n != "index.html")
    for name in names:
        # Check the actual project URL first, rather than only /index.html.
        target = base if name == "index.html" else urljoin(base, name)
        check = {"file": name, "url": target, "status": "pending"}
        try:
            request = Request(target, headers={"User-Agent": "ql-pages-check/1", "Cache-Control": "no-cache"})
            with opener.open(request, timeout=timeout) as response:
                check["http_status"] = response.status
                check["mime"] = response.headers.get_content_type()
                data = response.read(LIMIT + 1)
            if check["http_status"] != 200:
                check["status"] = "unexpected_http_status"
            elif len(data) > LIMIT:
                check["status"] = "response_too_large"
            elif data != expected[name]:
                check["status"] = "content_mismatch"
                check["expected_sha256"] = hashlib.sha256(expected[name]).hexdigest()
                check["actual_sha256"] = hashlib.sha256(data).hexdigest()
            elif not mime_ok(name, check["mime"]):
                check["status"] = "wrong_content_type"
            else:
                check["status"] = "passed"
                check["sha256"] = hashlib.sha256(data).hexdigest()
        except HTTPError as exc:
            check.update(status="redirect_rejected" if 300 <= exc.code < 400 else "http_error", http_status=exc.code)
        except (URLError, OSError, TimeoutError) as exc:
            reason = getattr(exc, "reason", exc)
            kind = "dns_error" if isinstance(reason, socket.gaierror) else "network_error"
            check.update(status=kind, error_type=type(reason).__name__)
        report["checks"].append(check)
        if check["status"] != "passed":
            report["result"] = check["status"]
            return report
    report.update(http_verified=True, result="passed")
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", required=True)
    parser.add_argument("--expected", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-loopback", action="store_true")
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise ValueError("Report output must be a new path")
        result = verify(args.url, args.expected, allow_loopback=args.allow_loopback)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("x", encoding="utf-8") as out:
            json.dump(result, out, ensure_ascii=False, indent=2)
            out.write("\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        raise SystemExit(0 if result["http_verified"] else 1)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, f"Deployment check failed: {exc}\n")
