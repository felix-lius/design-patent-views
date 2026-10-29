# -*- coding: utf-8 -*-
"""一键包构建脚本（跨平台，不受 PowerShell 执行策略影响）

用法
----
    python packaging/build.py

它会：
1. 清理旧产物
2. 用 PyInstaller 构建 onedir 包
3. 把示例模型和文档复制到包根目录（用户/agent 可直接跑冒烟测试）
4. 生成发布 zip

为什么需要第 3 步
----------------
PyInstaller 的 datas 会被放进 _internal/，而用户（和 agent）习惯在包根目录
直接跑 `patent-cli.exe auto --step examples\\powerbank.step`，
所以构建后要把 examples/ 和文档复制到根目录。
"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
PKG = os.path.join(DIST, "patent-cli")
BUILD = os.path.join(ROOT, "build")
ZIP = os.path.join(DIST, "design-patent-views-win64.zip")

# 随包放到根目录的文件
ROOT_FILES = ["SKILL.md", "INSTALL.md", "README.md", "DEVELOPMENT.md", "LICENSE"]
# 只带一个最小示例做冒烟测试（powerbank 约 90KB），不带全部测试模型
SMOKE_EXAMPLE = "examples/powerbank.step"


def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


def main() -> int:
    log("清理旧产物")
    # 只删本脚本自己的产物，不要整个清空 dist/
    # （dist/ 里还可能有 make_skill.py 生成的 skill 包）
    shutil.rmtree(BUILD, ignore_errors=True)
    shutil.rmtree(PKG, ignore_errors=True)
    if os.path.exists(ZIP):
        os.remove(ZIP)
    os.makedirs(DIST, exist_ok=True)

    log("PyInstaller 构建")
    py = os.path.join(ROOT, ".venv", "Scripts", "python.exe")
    if not os.path.exists(py):
        py = sys.executable
    cmd = [py, "-m", "PyInstaller", "--clean", "--noconfirm",
           "--distpath", DIST, "--workpath", BUILD,
           os.path.join(ROOT, "packaging", "patent_cli.spec")]
    if subprocess.call(cmd) != 0:
        print("✗ PyInstaller 构建失败", file=sys.stderr)
        return 1

    log("复制示例与文档到包根目录")
    ex_dir = os.path.join(PKG, "examples")
    os.makedirs(ex_dir, exist_ok=True)
    src_ex = os.path.join(ROOT, SMOKE_EXAMPLE)
    if os.path.exists(src_ex):
        shutil.copy2(src_ex, ex_dir)
    for f in ROOT_FILES:
        src = os.path.join(ROOT, f)
        if os.path.exists(src):
            shutil.copy2(src, PKG)

    log("生成发布 zip")
    if os.path.exists(ZIP):
        os.remove(ZIP)
    with zipfile.ZipFile(ZIP, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for r, _dirs, files in os.walk(PKG):
            for f in files:
                full = os.path.join(r, f)
                zf.write(full, os.path.relpath(full, PKG))

    pkg_mb = sum(os.path.getsize(os.path.join(r, f))
                 for r, _d, fs in os.walk(PKG) for f in fs) / 1048576
    zip_mb = os.path.getsize(ZIP) / 1048576
    print(f"\n完成：包 {pkg_mb:.0f} MB / zip {zip_mb:.0f} MB")
    print(f"产物：{ZIP}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
