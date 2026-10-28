# -*- coding: utf-8 -*-
"""外观专利六视图工具 — 轻量版依赖安装（方案 B）

核心原则：**先检测，只装缺的。**

用法
----
    python install_deps.py            # 检测 → 只安装缺失的依赖
    python install_deps.py --check    # 只检测，不安装
    python install_deps.py --mirror pypi   # 换官方 PyPI 源
    python install_deps.py --force-ocp     # 强制重装 OCP

它做什么
--------
1. 逐项检测：Python 版本、OCP、Pillow、ezdxf、numpy
2. 打印检测结果（哪些已有、哪些缺）
3. 全部就绪 → 直接退出，什么都不装
4. 有缺失 → **只安装缺失的那几项**
5. 装完再验证一遍

为什么不用 `pip install cadquery-ocp`
------------------------------------
实测某些 Windows 环境 pip 会因临时目录权限失败
（PermissionError: pip-unpack-*.whl）。本脚本用 urllib 直连下载
wheel 后再 `pip install --no-index --no-deps <本地wheel>`，更稳。
"""
from __future__ import annotations

import argparse
import os
import re
import ssl
import subprocess
import sys
import urllib.request

# ---------------------------------------------------------------- 配置
OCP_PKG = "cadquery-ocp"
OCP_VERSION = "7.7.2"          # 零依赖版本（8.x 会拉 vtk）
PY_MIN = (3, 10)
PY_REC = "3.12"

# 需要检测的 Python 包：(显示名, import 名, pip 名)
SIMPLE_DEPS = [
    ("Pillow", "PIL", "Pillow"),
    ("ezdxf", "ezdxf", "ezdxf"),
    ("numpy", "numpy", "numpy"),
]

MIRRORS = {
    "tuna": "https://pypi.tuna.tsinghua.edu.cn/simple",
    "pypi": "https://pypi.org/simple",
}

HERE = os.path.dirname(os.path.abspath(__file__))
WHEEL_DIR = os.path.join(HERE, ".wheels")


def _ctx():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def _tag() -> str:
    """当前平台的 wheel tag，如 cp312-cp312-win_amd64。"""
    ver = f"cp{sys.version_info.major}{sys.version_info.minor}"
    if sys.platform == "win32":
        plat = "win_amd64" if sys.maxsize > 2**32 else "win32"
    elif sys.platform == "darwin":
        plat = "macosx_11_0_arm64" if "arm" in os.uname().machine else "macosx_10_9_x86_64"
    else:
        plat = "manylinux2014_x86_64"
    return f"{ver}-{ver}-{plat}"


# ---------------------------------------------------------------- 检测
def detect_all() -> dict:
    """检测全部依赖，返回 {名称: {"ok": bool, "version": str|None}}。"""
    st = {}

    pv = sys.version_info
    st["Python"] = {
        "ok": (pv.major, pv.minor) >= PY_MIN,
        "version": f"{pv.major}.{pv.minor}.{pv.micro}",
        "note": "" if (pv.major, pv.minor) >= PY_MIN else f"需要 {PY_REC}（至少 {PY_MIN[0]}.{PY_MIN[1]}）",
    }

    for disp, mod, _pip in [("OCP", "OCP", OCP_PKG)] + SIMPLE_DEPS:
        try:
            m = __import__(mod)
            st[disp] = {"ok": True, "version": str(getattr(m, "__version__", "已安装")), "note": ""}
        except Exception:
            st[disp] = {"ok": False, "version": None, "note": "未安装"}
    return st


def print_status(st: dict) -> None:
    print("依赖检测：")
    for name, info in st.items():
        mark = "✓" if info["ok"] else "✗"
        ver = f"({info['version']})" if info["version"] else ""
        tail = f"  ← {info['note']}" if info["note"] else ""
        print(f"  {mark} {name:10s} {ver}{tail}")


# ---------------------------------------------------------------- 安装
def _download(url: str, dest: str) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "pip/26"})
    with urllib.request.urlopen(req, context=_ctx(), timeout=180) as r, open(dest, "wb") as f:
        total, last = 0, 0
        while True:
            chunk = r.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            total += len(chunk)
            if total - last >= 20 << 20:
                last = total
                print(f"      {total / 1048576:.0f} MB", flush=True)


