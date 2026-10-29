# -*- coding: utf-8 -*-
"""把 dist/ 下的发布包上传（或覆盖）到指定 GitHub Release。

用法
----
    set GITHUB_TOKEN=xxx
    python packaging/upload_assets.py felix-lius design-patent-views v0.1.0

会覆盖同名资产（先删后传）。
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"


def ctx():
    c = ssl.create_default_context()
    # 某些环境有 TLS 拦截代理，证书链验证会失败
    if os.environ.get("ALLOW_INSECURE_SSL") == "1":
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
    return c


def api(method: str, url: str, token: str, data: bytes = None, ctype: str = "application/json"):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "design-patent-views-releaser")
    if data is not None:
        req.add_header("Content-Type", ctype)
    return urllib.request.urlopen(req, context=ctx(), timeout=300)


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: upload_assets.py <owner> <repo> <tag> [file1 file2 ...]")
        return 2
    owner, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("✗ 缺少 GITHUB_TOKEN")
        return 2

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    dist = os.path.join(base, "dist")

    files = sys.argv[4:] or [
        "design-patent-views-win64.zip",
        "design-patent-views-skill-lite.zip",
    ]

    rel = json.loads(api("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token).read())
    rid = rel["id"]
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    print(f"Release {tag} (id={rid})")
    print(f"现有资产: {', '.join(existing) or '(无)'}")
    print()

    for fname in files:
        path = os.path.join(dist, fname)
        if not os.path.exists(path):
            print(f"✗ 跳过（不存在）: {fname}")
            continue
        size_mb = os.path.getsize(path) / 1048576
        if fname in existing:
            api("DELETE", f"{API}/repos/{owner}/{repo}/releases/assets/{existing[fname]}", token)
            print(f"  已删除旧资产: {fname}")
        blob = open(path, "rb").read()
        print(f"  上传 {fname} ({size_mb:.2f} MB) ...")
        r = api(
            "POST",
            f"{UPLOAD}/repos/{owner}/{repo}/releases/{rid}/assets?name={fname}",
            token, blob, "application/zip",
        )
        a = json.loads(r.read())
        url = a.get("browser_download_url", "")
        print(f"  ✓ {url}")

    print()
    rel2 = json.loads(api("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token).read())
    print("最终资产:")
    for a in rel2["assets"]:
        print(f"  {a['name']:42s} {a['size'] / 1048576:7.2f} MB")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
