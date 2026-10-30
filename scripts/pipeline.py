# -*- coding: utf-8 -*-
"""链路公共工具：路径约定、config 载入、日志读写。

输出根目录（可配置）
--------------------
默认值：**桌面「外观专利视图」文件夹**。打包版与源码版（轻量版）行为一致——
用户在哪种形态下用，出完图都应该一眼能看到。桌面不可写时退回当前工作目录。

开发/批量跑想落到仓库里，用 `--out-dir` 或 `PATENT_OUT_DIR` 显式指定（优先级更高）。
（v1.0 的旧行为是"源码运行落在仓库根目录"，导致轻量版用户永远看不到桌面默认目录，
  与 SKILL.md 的承诺不符，已修正。）

用户可用三种方式改：
  1. 命令行 `--out-dir <路径>`     —— 只对这一次生效
  2. 环境变量 `PATENT_OUT_DIR`     —— 只对这个进程生效
  3. `patent-cli config --out-dir` —— **持久化**，以后一直用它

优先级：--out-dir > PATENT_OUT_DIR > 持久化配置 > 默认值。
实际用了哪个，由 resolve_output_root() 返回，写进 JSON 报告，便于排查。

注意：只有 output/ 与 logs/ 跟着输出根目录走；input/ 始终留在程序目录，
因为它是每次运行的临时 config，跟着搬会让 --config 的相对路径失效。
"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict, Optional, Tuple

import userconfig

# 打包成 exe 后（PyInstaller onedir），exe 所在目录通常是只读的
# （如 Program Files），不能往那里写 output/logs。
_FROZEN = getattr(sys, "frozen", False)

DESKTOP_FOLDER_NAME = "外观专利视图"


def desktop_dir() -> Optional[str]:
    """拿真正的桌面路径（Windows 上可能是被 OneDrive 重定向过的那个）。"""
    if os.name == "nt":
        try:
            import winreg
            key = r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders"
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key) as k:
                v, _ = winreg.QueryValueEx(k, "Desktop")
            v = os.path.expandvars(str(v))
            if v and os.path.isdir(v):
                return v
        except (OSError, ImportError, ValueError):
            pass
    for name in ("Desktop", "桌面"):
        p = os.path.join(os.path.expanduser("~"), name)
        if os.path.isdir(p):
            return p
    return None


def default_root() -> str:
    """默认输出根：桌面「外观专利视图」文件夹；取不到桌面就退回当前工作目录。

    **纯路径计算，不建目录、不写探测文件**：没得到用户确认（选模式/选目录）
    之前，磁盘上不该出现任何东西。可写性检查推迟到 resolve_output_root()。
    """
    d = desktop_dir()
    if d:
        return os.path.join(d, DESKTOP_FOLDER_NAME)
    return os.getcwd()


# 兼容旧名字
_pick_default_root = default_root


def _root_writable(path: str) -> bool:
    """目录能建、能写就 True（会顺手建出来——只在真要往这里落盘时调用）。"""
    try:
        os.makedirs(path, exist_ok=True)
        probe = os.path.join(path, ".patent_write_probe")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
        return True
    except OSError:
        return False


if _FROZEN:
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    DIR_EXAMPLES = os.path.join(_exe_dir, "examples")     # 只读：随包资源
    _INPUT_BASE = os.getcwd()
else:
    _SRC_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DIR_EXAMPLES = os.path.join(_SRC_BASE, "examples")
    _INPUT_BASE = _SRC_BASE

# 默认输出根：**打包版和轻量版（源码运行）一致，都用桌面**。
# v1.0 的旧行为是"源码运行落在仓库根目录"，结果轻量版用户按 SKILL.md 去桌面找图
# 永远找不到——文档与实现不一致，属于硬伤，已修正。
_DEFAULT_ROOT = default_root()

OUTPUT_ROOT = _DEFAULT_ROOT
OUTPUT_ROOT_SOURCE = "default"      # arg / env / config / default
# 默认根（桌面）不可写、被迫退回当前目录时置 True，好让上层如实告诉用户
DEFAULT_ROOT_FELL_BACK = False

DIR_INPUT = os.path.join(_INPUT_BASE, "input")
DIR_OUTPUT = os.path.join(OUTPUT_ROOT, "output")
DIR_LOGS = os.path.join(OUTPUT_ROOT, "logs")


def default_root_note(path: str) -> Optional[str]:
    """默认目录踩到云同步盘时给一句提醒。

    外观设计在申请日前是未公开的，图被 OneDrive 之类同步上去，
    等于把未公开设计交给了第三方服务器——这和本工具「全程本地」的定位冲突。
    """
    low = path.lower()
    for cloud in ("onedrive", "dropbox", "google drive", "icloud", "坚果云", "百度网盘"):
        if cloud in low:
            return (f"当前默认目录位于云同步盘（{cloud}），"
                    f"出图会自动上传到云端。未公开的外观设计建议改到本地目录："
                    f"patent-cli config --out-dir \"D:/专利出图\"")
    return None


def ensure_dirs() -> None:
    """按需创建 input/ output/ logs/。

    **刻意不在 import 阶段调用**：一 import 就建目录，会让"还没得到用户确认"
    的那次调用也在磁盘上留下痕迹（实测：连 `--help` 都在技能目录里建出了
    output/ 与 logs/）。现在由真正要写文件的步骤显式调用，没确认就一个字节不落盘。
    """
    for _d in (DIR_INPUT, DIR_OUTPUT, DIR_LOGS):
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            pass


# 兼容旧名字（外部脚本/旧代码可能引用 _ensure_dirs）
_ensure_dirs = ensure_dirs


def set_output_root(path: str, source: str = "arg") -> str:
    """切换输出根目录（运行时生效），返回规范化后的绝对路径。

    只改路径，**不建目录**——建目录由 ensure_dirs()/具体写盘步骤负责。
    """
    global OUTPUT_ROOT, OUTPUT_ROOT_SOURCE, DIR_OUTPUT, DIR_LOGS
    OUTPUT_ROOT = os.path.abspath(path)
    OUTPUT_ROOT_SOURCE = source
    DIR_OUTPUT = os.path.join(OUTPUT_ROOT, "output")
    DIR_LOGS = os.path.join(OUTPUT_ROOT, "logs")
    return OUTPUT_ROOT


def resolve_output_root(cli_value: Optional[str] = None) -> Tuple[str, str]:
    """按优先级定输出根目录，返回 (路径, 来源)。"""
    if cli_value:
        return set_output_root(cli_value, "arg"), "arg"

    env = os.environ.get("PATENT_OUT_DIR")
    if env and env.strip():
        return set_output_root(env.strip(), "env"), "env"

    saved = userconfig.get_out_dir()
    if saved:
        # 配置里的目录可能已被用户删除/移动，仍照用（会自动重建），
        # 但如果它变成了一个文件，就退回默认，避免整条链路崩掉。
        if not os.path.exists(saved) or os.path.isdir(saved):
            return set_output_root(saved, "config"), "config"

    root = _DEFAULT_ROOT
    if not _root_writable(root):
        # 受管机器上桌面可能不可写：退回当前工作目录，功能不能因此失效。
        # 但要留痕——否则用户又该问"说好的桌面呢"。
        global DEFAULT_ROOT_FELL_BACK
        DEFAULT_ROOT_FELL_BACK = True
        root = os.getcwd()
        _root_writable(root)
    return set_output_root(root, "default"), "default"


def config_path(name: str) -> str:
    return os.path.join(DIR_INPUT, f"{name}.json")


def step_log_path(step: str, name: str) -> str:
    return os.path.join(DIR_LOGS, f"{step}_{name}.json")


def load_config(name: str) -> Dict[str, Any]:
    path = config_path(name)
    with open(path, encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("product_name", name)
    cfg.setdefault("design_mode", "overall")
    cfg.setdefault("front_axis", "+Y")
    cfg.setdefault("up_axis", "+Z")
    cfg.setdefault("views", ["front", "back", "left", "right", "top", "bottom", "iso"])
    cfg.setdefault("omit", [])
    cfg.setdefault("iso", {"azimuth_deg": 45.0, "elevation_deg": 35.264})
    cfg.setdefault("render", {"line_width_mm": 0.35, "supersample": 2})
    return cfg


def step_path(name: str, cfg: Dict[str, Any] = None) -> str:
    """定位 STEP 模型文件。

    优先级：
    1. cfg 中的 step_file（patent-cli 写入）    2. examples/ 或 input/ 下同名 .step / .stp
    """
    if cfg and cfg.get("step_file"):
        p = cfg["step_file"]
        if os.path.exists(p):
            return p

    for d in (DIR_EXAMPLES, DIR_INPUT):
        for ext in (".step", ".stp"):
            p = os.path.join(d, f"{name}{ext}")
            if os.path.exists(p):
                return p
    raise FileNotFoundError(
        f"找不到 {name}.step / .stp（已查 examples/ 与 input/）"
    )


def write_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def read_json(path: str) -> Any:
    with open(path, encoding="utf-8") as f:
        return json.load(f)


# ---------------------------------------------------------------- 目录分配
MODEL_META_NAME = "model.json"


def _norm(p: str) -> str:
    return os.path.normcase(os.path.abspath(p))


def model_source_of(name: str) -> Optional[str]:
    """查 output/<name>/ 是哪个 STEP 生成的。查不到返回 None。

    先看 model.json（新版会写），再退回 01 日志（旧目录只有日志）。
    """
    try:
        d = read_json(os.path.join(DIR_OUTPUT, name, MODEL_META_NAME))
        p = d.get("step_file")
        if p:
            return _norm(p)
    except (OSError, ValueError):
        pass
    try:
        d = read_json(os.path.join(DIR_LOGS, f"01_{name}.json"))
        p = d.get("step_file")
        if p:
            return _norm(p)
    except (OSError, ValueError):
        pass
    return None


def resolve_run_name(name: str, step_file: Optional[str]) -> str:
    """给这次运行分配输出目录名，保证**不同模型绝不互相覆盖**。

    规则：
      · 目录不存在                → 用原名字
      · 目录已存在，且来自同一个 STEP → 复用（同一模型重跑，本来就该覆盖旧结果）
      · 目录已存在，但来自另一个 STEP → 依次试 <名字>-2、<名字>-3 ……

    这样两个都叫 model.step 的文件（放在不同文件夹里）不会打架。
    """
    src = _norm(step_file) if step_file else None
    candidate = name
    n = 1
    while os.path.isdir(os.path.join(DIR_OUTPUT, candidate)):
        if src and model_source_of(candidate) == src:
            return candidate
        n += 1
        candidate = f"{name}-{n}"
        if n > 999:
            import time
            return f"{name}-{int(time.time())}"
    return candidate


def write_model_meta(name: str, step_file: Optional[str],
                     product_name: Optional[str] = None) -> None:
    """在 output/<name>/ 里留个来源标记，下次据此判断该不该复用目录。"""
    if not step_file:
        return
    try:
        write_json(os.path.join(DIR_OUTPUT, name, MODEL_META_NAME), {
            "step_file": os.path.abspath(step_file),
            "product_name": product_name,
        })
    except OSError:
        pass