def fetch_ocp_wheel(mirror: str) -> str:
    """从镜像索引里挑出匹配当前平台的 OCP wheel 并下载。"""
    os.makedirs(WHEEL_DIR, exist_ok=True)
    index = f"{MIRRORS[mirror]}/{OCP_PKG}/"
    print(f"  索引: {index}")

    req = urllib.request.Request(index, headers={"User-Agent": "pip/26"})
    html = urllib.request.urlopen(req, context=_ctx(), timeout=60).read().decode("utf-8", "ignore")

    links = [p.split('"')[0] for p in html.split('href="')[1:]]
    links = [l for l in links if ".whl" in l]

    tag = _tag()
    cands = [l for l in links if tag in l and OCP_VERSION in l]
    if not cands:
        cands = [l for l in links if tag in l]
    if not cands:
        raise RuntimeError(
            f"镜像里找不到匹配 {tag} 的 {OCP_PKG} wheel。\n"
            f"当前 Python {sys.version.split()[0]}，请改用 Python {PY_REC}。"
        )

    def ver_key(link: str):
        m = re.search(r"-(\d+\.\d+\.\d+)-", link)
        return tuple(int(x) for x in m.group(1).split(".")) if m else (0,)

    cands.sort(key=ver_key)
    url = cands[-1]
    if url.startswith("../"):
        url = f"{MIRRORS[mirror]}/{OCP_PKG}/" + url
    elif url.startswith("/"):
        url = MIRRORS[mirror].rsplit("/simple", 1)[0] + url

    fn = url.split("#")[0].split("/")[-1]
    dest = os.path.join(WHEEL_DIR, fn)
    if os.path.exists(dest) and os.path.getsize(dest) > 10 << 20:
        print(f"  已缓存: {fn} ({os.path.getsize(dest) / 1048576:.0f} MB)")
        return dest

    print(f"  下载: {fn}")
    _download(url, dest)
    print(f"  完成: {os.path.getsize(dest) / 1048576:.0f} MB")
    return dest


def pip_available() -> bool:
    try:
        return subprocess.call(
            [sys.executable, "-m", "pip", "--version"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        ) == 0
    except Exception:
        return False


def pip_install(args: list[str], mirror: str) -> bool:
    cmd = [sys.executable, "-m", "pip", "install"] + args
    if mirror != "pypi":
        cmd += ["-i", MIRRORS[mirror] + "/"]
    print("  $", " ".join(cmd[2:]))
    return subprocess.call(cmd) == 0


# ---------------------------------------------------------------- 主流程
def main() -> int:
    ap = argparse.ArgumentParser(description="外观专利六视图工具 — 依赖安装（只装缺的）")
    ap.add_argument("--check", action="store_true", help="只检测，不安装")
    ap.add_argument("--mirror", default="tuna", choices=list(MIRRORS), help="PyPI 镜像")
    ap.add_argument("--force-ocp", action="store_true", help="强制重装 OCP")
    args = ap.parse_args()

    print("=" * 56)
    print(" 外观专利六视图工具 — 依赖安装")
    print("=" * 56)
    print(f"Python: {sys.version.split()[0]}  ({sys.executable})")
    print(f"平台  : {sys.platform} / {_tag()}")
    print()

    # ---- 1. 检测 ----
    st = detect_all()
    if args.force_ocp:
        st["OCP"] = {"ok": False, "version": None, "note": "强制重装"}
    print_status(st)

    missing = [n for n, v in st.items() if not v["ok"]]
    if not missing:
        print("\n✓ 全部依赖已就绪，无需安装。")
        return 0

    if args.check:
        print(f"\n✗ 缺少 {len(missing)} 项：{', '.join(missing)}")
        print("  运行 python install_deps.py 安装")
        return 1

    # ---- 2. Python 版本不对：无法自动修 ----
    if "Python" in missing:
        print(f"\n✗ Python 版本不满足要求（当前 {st['Python']['version']}，需要 {PY_REC}）。")
        print("\n请先安装 Python 3.12：https://www.python.org/downloads/")
        print("（安装时勾选「Add Python to PATH」）")
        print("\n或者改用「一键包」版本，它自带运行时，不需要 Python。")
        return 1

    # ---- 3. 检查 pip ----
    if not pip_available():
        print("\n✗ 当前 Python 没有可用的 pip，无法安装依赖。")
        print("\n修复方式（任选其一）：")
        print(f"  1. {sys.executable} -m ensurepip --upgrade")
        print("  2. 下载 get-pip.py 后运行：python get-pip.py")
        print("  3. 重新安装 Python，勾选「Add Python to PATH」和 pip")
        print("\n或者改用「一键包」版本（自带运行时，不需要 Python 和 pip）。")
        return 1

    # ---- 4. 只装缺的 ----
    print(f"\n需要安装 {len(missing)} 项：{', '.join(missing)}")

    if "OCP" in missing:
        print("\n[1] OCP（几何内核，约 91MB）")
        try:
            whl = fetch_ocp_wheel(args.mirror)
        except Exception as e:
            print(f"\n✗ OCP 下载失败: {e}")
            print(f"\n手动安装：pip install {OCP_PKG}=={OCP_VERSION}")
            return 1
        if not pip_install(["--no-index", "--no-deps", whl], args.mirror):
            print("\n✗ OCP 安装失败")
            return 1

    simple_missing = [pip for disp, _mod, pip in SIMPLE_DEPS if disp in missing]
    if simple_missing:
        print(f"\n[2] {' / '.join(simple_missing)}")
        if not pip_install(simple_missing, args.mirror):
            print("\n✗ 依赖安装失败")
            return 1

    # ---- 5. 复验 ----
    print("\n复验...")
    st2 = detect_all()
    print_status(st2)
    still = [n for n, v in st2.items() if not v["ok"]]
    if still:
        print(f"\n✗ 仍有 {len(still)} 项不可用：{', '.join(still)}")
        return 1

    print("\n" + "=" * 56)
    print(" ✓ 安装完成")
    print("=" * 56)
    print(f"\n下一步：python {os.path.join(HERE, 'scripts', 'patent_cli.py')} auto --step <模型.step>")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
