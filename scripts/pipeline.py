# -*- coding: utf-8 -*-
"""链路公共工具：路径约定、config 载入、日志读写。

输出根目录（可配置）
--------------------
默认值：
  · 源码运行 → 仓库根目录（保持原有行为）
  · 打包运行 → 当前工作目录（exe 所在目录常为只读，不能往那里写）

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

if _FROZEN:
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    _DEFAULT_ROOT = os.getcwd()
    DIR_EXAMPLES = os.path.join(_exe_dir, "examples")     # 只读：随包资源
    _INPUT_BASE = os.getcwd()
else:
    _SRC_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    _DEFAULT_ROOT = _SRC_BASE
    DIR_EXAMPLES = os.path.join(_SRC_BASE, "examples")
    _INPUT_BASE = _SRC_BASE

OUTPUT_ROOT = _DEFAULT_ROOT
OUTPUT_ROOT_SOURCE = "default"      # arg / env / config / default

DIR_INPUT = os.path.join(_INPUT_BASE, "input")
DIR_OUTPUT = os.path.join(OUTPUT_ROOT, "output")
DIR_LOGS = os.path.join(OUTPUT_ROOT, "logs")


def _ensure_dirs() -> None:
    for _d in (DIR_INPUT, DIR_OUTPUT, DIR_LOGS):
        try:
            os.makedirs(_d, exist_ok=True)
        except OSError:
            pass


_ensure_dirs()


def set_output_root(path: str, source: str = "arg") -> str:
    """切换输出根目录（运行时生效），返回规范化后的绝对路径。"""
    global OUTPUT_ROOT, OUTPUT_ROOT_SOURCE, DIR_OUTPUT, DIR_LOGS
    OUTPUT_ROOT = os.path.abspath(path)
    OUTPUT_ROOT_SOURCE = source
    DIR_OUTPUT = os.path.join(OUTPUT_ROOT, "output")
    DIR_LOGS = os.path.join(OUTPUT_ROOT, "logs")
    _ensure_dirs()
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

    return set_output_root(_DEFAULT_ROOT, "default"), "default"


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
    1. cfg 中的 step_file（patent-cli 写入）
    2. examples/ 或 input/ 下同名 .step / .stp
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
