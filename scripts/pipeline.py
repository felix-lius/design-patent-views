# -*- coding: utf-8 -*-
"""链路公共工具：路径约定、config 载入、日志读写。"""
from __future__ import annotations

import json
import os
import sys
from typing import Any, Dict

# 打包成 exe 后（PyInstaller onedir），exe 所在目录通常是只读的
# （如 Program Files），不能往那里写 output/logs。
# 因此：
#   · 源码运行  → 仓库根目录（保持原有行为）
#   · 打包运行  → 当前工作目录（调用方可控，沙箱内也可写）
#     可用环境变量 PATENT_OUT_DIR 覆盖。
_FROZEN = getattr(sys, "frozen", False)

if _FROZEN:
    _exe_dir = os.path.dirname(os.path.abspath(sys.executable))
    BASE = os.environ.get("PATENT_OUT_DIR") or os.getcwd()
    DIR_EXAMPLES = os.path.join(_exe_dir, "examples")     # 只读：随包资源
else:
    BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DIR_EXAMPLES = os.path.join(BASE, "examples")

DIR_INPUT = os.path.join(BASE, "input")
DIR_OUTPUT = os.path.join(BASE, "output")
DIR_LOGS = os.path.join(BASE, "logs")

for _d in (DIR_INPUT, DIR_OUTPUT, DIR_LOGS):
    try:
        os.makedirs(_d, exist_ok=True)
    except OSError:
        pass


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
