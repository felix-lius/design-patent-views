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
import time
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"

# Windows 控制台默认 GBK，脚本里的 ✓/✗ 会直接抛 UnicodeEncodeError，
# 而且是在"上传已经成功"之后才崩——看着像失败，其实成功了。
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def ctx():
    c = ssl.create_default_context()
    # 某些环境有 TLS 拦截代理，证书链验证会失败
    if os.environ.get("ALLOW_INSECURE_SSL") == "1":
        c.check_hostname = False
        c.verify_mode = ssl.CERT_NONE
    return c


def api(method: str, url: str, token: str, data: bytes = None, ctype: str = "application/json",
        timeout: int = 300):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "design-patent-views-releaser")
    if data is not None:
        req.add_header("Content-Type", ctype)
    return urllib.request.urlopen(req, context=ctx(), timeout=timeout)


def upload_with_retry(owner: str, repo: str, rid: int, path: str, token: str,
                      attempts: int = 3) -> bool:
    """上传单个资产，失败重试。大文件给足超时（30 分钟）。"""
    name = os.path.basename(path)
    size_mb = os.path.getsize(path) / 1048576
    blob = open(path, "rb").read()
    url = f"{UPLOAD}/repos/{owner}/{repo}/releases/{rid}/assets?name={name}"

    for i in range(1, attempts + 1):
        try:
            print(f"  上传 {name} ({size_mb:.2f} MB) 第 {i}/{attempts} 次 ...", flush=True)
            r = api("POST", url, token, blob, "application/zip", timeout=1800)
            a = json.loads(r.read())
            print(f"  ✓ {a.get('browser_download_url', '')}")
            return True
        except Exception as e:
            print(f"  ✗ 第 {i} 次失败: {type(e).__name__}: {str(e)[:120]}")
            if i < attempts:
                wait = 10 * i
                print(f"    等待 {wait}s 后重试 ...", flush=True)
                time.sleep(wait)
                # 清理可能残留的半个资产
                try:
                    rel = json.loads(api("GET", f"{API}/repos/{owner}/{repo}/releases/{rid}", token).read())
                    for a in rel.get("assets", []):
                        if a["name"] == name:
                            api("DELETE", f"{API}/repos/{owner}/{repo}/releases/assets/{a['id']}", token)
                            print("    已清理残留资产")
                except Exception:
                    pass
    return False


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
        # 小文件优先——先确保轻量包就位，再传大包
        "design-patent-views-skill-lite.zip",
        "design-patent-views-win64.zip",
    ]

    rel = json.loads(api("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token).read())
    rid = rel["id"]
    existing = {a["name"]: a["id"] for a in rel.get("assets", [])}
    print(f"Release {tag} (id={rid})")
    print(f"现有资产: {', '.join(existing) or '(无)'}")
    print()

    failed = []
    for fname in files:
        path = os.path.join(dist, fname)
        if not os.path.exists(path):
            print(f"✗ 跳过（不存在）: {fname}")
            continue
        if fname in existing:
            api("DELETE", f"{API}/repos/{owner}/{repo}/releases/assets/{existing[fname]}", token)
            print(f"  已删除旧资产: {fname}")
        if not upload_with_retry(owner, repo, rid, path, token):
            failed.append(fname)

    print()
    rel2 = json.loads(api("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token).read())
    print("最终资产:")
    for a in rel2["assets"]:
        print(f"  {a['name']:42s} {a['size'] / 1048576:7.2f} MB")

    if failed:
        print(f"\n✗ 上传失败: {', '.join(failed)}")
        print("  可单独重试：python packaging/upload_assets.py "
              f"{owner} {repo} {tag} {' '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
