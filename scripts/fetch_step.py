# -*- coding: utf-8 -*-
"""稳健下载器：分块 Range 请求 + 逐块校验 + 断点续传。

背景
----
Keychron 的模型服务器（keychron.co:34568）会在传输中途关闭连接，
一次性整包读取会静默拿到半截文件（表现为 STEP 解析报语法错误）。
这里改用 HTTP Range 分段拉取，每段独立重试，最后校验总长度。
"""
from __future__ import annotations

import os
import ssl
import sys
import time
import urllib.request

CHUNK = 512 * 1024
MAX_RETRY = 6


def _ctx():
    c = ssl.create_default_context()
    c.check_hostname = False
    c.verify_mode = ssl.CERT_NONE
    return c


def _head(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}, method="HEAD")
    with urllib.request.urlopen(req, context=_ctx(), timeout=60) as r:
        cl = r.headers.get("Content-Length")
        accept = r.headers.get("Accept-Ranges")
        return (int(cl) if cl else -1, accept)


def _fetch_range(url: str, start: int, end: int) -> bytes:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Range": f"bytes={start}-{end}",
        },
    )
    with urllib.request.urlopen(req, context=_ctx(), timeout=120) as r:
        data = r.read()
    return data


def download(url: str, dest: str, total_hint: int = -1) -> bool:
    t0 = time.time()
    try:
        total, accept = _head(url)
        print(f"HEAD total={total} accept-ranges={accept}", flush=True)
    except Exception as e:
        total = -1
        print(f"HEAD failed: {type(e).__name__}: {e}", flush=True)

    if total <= 0:
        total = total_hint
    if total <= 0:
        print("!! 无法获知文件总长，退回整包下载", flush=True)
        return _plain(url, dest)

    buf = bytearray(total)
    pos = 0
    stall = 0
    while pos < total:
        end = min(pos + CHUNK - 1, total - 1)
        ok = False
        for attempt in range(1, MAX_RETRY + 1):
            try:
                data = _fetch_range(url, pos, end)
                want = end - pos + 1
                if len(data) != want:
                    raise IOError(f"chunk short {len(data)}/{want}")
                buf[pos:pos + len(data)] = data
                pos += len(data)
                ok = True
                stall = 0
                pct = pos * 100.0 / total
                print(f"  {pos}/{total} ({pct:.1f}%)  {time.time()-t0:.0f}s", flush=True)
                break
            except Exception as e:
                wait = min(2 * attempt, 8)
                print(f"  chunk@{pos} attempt{attempt} fail: {type(e).__name__}: {e}; retry in {wait}s", flush=True)
                time.sleep(wait)
        if not ok:
            stall += 1
            if stall >= 3:
                print(f"!! 连续失败，放弃于 {pos}/{total}", flush=True)
                return False

    data = bytes(buf)
    # 完整性粗校验：STEP 文件必须以 END-ISO-10303-21; 结尾
    tail = data[-200:].decode("latin-1", "ignore")
    if "END-ISO-10303-21" not in tail:
        print(f"!! 尾部校验失败，可能仍不完整。tail={tail[-80:]!r}", flush=True)
        return False
    with open(dest, "wb") as f:
        f.write(data)
    print(f"OK {dest} {len(data)} bytes  {time.time()-t0:.0f}s", flush=True)
    return True


def _plain(url: str, dest: str) -> bool:
    for attempt in range(1, 4):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r:
                data = r.read()
            if "END-ISO-10303-21" not in data[-200:].decode("latin-1", "ignore"):
                print(f"  attempt{attempt}: 尾部不完整 ({len(data)} bytes)", flush=True)
                continue
            open(dest, "wb").write(data)
            print(f"OK {dest} {len(data)} bytes", flush=True)
            return True
        except Exception as e:
            print(f"  attempt{attempt} {type(e).__name__}: {e}", flush=True)
    return False


if __name__ == "__main__":
    pairs = [
        (
            "keychron_g9he_mouse.stp",
            "http://www.keychron.co:34568/keychron-github-assets/Keychron-Keyboards-Hardware-Design/Mice/G9%20HE/Keychron_G9_HE_Mouse-20260918.stp",
        ),
        (
            "keychron_m1_mouse.stp",
            "http://www.keychron.co:34568/keychron-github-assets/Keychron-Keyboards-Hardware-Design/Mice/M1/M1-20230525.stp",
        ),
    ]
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(base, "examples")
    ok_all = True
    for fn, url in pairs:
        print(f"===== {fn}", flush=True)
        ok = download(url, os.path.join(out, fn))
        ok_all = ok_all and ok
    sys.exit(0 if ok_all else 1)
