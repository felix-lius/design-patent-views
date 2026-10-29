# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置 — 外观设计专利视图生成工具（方案 A 一键包）

用法
----
    pyinstaller --clean --noconfirm packaging/patent_cli.spec

产出
----
    dist/patent-cli/patent-cli.exe   （onedir，约 290MB）

设计说明
--------
* **onedir 而非 onefile**：OCP 有 2000+ 文件、333MB，onefile 每次启动都要
  解压到临时目录（慢 10–20 秒），且更容易被杀软拦。onedir 启动快、体积一样。

* **不做二进制裁剪**（重要教训）：曾尝试剔除 vtk / OpenGL / avif / webp 等
  "看起来只有可视化才用"的 DLL，结果 `import OCP` 直接报
  `DLL load failed`。原因是 OCP 打成单个大 pyd（111MB），这些库是它的
  **静态/延迟加载依赖**，无法从功能上推断取舍。
  实测 292MB 已是可靠下限，硬裁会换来一个跑不起来的包。

* **不能排除 unittest**：ezdxf → pyparsing → unittest 有硬依赖。

* 输出目录：打包后 pipeline.py 会把 output/logs 重定向到
  %LOCALAPPDATA%\\design-patent-views\\，避免往 Program Files 写文件失败。
"""
import os

from PyInstaller.utils.hooks import collect_all

_HERE = os.path.dirname(os.path.abspath(SPEC))
_ROOT = os.path.dirname(_HERE)
_SCRIPTS = os.path.join(_ROOT, "scripts")

# ---- OCP：全量收集（DLL 运行时加载，静态分析不可见）----
ocp_datas, ocp_binaries, ocp_hidden = collect_all("OCP")

# ---- ezdxf：带字体/模板等资源 ----
try:
    ez_datas, ez_binaries, ez_hidden = collect_all("ezdxf")
except Exception:
    ez_datas, ez_binaries, ez_hidden = [], [], []

analysis = Analysis(
    [os.path.join(_SCRIPTS, "patent_cli.py")],
    pathex=[_SCRIPTS],
    binaries=ocp_binaries + ez_binaries,
    datas=ocp_datas + ez_datas + [
        # 随包附带文档，用户解压后能看懂
        (os.path.join(_ROOT, "SKILL.md"), "."),
        (os.path.join(_ROOT, "INSTALL.md"), "."),
        (os.path.join(_ROOT, "README.md"), "."),
        (os.path.join(_ROOT, "LICENSE.md"), "."),
    ],
    hiddenimports=(
        ocp_hidden
        + ez_hidden
        + [
            # 本项目模块（patent_cli 中延迟 import）
            "pipeline", "spec", "geom_core", "render", "dxf_export",
            "step01_parse_validate", "step02_orient", "step03_views",
            "step04_normalize", "step05_compliance_check",
            # 第三方运行时依赖（静态分析容易漏）
            "pyparsing", "pyparsing.testing", "unittest",
            "ezdxf.entities", "ezdxf.queryparser",
        ]
    ),
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        # 未使用的大包（注意：**不要**排除 unittest / pyparsing）
        "matplotlib", "scipy", "pandas", "IPython", "jupyter",
        "notebook", "pytest", "sphinx", "docutils",
        "PyQt5", "PyQt6", "PySide2", "PySide6", "wx",
        "tkinter", "_tkinter",
        "pip", "wheel",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="patent-cli",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,               # UPX 易被杀软误报，关闭
    console=True,            # 命令行工具
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="patent-cli",
)
