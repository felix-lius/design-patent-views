# -*- coding: utf-8 -*-
"""删除 GitHub Release 上指定名称的资产。

用法
----
    set GITHUB_TOKEN=xxx
    python packaging/delete_asset.py felix-lius design-patent-views v0.1.0 design-patent-views-skill-lite.zip
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 5:
        print("usage: delete_asset.py <owner> <repo> <tag> <asset_name>")
        return 2
    owner, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]
    target = sys.argv[4]
    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("✗ 缺少 GITHUB_TOKEN")
        return 2

    ctx = ssl.create_default_context()
    if os.environ.get("ALLOW_INSECURE_SSL") == "1":
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    def api(method, url, data=None):
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Bearer {token}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", "asset-deleter")
        return urllib.request.urlopen(req, context=ctx, timeout=30)

    rel = json.loads(api("GET", f"https://api.github.com/repos/{owner}/{repo}/releases/tags/{tag}").read())
    deleted = False
    for a in rel.get("assets", []):
        if a["name"] == target:
            api("DELETE", f"https://api.github.com/repos/{owner}/{repo}/releases/assets/{a['id']}")
            print(f"✓ 已删除: {a['name']}")
            deleted = True
        else:
            print(f"  保留: {a['name']}  ({a['size'] / 1048576:.2f} MB)")
    if not deleted:
        print(f"未找到名为 {target} 的资产")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
