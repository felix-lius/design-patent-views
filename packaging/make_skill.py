# -*- coding: utf-8 -*-
"""Skill 包构建脚本 —— 产出一个可直接丢给别的 agent 的技能压缩包

用法
----
    python packaging/make_skill.py --lite    # 轻量版（约 1MB，需目标机 Python 3.12）
    python packaging/make_skill.py --full    # 自包含版（约 92MB，含 patent-cli.exe，无需 Python）
    python packaging/make_skill.py --both

产物
----
    dist/design-patent-views-skill-lite.zip
    dist/design-patent-views-skill-win64.zip

zip 内部结构（单层根目录，解压到技能目录即可）
------------------------------------------------
    design-patent-views/
      ├─ SKILL.md                 技能入口（frontmatter: name/description）
      ├─ 自测清单.md              给接收方 agent 的验收步骤
      ├─ INSTALL.md / README.md / DEVELOPMENT.md / LICENSE.md
      ├─ 中国外观设计专利制图合规规格.md
      ├─ install_deps.py          轻量版依赖安装器
      ├─ scripts/*.py             引擎源码
      ├─ examples/*.step          冒烟测试模型
      ├─ docs/*.png               演示图
      └─ （仅 full）patent-cli.exe + _internal/  自包含运行时

与 packaging/build.py 的区别
---------------------------
build.py 打的是「发布用一键包」（扁平结构，给最终用户）；
本脚本打的是「skill 包」（单层根目录 + 自测清单，给 agent 装载）。
"""
from __future__ import annotations

import os
import shutil
import sys
import zipfile

# 中文 Windows 控制台是 cp936，打印 ✓ 之类字符会 UnicodeEncodeError
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")
STAGE = os.path.join(ROOT, "build", "skill")
PKG_NAME = "design-patent-views"

ZIP_LITE = os.path.join(DIST, "design-patent-views-skill.zip")
ZIP_FULL = os.path.join(DIST, "design-patent-views-skill-win64.zip")

# 两版共有的文件（相对 ROOT）
COMMON_FILES = [
    "SKILL.md",
    "INSTALL.md",
    "README.md",
    "DEVELOPMENT.md",
    "LICENSE.md",
    "中国外观设计专利制图合规规格.md",
    "install_deps.py",
]
# 技能包**只放 .md 和 .py**。
# SkillHub 会逐个校验文件类型，实测拒收过：LICENSE（无扩展名）、examples/*.step。
# 所以示例模型和流程图都不进包，改用 GitHub 绝对地址引用：
#   · 示例模型 → README/自测清单里给下载命令
#   · 流程图   → README 里的链接改写为 raw 地址
EXAMPLES: list[str] = []

# ⚠️ SkillHub 禁止上传二进制文件（PNG/JPG 等），所以技能包里**不放图片**。
# README 里的图片引用会在 patch_readme() 中改写为 GitHub 绝对地址，
# 这样在平台上仍能正常显示，而包内不含二进制。
DOCS = []

# README 里外链的目标前缀。
# 用 jsDelivr 而不是 raw.githubusercontent.com：后者在国内基本不通
# （实测连不上），jsDelivr 有国内节点，平台侧渲染 README 时图片能正常显示。
RAW_BASE = "https://cdn.jsdelivr.net/gh/felix-lius/design-patent-views@main/"
# 打包期附带的自测清单
SELFTEST_SRC = os.path.join(ROOT, "packaging", "自测清单.md")

DOWNLOAD_URL_TOKEN = "<DOWNLOAD_URL>"
DOWNLOAD_URL_REPLACE = "（暂无公开下载地址——请直接用方案 B 装依赖）"


def log(msg: str) -> None:
    print(f"==> {msg}", flush=True)


# 只打包运行必需的脚本；开发/下载工具不进技能包
#   fetch_step / fetch_wheel —— 开发期下载工具，终端用户用不到
#   make_* / make_report_chart —— 生成测试件与验证图表，开发用
_EXCLUDE_SCRIPTS = {
    "fetch_step.py", "fetch_wheel.py",
    "make_powerbank.py", "make_sample.py", "make_report_chart.py",
}


def copy_scripts(dst: str) -> None:
    src_dir = os.path.join(ROOT, "scripts")
    out = os.path.join(dst, "scripts")
    os.makedirs(out, exist_ok=True)
    n = 0
    skipped = []
    for name in sorted(os.listdir(src_dir)):
        if not name.endswith(".py"):
            continue
        if name in _EXCLUDE_SCRIPTS:
            skipped.append(name)
            continue
        shutil.copy2(os.path.join(src_dir, name), out)
        n += 1
    log(f"scripts/  {n} 个 .py（排除 {len(skipped)} 个开发工具）")


