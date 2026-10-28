# -*- coding: utf-8 -*-
"""创建 GitHub Release 并上传发布包。

用法
----
    set GITHUB_TOKEN=<token>
    python packaging/create_release.py felix-lius design-patent-views v0.1.0

token 从环境变量读，不落盘、不回显。
"""
from __future__ import annotations

import json
import os
import ssl
import sys
import urllib.request

API = "https://api.github.com"
UPLOAD = "https://uploads.github.com"

RELEASE_NOTES = """## 外观设计专利视图生成工具 v0.1.0

从 STEP 三维模型自动生成中国外观设计专利所需的**六视图 + 立体图 + JPEG 提交件 + 可编辑 DXF**，
全程本地运行，模型不上传。

### 核心能力

- **精确几何投影** —— OpenCascade HLR 隐藏线消除（与 FreeCAD TechDraw 同款算法），不是 AI 生成
- **合规规格固化** —— 150×220mm @300DPI = 1772×2598px，符合 CNIPA 要求
- **33 项合规自检** —— 格式 / 线条 / 视图 / 清晰度 / 文书五类自动核查
- **原生 DXF** —— 导出 `ARC`/`CIRCLE`/`LINE` 实体，可在 CAD 中直接编辑
- **一句话出图** —— `auto` 命令自动引导方位确认与实体筛选

### 下载

| 文件 | 大小 | 说明 |
|---|---|---|
| `design-patent-views-win64.zip` | 92 MB | **一键包**，解压即用，不需要 Python |

解压后约 292 MB，直接运行 `patent-cli.exe`。

轻量版（需要 Python 3.12）不需要下载包，克隆仓库后运行 `python install_deps.py` 即可。

### 安装方式

两种方式都只需要复制一段话给 AI agent，详见 [README](https://github.com/felix-lius/design-patent-views#安装)。

### 验证情况

已用 **9 个真实产品模型**验证，覆盖 6 个品类（移动电源、蓝牙音箱、游戏手柄、3D 鼠标、鼠标外壳、薄壁壳体），
合规自检全部 0 失败。

### 已知限制

- 仅支持 Windows x64
- 输入几何必须有效（破面/自交会导致 HLR 丢线，工具会告警但无法修复）
- 装配体需人工筛选外观件
- 产品朝向需人工确认（CAD 坐标轴常与实际朝向不一致）

### 许可证

MIT + Commons Clause —— 自用、商用（自己的业务）都可以，但**不能把本工具本身拿去卖**。
"""


def _ctx():
    """SSL 上下文。

    某些环境（企业代理 / 本地 TLS 拦截代理）会导致证书链验证失败
    （unable to get issuer certificate）。设置环境变量 ALLOW_INSECURE_SSL=1
    可跳过验证——仅用于向 GitHub 上传本仓库自己的发布包，风险可控。
    """
    if os.environ.get("ALLOW_INSECURE_SSL") == "1":
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx
    return ssl.create_default_context()


def api(method: str, url: str, token: str, data: bytes = None, ctype: str = "application/json"):
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", "design-patent-views-release")
    if data is not None:
        req.add_header("Content-Type", ctype)
    return urllib.request.urlopen(req, context=_ctx(), timeout=120)


def main() -> int:
    if len(sys.argv) < 4:
        print("usage: create_release.py <owner> <repo> <tag>")
        return 2
    owner, repo, tag = sys.argv[1], sys.argv[2], sys.argv[3]

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    if not token:
        print("✗ 缺少环境变量 GITHUB_TOKEN")
        return 2

    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    asset = os.path.join(base, "dist", "design-patent-views-win64.zip")
    if not os.path.exists(asset):
        print(f"✗ 找不到发布包：{asset}")
        return 1
    size_mb = os.path.getsize(asset) / 1048576

    # 1. 创建（或复用）release
    payload = json.dumps({
        "tag_name": tag,
        "name": f"v{tag.lstrip('v')}",
        "body": RELEASE_NOTES,
        "draft": False,
        "prerelease": False,
    }).encode()
    print(f"创建 Release {tag} ...")
    try:
        r = api("POST", f"{API}/repos/{owner}/{repo}/releases", token, payload)
        rel = json.loads(r.read())
        print(f"  ✓ Release 已创建 (id={rel['id']})")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        if e.code == 422 and "already_exists" in body:
            print("  Release 已存在，复用")
            r = api("GET", f"{API}/repos/{owner}/{repo}/releases/tags/{tag}", token)
            rel = json.loads(r.read())
        else:
            print(f"  ✗ 创建失败 HTTP {e.code}: {body[:300]}")
            return 1

    # 2. 上传资产
    name = os.path.basename(asset)
    print(f"上传 {name} ({size_mb:.0f} MB) ...")
    with open(asset, "rb") as f:
        blob = f.read()
    try:
        r = api(
            "POST",
            f"{UPLOAD}/repos/{owner}/{repo}/releases/{rel['id']}/assets?name={name}",
            token, blob, "application/zip",
        )
        a = json.loads(r.read())
        print(f"  ✓ 上传完成：{a['browser_download_url']}")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "ignore")
        print(f"  ✗ 上传失败 HTTP {e.code}: {body[:300]}")
        return 1

    print(f"\n完成：https://github.com/{owner}/{repo}/releases/tag/{tag}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