def copy_common(dst: str) -> None:
    for rel in COMMON_FILES:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            log(f"⚠ 跳过缺失文件 {rel}")
            continue
        shutil.copy2(src, os.path.join(dst, os.path.basename(rel)))

    for rel in EXAMPLES + DOCS:
        src = os.path.join(ROOT, rel)
        if not os.path.exists(src):
            log(f"⚠ 跳过缺失文件 {rel}")
            continue
        target_dir = os.path.join(dst, os.path.dirname(rel))
        os.makedirs(target_dir, exist_ok=True)
        shutil.copy2(src, target_dir)

    if os.path.exists(SELFTEST_SRC):
        shutil.copy2(SELFTEST_SRC, os.path.join(dst, "自测清单.md"))
    else:
        log("⚠ 缺少 packaging/自测清单.md")


def patch_readme_images(dst: str) -> None:
    """把 README 里的本地文件引用改写为 GitHub 绝对地址。

    原因：SkillHub 会逐个校验包内文件类型，实测拒收过
    LICENSE（无扩展名）和 examples/*.step。所以包里只放 .md / .py，
    图片和流程图一律改成绝对地址引用，在平台上仍能正常显示。
    """
    path = os.path.join(dst, "README.md")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    original = text

    # ![alt](docs/xxx.png) -> ![alt](https://raw.githubusercontent.com/.../docs/xxx.png)
    import re
    text = re.sub(r"\]\((docs/[^)]+)\)", lambda m: f"]({RAW_BASE}{m.group(1)})", text)
    # <img src="docs/xxx.png"> 同理
    text = re.sub(r'src="(docs/[^"]+)"', lambda m: f'src="{RAW_BASE}{m.group(1)}"', text)
    # 根目录下的流程图等本地文件链接（包内不再附带 .svg，改指 GitHub）
    text = re.sub(r"\]\((?!https?://|#|mailto:)([^)/]+\.svg)\)",
                  lambda m: f"]({RAW_BASE}{m.group(1)})", text)

    if text != original:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        log("README 本地引用已改为 GitHub 绝对地址（避免平台拒收）")


def patch_skill_md(dst: str, variant: str) -> None:
    """按包形态调整 SKILL.md 里的安装引导。

    lite 版：保留真实下载地址（用户可另装一键包，也可直接装依赖）
    full 版：本包已自带 patent-cli.exe + _internal/，无需任何下载，
             把「一键包」提示词替换为「已自带」说明，避免 agent 多此一举去下载。
    """
    path = os.path.join(dst, "SKILL.md")
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as f:
        text = f.read()
    original = text

    if variant == "full":
        # 把「帮我装一下…一键包…」整段替换掉
        import re
        text = re.sub(
            r"帮我装一下外观设计专利视图生成工具的一键包：\S+\n\n[^\n]*\n",
            "本包已自带运行环境（patent-cli.exe + _internal/），无需下载、无需安装依赖。\n"
            "直接运行包根目录的 patent-cli.exe 即可。\n",
            text,
        )

    if text != original:
        with open(path, "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        log(f"SKILL.md 已按 {variant} 版调整安装引导")


def copy_exe(dst: str) -> None:
    """full 版：把 dist/patent-cli 的 exe 与 _internal 拷进包根目录"""
    src = os.path.join(DIST, "patent-cli")
    exe = os.path.join(src, "patent-cli.exe")
    internal = os.path.join(src, "_internal")
    if not (os.path.exists(exe) and os.path.isdir(internal)):
        raise SystemExit(
            "✗ 找不到 dist/patent-cli/patent-cli.exe 或 _internal/，"
            "请先运行 python packaging/build.py"
        )
    shutil.copy2(exe, dst)
    shutil.copytree(internal, os.path.join(dst, "_internal"))
    log("patent-cli.exe + _internal/ 已拷入")


def make_zip(dst: str, zip_path: str) -> float:
    if os.path.exists(zip_path):
        os.remove(zip_path)
    os.makedirs(os.path.dirname(zip_path), exist_ok=True)
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for r, _dirs, files in os.walk(dst):
            for f in files:
                full = os.path.join(r, f)
                arc = os.path.join(PKG_NAME, os.path.relpath(full, dst))
                zf.write(full, arc.replace(os.sep, "/"))
    return os.path.getsize(zip_path) / 1048576


def build(variant: str) -> None:
    log(f"构建 {variant} 版")
    shutil.rmtree(STAGE, ignore_errors=True)
    dst = os.path.join(STAGE, variant, PKG_NAME)
    os.makedirs(dst, exist_ok=True)

    copy_common(dst)
    copy_scripts(dst)
    patch_readme_images(dst)
    patch_skill_md(dst, variant)
    if variant == "full":
        copy_exe(dst)

    zip_path = ZIP_FULL if variant == "full" else ZIP_LITE
    mb = make_zip(dst, zip_path)
    log(f"✓ {os.path.basename(zip_path)}  {mb:.1f} MB")


def main() -> int:
    args = [a.lower() for a in sys.argv[1:]]
    if not args:
        args = ["--lite"]
    do_lite = "--both" in args or "--lite" in args
    do_full = "--both" in args or "--full" in args
    if not (do_lite or do_full):
        print(__doc__)
        return 2
    if do_lite:
        build("lite")
    if do_full:
        build("full")
    print(f"\n产物目录：{DIST}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
