# -*- coding: utf-8 -*-
"""patent-cli — 外观设计专利视图生成工具的统一命令行入口。

设计原则
--------
1. 统一 --config <json>，不做一堆位置参数（agent 拼位置参数极易出错）
2. stdout 只输出一个 JSON（agent 好解析）
3. 明确退出码：
     0  成功
     2  需要用户输入（返回 need 字段，agent 转成对话）
     3  输入错误（config / STEP 文件问题）
     4  引擎错误（几何/渲染异常）
4. 需要用户决策时不失败，返回 {"ok":false,"need":"...","options":[...]}
5. 幂等：同 config 重跑结果一致

用法
----
    patent-cli analyze  --config job.json
    patent-cli render   --config job.json
    patent-cli dxf      --config job.json
    patent-cli check    --config job.json
    patent-cli run      --config job.json      # 全流程

job.json 示例
-------------
    {
      "step_file": "examples/mouse_shell.step",
      "product_name": "蓝牙鼠标",
      "front_axis": "+Y",
      "up_axis": "+Z"
    }

其中 step_file 可以是相对路径（相对于 job.json 所在目录）或绝对路径。
省略的字段使用默认值（与 input/*.json 的格式完全兼容）。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import traceback

# ezdxf 需要一个可写的缓存目录，否则会打印警告（不影响功能，但会干扰 agent 解析 JSON）
os.environ.setdefault("XDG_CACHE_HOME", os.path.join(os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))), ".cache"))

# 统一 stdout/stderr 为 UTF-8：打包成 exe 后默认会跟随控制台代码页（中文 Windows 是 cp936），
# 导致中文输出乱码、agent 解析失败。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 确保能 import 同目录下的模块
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, _SCRIPT_DIR)

import pipeline as pl
import spec


# ============================================================ 退出码
EXIT_OK = 0
EXIT_NEED_INPUT = 2
EXIT_INPUT_ERROR = 3
EXIT_ENGINE_ERROR = 4

# ============================================================ 出图模式
# 用户一开始就要在两者之间选一个，**没有默认值**：不给 --mode 就返回 need。
MODE_ONE_SHOT = "one_shot"     # 一键式：方位按规则自动判定，不再询问
MODE_CUSTOM = "custom"         # 自定义：主视图/上方向/外观件/导出目录逐项确认
MODES = (MODE_ONE_SHOT, MODE_CUSTOM)

# ============================================================ config 解析
def load_job(config_path: str) -> dict:
    """从 job.json 加载配置，合并默认值，解析 step_file 路径。"""
    if not os.path.exists(config_path):
        raise FileNotFoundError(f"config 文件不存在：{config_path}")

    with open(config_path, encoding="utf-8-sig") as f:
        cfg = json.load(f)

    # 解析 step_file
    step_file = cfg.get("step_file", "")
    if not step_file:
        # 兼容旧格式：用 config 文件名（而非 product_name）在 examples/ 和 input/ 里找
        name = os.path.splitext(os.path.basename(config_path))[0]
        try:
            step_file = pl.step_path(name)
        except FileNotFoundError:
            raise FileNotFoundError(
                f"config 中未指定 step_file，且在 examples/ 和 input/ 下找不到 {name}.step"
            )
    else:
        # 相对路径相对于 config 文件所在目录解析
        if not os.path.isabs(step_file):
            step_file = os.path.join(os.path.dirname(os.path.abspath(config_path)), step_file)
        if not os.path.exists(step_file):
            raise FileNotFoundError(f"step_file 不存在：{step_file}")

    cfg["step_file"] = os.path.abspath(step_file)
    # _name 决定 output/ 与 logs/ 的目录名：
    #   优先用 product_name（需为文件名安全字符），否则回退到 config 文件名。
    # 这样 agent 用临时 job.json 时不会让多个任务输出到同一个 output/job/。
    stem = os.path.splitext(os.path.basename(config_path))[0]
    pn = str(cfg.get("product_name") or "").strip()
    safe = "".join(ch for ch in pn if ch.isalnum() or ch in "-_") if pn else ""
    cfg["_name"] = safe if safe and safe.isascii() else stem
    cfg.setdefault("product_name", cfg["_name"])

    # 必须在 setdefault 之前判断——否则默认值一填，就永远判定为"用户已指定"
    _had_front = "front_axis" in cfg
    _had_up = "up_axis" in cfg

    cfg.setdefault("design_mode", "overall")
    cfg.setdefault("front_axis", "+Y")
    cfg.setdefault("up_axis", "+Z")
    cfg.setdefault("views", ["front", "back", "left", "right", "top", "bottom", "iso"])
    cfg.setdefault("omit", [])
    cfg.setdefault("iso", {"azimuth_deg": 45.0, "elevation_deg": 35.264})
    cfg.setdefault("render", {"line_width_mm": 0.35, "supersample": 2})
    cfg["_front_explicit"] = _had_front
    cfg["_up_explicit"] = _had_up
    cfg.setdefault("hlr_mode", "composite")
    cfg.setdefault("verify_outline", False)
    cfg.setdefault("solids_filtered", False)
    return cfg


# ============================================================ 子命令

def write_runtime_config(cfg: dict, name: str) -> str:
    """把配置写到 input/<name>.json 供 step01-05 读取。

    两条铁律：
    1. 剥离以下划线开头的内部字段（_name / _front_explicit 等），否则会把
       内部状态写回用户的配置文件，污染它。
    2. **与已有文件合并，不整体覆盖**。用 --step 跑一个已有产品时，cfg 里
       只有几何相关字段，直接覆盖会丢掉用户手写的 purpose / brief
       （设计要点、最佳视图），那是"简要说明"的原料，丢了很严重。
    """
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    path = pl.config_path(name)

    existing = {}
    if os.path.exists(path):
        try:
            d = pl.read_json(path)
            if isinstance(d, dict):
                existing = d
        except (OSError, ValueError):
            existing = {}

    # 产品名是从文件名自动推出来的，别让它盖掉用户写好的中文名
    if cfg.get("_product_name_auto") and existing.get("product_name"):
        clean.pop("product_name", None)

    existing.update(clean)
    pl.write_json(path, existing)
    return path



def cmd_analyze(cfg: dict) -> dict:
    """分析模型：实体清单、尺寸、BRepCheck 有效性、建议方位。"""
    import geom_core as geom
    from OCP.BRepCheck import BRepCheck_Analyzer

    sh = geom.load_model(cfg["step_file"])
    stats = geom.shape_stats(sh)
    valid = geom.is_valid(sh)
    bb = geom.bbox3d(sh)
    size = tuple(round(bb[1][i] - bb[0][i], 1) for i in range(3))

    # 实体级有效性
    invalid_solids = []
    sols = geom.split_solids(sh)
    if 1 < len(sols) <= 250:
        for idx, s in enumerate(sols):
            try:
                if not BRepCheck_Analyzer(s).IsValid():
                    invalid_solids.append(idx)
            except Exception:
                pass

    # 方位建议（从包围盒推断）
    suggestions = {}
    dims = list(size)
    longest = dims.index(max(dims))
    shortest = dims.index(min(dims))
    axis_names = ["X", "Y", "Z"]
    suggestions["likely_length_axis"] = f"+{axis_names[longest]}"
    suggestions["likely_height_axis"] = f"+{axis_names[shortest]}"
    suggestions["note"] = "自动推断仅供参考，请根据产品实际朝向确认 front_axis 和 up_axis"

    return {
        "ok": True,
        "action": "analyze",
        "model": {
            "step_file": cfg["step_file"],
            "solids": stats["solids"],
            "faces": stats["faces"],
            "edges": stats["edges"],
            "valid": valid,
            "invalid_solids": invalid_solids,
            "size_mm": {"x": size[0], "y": size[1], "z": size[2]},
            "bbox_min": [round(v, 2) for v in bb[0]],
            "bbox_max": [round(v, 2) for v in bb[1]],
        },
        "orientation_suggestion": suggestions,
    }


def cmd_render(cfg: dict) -> dict:
    """出六视图 + 立体图 + JPEG 提交件。"""
    import step01_parse_validate as s01
    import step02_orient as s02
    import step03_views as s03
    import step04_normalize as s04

    name = cfg["_name"]

    # 把 cfg 写成 input/<name>.json 供 step01-04 使用
    write_runtime_config(cfg, name)

    rep01 = s01.run(name)
    pl.write_json(pl.step_log_path("01", name), rep01)
    if not rep01["ok"]:
        return {"ok": False, "action": "render", "error": "step01 failed",
                "errors": rep01["errors"], "warnings": rep01["warnings"]}

    rep02 = s02.run(name)
    pl.write_json(pl.step_log_path("02", name), rep02)
    if not rep02["ok"]:
        return {"ok": False, "action": "render", "error": "step02 failed",
                "warnings": rep02["warnings"]}

    rep03 = s03.run(name)
    pl.write_json(pl.step_log_path("03", name), rep03)

    rep04 = s04.run(name)
    pl.write_json(pl.step_log_path("04", name), rep04)

    return {
        "ok": True,
        "action": "render",
        "product": name,
        "views": [o["view"] for o in rep03["outputs"]],
        "outputs": {
            "raw_dir": os.path.join(pl.DIR_OUTPUT, name, "raw"),
            "sheet_first_angle": os.path.join(pl.DIR_OUTPUT, name, "sheet_first_angle.png"),
            "sheet_grid": os.path.join(pl.DIR_OUTPUT, name, "sheet_grid.png"),
            "contact_sheet": os.path.join(pl.DIR_OUTPUT, name, "contact_sheet.png"),
            "submission_dir": os.path.join(pl.DIR_OUTPUT, name, "submission"),
            "submission_files": [i["file"] for i in rep04["items"]],
            "total_mb": round(rep04["total_mb"], 3),
        },
        "logs": {
            "01": pl.step_log_path("01", name),
            "02": pl.step_log_path("02", name),
            "03": pl.step_log_path("03", name),
            "04": pl.step_log_path("04", name),
        },
    }


def cmd_dxf(cfg: dict) -> dict:
    """导出 DXF（可编辑矢量，1:1 mm）。"""
    import step01_parse_validate as s01
    import step02_orient as s02
    import step03_views as s03
    import dxf_export

    name = cfg["_name"]
    write_runtime_config(cfg, name)

    # 确保 02 已跑
    rep02_path = pl.step_log_path("02", name)
    if not os.path.exists(rep02_path):
        rep01 = s01.run(name)
        pl.write_json(pl.step_log_path("01", name), rep01)
        rep02 = s02.run(name)
        pl.write_json(rep02_path, rep02)
    else:
        rep02 = pl.read_json(rep02_path)

    rep03 = s03.run(name)
    pl.write_json(pl.step_log_path("03", name), rep03)

    dxf_path = os.path.join(pl.DIR_OUTPUT, name, "all_views.dxf")
    views = {}
    for v, d in rep02["views"].items():
        views[v] = {
            "primitives": d["primitives"],
            "polylines": d["polylines"],
            "bbox": d["bbox"],
            "size": d["size"],
            "scale": d.get("scale", rep02["uniform_scale_px_per_mm"]),
        }

    dxf_export.export_all_views(name, views, dxf_path, dpi=spec.DPI)

    return {
        "ok": True,
        "action": "dxf",
        "product": name,
        "dxf_file": dxf_path,
        "drawing_extent_mm": getattr(dxf_export, "_last_extent", None),
    }


def cmd_check(cfg: dict) -> dict:
    """合规自检（33 项）。缺前置步骤时自动补跑 ①→④。"""
    import step05_compliance_check as s05

    name = cfg["_name"]

    # 自检要读 01~04 的日志；若还没跑过，先补跑出图流程
    if not os.path.exists(pl.step_log_path("04", name)):
        r = cmd_render(cfg)
        if not r.get("ok"):
            return r

    rep05 = s05.run(name)
    pl.write_json(pl.step_log_path("05", name), rep05)

    return {
        "ok": rep05["ok"],
        "action": "check",
        "product": name,
        "summary": rep05["summary"],
        "total_items": rep05["total_items"],
        "items": rep05["items"],
        "report_file": pl.step_log_path("05", name),
    }


def cmd_run(cfg: dict, analyzed: dict = None) -> dict:
    """全流程：分析 → 出图 → DXF → 自检。

    analyzed: 已经分析过的模型结果（一键式/自定义里都先分析过了），
              传进来避免对同一个 STEP 重复跑一遍 BRepCheck（大装配体很贵）。
    """
    name = cfg["_name"]

    # 1. analyze
    model = analyzed if analyzed is not None else cmd_analyze(cfg)["model"]

    # 如果多实体未筛选，返回 need（让 agent 问用户）
    if model["solids"] > 1 and not cfg.get("solids_filtered"):
        return {
            "ok": False,
            "need": "solid_selection",
            "action": "run",
            "product": name,
            "analyze": model,
            "message": f"模型含 {model['solids']} 个实体（装配体）。"
                       f"外观专利通常只保留外观件，建议用 extract_solids.py 筛选后重试。"
                       f"如确认要全量出图，请在 config 中设置 \"solids_filtered\": true。",
            "options": [
                {"label": "全量出图", "value": "all", "hint": "设置 solids_filtered=true 后重试"},
                {"label": "筛选外观件", "value": "filter", "hint": "用 extract_solids.py keep <step> <ids> <out>"},
            ],
            "forbidden": "禁止在用户答复前自行加 --solids-filtered。",
        }

    # 2. render
    r_render = cmd_render(cfg)
    if not r_render.get("ok"):
        return r_render

    # 3. dxf
    r_dxf = cmd_dxf(cfg)

    # 4. check
    r_check = cmd_check(cfg)

    return {
        "ok": r_check.get("ok"),
        "action": "run",
        "product": name,
        "analyze": model,
        "render": r_render.get("outputs"),
        "dxf": r_dxf.get("dxf_file"),
        "check": {
            "summary": r_check["summary"],
            "total_items": r_check["total_items"],
            "report_file": r_check["report_file"],
        },
    }


# ============================================================ 首次体验（P4）

# 六个候选朝向：正面方向 → 该方向的默认"上"
_PREVIEW_DIRS = [
    ("+X", (1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ("-X", (-1.0, 0.0, 0.0), (0.0, 0.0, 1.0)),
    ("+Y", (0.0, 1.0, 0.0), (0.0, 0.0, 1.0)),
    ("-Y", (0.0, -1.0, 0.0), (0.0, 0.0, 1.0)),
    ("+Z", (0.0, 0.0, 1.0), (0.0, 1.0, 0.0)),
    ("-Z", (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
]

# 轴值 ↔ 人话映射：用户在 HTML 上看到的是人话，不用理解 +X / -Y 这种坐标术语。
# 主视图 6 个方向用"从哪个方向看产品"来描述：
_AXIS_LABELS_CN = {
    "+X": "右侧",    "-X": "左侧",
    "+Y": "正面",    "-Y": "背面",
    "+Z": "顶部",    "-Z": "底部",
}
# 上方向 4 个候选用"产品怎么摆"来描述：
_UP_LABELS_CN = {
    ("+Z", "+X"): "正着摆",   ("+Z", "-X"): "正着摆",
    ("-Z", "+X"): "倒着摆",   ("-Z", "-X"): "倒着摆",
    ("+Y", "+X"): "左倾",     ("+Y", "-X"): "左倾",
    ("-Y", "+X"): "右倾",     ("-Y", "-X"): "右倾",
    # front=±X 时 up 候选是 ±Y/±Z
    ("+Z", "+Y"): "正着摆",   ("+Z", "-Y"): "正着摆",
    ("-Z", "+Y"): "倒着摆",   ("-Z", "-Y"): "倒着摆",
    ("+X", "+Y"): "右倾",     ("+X", "-Y"): "右倾",
    ("-X", "+Y"): "左倾",     ("-X", "-Y"): "左倾",
    # front=±Z 时 up 候选是 ±X/±Y
    ("+Y", "+X"): "正着摆",   ("+Y", "-X"): "正着摆",
    ("-Y", "+X"): "倒着摆",   ("-Y", "-X"): "倒着摆",
    ("+X", "+Y"): "右倾",     ("-X", "+Y"): "左倾",
}


def _up_label_cn(front: str, up: str) -> str:
    """给定主视图和上方向，返回人话描述（正着摆/倒着摆/左倾/右倾）。"""
    # 简化逻辑：上方向的正半轴 = 正着/右倾，负半轴 = 倒着/左倾
    # 具体取决于哪个轴
    f = _axis_letter(front)
    u = _axis_letter(up)
    u_sign = "+" if up.strip().startswith("+") else "-"
    if u == "Z":
        return "正着摆" if u_sign == "+" else "倒着摆"
    # up 在水平面内（X 或 Y），表示产品倾斜了
    # 正半轴向右、负半轴向左（近似）
    if f == "X" and u == "Y":
        return "右倾" if u_sign == "+" else "左倾"
    if f == "Y" and u == "X":
        return "右倾" if u_sign == "+" else "左倾"
    return "正着摆" if u_sign == "+" else "倒着摆"


def build_cfg_from_step(step_path: str, product_name: str = None,
                        front: str = None, up: str = None) -> dict:
    """不写 config 文件，直接从 STEP 路径构造一份运行配置。

    这是「用户丢一个 STEP 进来说句话就能出图」的关键：
    agent 不必手写 JSON，只要传 --step。
    """
    if not os.path.exists(step_path):
        raise FileNotFoundError(f"STEP 文件不存在：{step_path}")

    stem = os.path.splitext(os.path.basename(step_path))[0]
    raw_name = product_name or stem
    safe = "".join(ch for ch in raw_name if ch.isalnum() or ch in "-_")
    name = safe if safe and safe.isascii() else stem
    safe_stem = "".join(ch for ch in stem if ch.isalnum() or ch in "-_") or "model"

    cfg = {
        "step_file": os.path.abspath(step_path),
        "product_name": raw_name,
        "_name": name if name.isascii() else safe_stem,
        "design_mode": "overall",
        "front_axis": front or "+Y",
        "up_axis": up or "+Z",
        "views": ["front", "back", "left", "right", "top", "bottom", "iso"],
        "omit": [],
        "iso": {"azimuth_deg": 45.0, "elevation_deg": 35.264},
        "render": {"line_width_mm": 0.35, "supersample": 2},
        "hlr_mode": "composite",
        "verify_outline": False,
        "solids_filtered": False,
        # 标记：方位是否由用户明确指定（未指定则先引导确认）
        "_front_explicit": bool(front),
        "_up_explicit": bool(up),
        # 产品名是不是从文件名自动推出来的（是的话不该覆盖用户手写的中文名）
        "_product_name_auto": not bool(product_name),
    }
    return cfg


def _axis_letter(axis: str) -> str:
    return axis.strip().upper().lstrip("+-")


def default_up_for(front: str) -> str:
    """给定主视图方向，返回默认上方向。

    主视图是 ±Z 时，上方向取 +Y；否则取 +Z。
    """
    return "+Y" if _axis_letter(front) == "Z" else "+Z"


def perpendicular_axes(front: str) -> list:
    """返回垂直于 front 的 4 个方向（候选上方向）。"""
    f = _axis_letter(front)
    if f == "X":
        return ["+Y", "-Y", "+Z", "-Z"]
    if f == "Y":
        return ["+X", "-X", "+Z", "-Z"]
    return ["+X", "-X", "+Y", "-Y"]


def make_orientation_previews(cfg: dict, kind: str = "front", front: str = None,
                              target_px: int = 420, errors: list = None) -> list:
    """渲染方位候选缩略图。

    kind="front" : 6 个候选主视图方向（±X/±Y/±Z）
    kind="up"    : 4 个候选上方向（垂直于给定 front）

    errors: 传入一个 list 时，把每个方向的失败原因收集进去。**空列表是有意义的信号**
            （渲染/落盘失败），调用方必须当错误处理——否则 agent 拿到
            previews=[] 就没法问用户，只能自己猜，正是我们要堵的那条路。
    """
    import geom_core as geom
    from PIL import Image, ImageDraw

    shape = geom.load_model(cfg["step_file"])
    out_dir = os.path.join(pl.DIR_OUTPUT, cfg["_name"], "orientation")
    os.makedirs(out_dir, exist_ok=True)

    # 组装待渲染的 (标签, 视线方向, 上方向)
    jobs = []
    if kind == "up" and front:
        for up_axis in perpendicular_axes(front):
            d = tuple(geom.AXIS_VECTORS[front])
            u = tuple(geom.AXIS_VECTORS[up_axis])
            jobs.append((f"main={front} up={up_axis}", d, u, up_axis))
    else:
        for axis_name, d, u in _PREVIEW_DIRS:
            jobs.append((f"MAIN = {axis_name}", d, u, axis_name))

    results = []
    for label, d, u, axis in jobs:
        try:
            _prims, polys = geom.project_visible_full(shape, d, u, deflection=0.2)
            if not polys:
                if errors is not None:
                    errors.append(f"{axis}: 该方向没有可见轮廓")
                continue
            bb = geom.polyline_bbox(polys)
            w = max(bb[2] - bb[0], 1e-6)
            h = max(bb[3] - bb[1], 1e-6)
            pad = 36
            scale = (target_px - pad * 2) / max(w, h)

            img = Image.new("RGB", (target_px, target_px), "white")
            dr = ImageDraw.Draw(img)
            ox = (target_px - w * scale) / 2 - bb[0] * scale
            oy = (target_px - h * scale) / 2 + bb[3] * scale   # y 轴翻转
            lw = max(1, int(round(scale * 0.6)))
            for poly in polys:
                pts = [(x * scale + ox, -y * scale + oy) for x, y in poly]
                if len(pts) >= 2:
                    dr.line(pts, fill="black", width=lw, joint="curve")
            dr.text((8, 6), label, fill="black")

            safe = axis.replace("+", "p").replace("-", "n")
            prefix = "up" if kind == "up" else "main"
            path = os.path.join(out_dir, f"{prefix}_{safe}.png")
            img.save(path, "PNG")
            results.append({"axis": axis, "file": path, "label": label, "size_px": target_px})
        except Exception as e:
            if errors is not None:
                errors.append(f"{axis}: {type(e).__name__}: {e}")
            continue
    return results


def _img_to_base64(path: str) -> str:
    """读图片文件转 base64 data URI（内嵌进 HTML，双击即开不依赖外部文件）。"""
    import base64
    with open(path, "rb") as f:
        data = base64.b64encode(f.read()).decode("ascii")
    return f"data:image/png;base64,{data}"


def make_selection_html(cfg: dict, previews: list, kind: str,
                        front: str = None, step_file: str = None) -> str:
    """生成自包含的 HTML 选择页面（内嵌 base64 缩略图 + 人话标注 + 点击生成命令）。

    用户双击打开这个 HTML 就能看到所有候选视角，点击选中的那张图，
    页面底部自动显示出对应的命令，用户复制给 agent 即可。
    全程不出现 +X / -Y 这种坐标术语。
    """
    out_dir = os.path.join(pl.DIR_OUTPUT, cfg["_name"], "orientation")
    os.makedirs(out_dir, exist_ok=True)

    if kind == "front":
        page_name = "select_main_view.html"
        title = "选主视图 —— 从哪个方向看过去是产品的「正面」？"
        intro = ("主视图就是专利六视图里排第一张的那个面——"
                 "产品正常摆放时，你站在正前方看到的那一面。"
                 "点击下面最像「正面」的那张图。")
        default_hint = "不确定就选「正面」，通常没错。"
    else:
        page_name = "select_up_axis.html"
        title = f"产品怎么摆？ —— 主视图已选定，现在确认摆放方向"
        intro = ("同一个正面，产品可以正着摆、倒着摆、左倾、右倾。"
                 "选一个最自然的摆法——它决定俯视图和仰视图哪个在上。")
        default_hint = "不确定就选「正着摆」，通常没错。"

    # 构建 HTML 卡片
    cards_html = []
    for p in previews:
        axis = p["axis"]
        img_b64 = _img_to_base64(p["file"])
        if kind == "front":
            label_cn = _AXIS_LABELS_CN.get(axis, axis)
            command = (f'patent-cli auto --step "{step_file}" '
                       f'--mode custom --front {axis}')
        else:
            label_cn = _up_label_cn(front, axis)
            command = (f'patent-cli auto --step "{step_file}" '
                       f'--mode custom --front {front} --up {axis}')
        # 转义命令里的引号给 JS 用
        cmd_js = command.replace('"', '&quot;')
        cards_html.append(f'''
        <div class="card" onclick="selectCard(this, '{cmd_js}')">
          <img src="{img_b64}" alt="{label_cn}" />
          <div class="label">{label_cn}</div>
        </div>''')

    cards = "\n".join(cards_html)

    html = f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, "Microsoft YaHei", sans-serif;
          background: #f5f5f5; color: #333; padding: 24px; }}
  h1 {{ font-size: 20px; margin-bottom: 8px; }}
  .intro {{ font-size: 14px; color: #666; margin-bottom: 20px; line-height: 1.6; }}
  .grid {{ display: flex; flex-wrap: wrap; gap: 16px; }}
  .card {{ background: #fff; border: 3px solid #ddd; border-radius: 8px;
           padding: 8px; cursor: pointer; text-align: center;
           transition: all 0.15s; width: 200px; }}
  .card:hover {{ border-color: #4a90d9; transform: translateY(-2px); }}
  .card.selected {{ border-color: #2ecc71; background: #eafaf1; }}
  .card img {{ width: 180px; height: 180px; object-fit: contain; display: block;
              margin: 0 auto 8px; }}
  .card .label {{ font-size: 16px; font-weight: 600; }}
  .hint {{ margin-top: 20px; font-size: 14px; color: #999; }}
  .result {{ display: none; margin-top: 24px; padding: 16px 20px;
            background: #fff; border: 2px solid #2ecc71; border-radius: 8px; }}
  .result.show {{ display: block; }}
  .result-label {{ font-size: 14px; color: #666; margin-bottom: 8px; }}
  .result-cmd {{ font-family: "Cascadia Code", "Consolas", monospace; font-size: 14px;
                background: #f0f0f0; padding: 12px; border-radius: 4px;
                word-break: break-all; line-height: 1.5; }}
  .copy-btn {{ margin-top: 8px; padding: 6px 16px; font-size: 14px;
              background: #4a90d9; color: #fff; border: none; border-radius: 4px;
              cursor: pointer; }}
  .copy-btn:hover {{ background: #357abd; }}
</style>
</head>
<body>
  <h1>{title}</h1>
  <p class="intro">{intro}</p>
  <div class="grid">{cards}</div>
  <p class="hint">{default_hint}</p>
  <div class="result" id="result">
    <div class="result-label">✅ 你选好了。把下面这行命令复制给你的 AI 助手：</div>
    <div class="result-cmd" id="cmd"></div>
    <button class="copy-btn" onclick="copyCmd()">复制命令</button>
  </div>
<script>
  function selectCard(card, cmd) {{
    document.querySelectorAll('.card').forEach(c => c.classList.remove('selected'));
    card.classList.add('selected');
    var el = document.getElementById('cmd');
    el.textContent = cmd;
    document.getElementById('result').classList.add('show');
  }}
  function copyCmd() {{
    var text = document.getElementById('cmd').textContent;
    navigator.clipboard.writeText(text).then(function() {{
      alert('已复制！粘贴给你的 AI 助手即可。');
    }});
  }}
</script>
</body>
</html>"""

    html_path = os.path.join(out_dir, page_name)
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)
    return html_path


# ------------------------------------------------------------ 一键式方位规则

def auto_axes_by_bbox(model: dict) -> tuple:
    """一键式的方位规则：**写死在代码里，可复现、可解释**，不交给 agent 裁量。

    规则：
      · 上方向 = +Z（CAD 惯例：Z 轴朝上建模）
      · 主视图 = 水平两轴（X / Y）中较长者的正方向；并列取 +X

    已知局限（必须如实告知用户）：产品若不是 Z 轴朝上建模，或正面在 -X / -Y 一侧，
    一键式会判偏。所以一键式的交付里必须写明"判了什么、依据是什么、怎么改"。
    """
    size = model.get("size_mm") or {}
    dims = [float(size.get(k) or 0.0) for k in ("x", "y", "z")]
    axes = ["X", "Y", "Z"]
    front_i = max((0, 1), key=lambda i: (dims[i], -i))      # 并列时取 +X
    front, up = f"+{axes[front_i]}", "+Z"
    reason = (f"上方向取 +Z（CAD 惯例：Z 轴朝上建模）；"
              f"主视图取水平两轴中较长者 = {front}"
              f"（X={dims[0]:g}mm / Y={dims[1]:g}mm / Z={dims[2]:g}mm）")
    return front, up, reason


def need_mode_result(cfg: dict) -> dict:
    """出图方式未定 → 必须问用户。没有默认值，也不允许 agent 代选。"""
    return {
        "ok": False,
        "need": "mode",
        "action": "auto",
        "product": cfg.get("_name"),
        "step_file": cfg.get("step_file"),
        "message": (
            "出图方式还没定，**必须先问用户**（这一步没有默认值，不能替他选）。\n"
            "把下面两个选项原样给用户，拿到答复后再继续：\n"
            "  A 一键式：不再打断。主视图/上方向按包围盒规则自动判定，图直接出到默认目录。"
            "代价：主视图若与产品实际摆放不一致，附图会有形式缺陷，需要重出。\n"
            "  B 自定义：多花 1–2 分钟。先给 6 张候选主视图让用户挑，再确认上方向、"
            "外观件范围，以及这次图存到哪个文件夹。"
        ),
        "options": [
            {"label": "A 一键式（自动判定方位，不再询问）", "value": MODE_ONE_SHOT,
             "hint": "适合批量试样、内部预审；方位判错需重出"},
            {"label": "B 自定义（逐项确认）", "value": MODE_CUSTOM,
             "hint": "适合正式递交、不对称产品、多零件装配体"},
        ],
        "how_to_continue": (
            "拿到用户答复后按他的选择调用（**不要自己选**）：\n"
            f"  patent-cli auto --step <同一文件> --mode {MODE_ONE_SHOT}\n"
            f"  patent-cli auto --step <同一文件> --mode {MODE_CUSTOM}"
        ),
        "forbidden": "禁止在用户没答复的情况下自行选择模式；也禁止跳过本步直接 run。",
    }


def need_out_dir_result(cfg: dict) -> dict:
    """自定义模式下第一次出图 → 问一次导出目录（问过就记住，之后不再问）。"""
    opts = []
    desk = pl.desktop_dir()
    if desk:
        p = os.path.join(desk, pl.DESKTOP_FOLDER_NAME)
        opts.append({"label": f"桌面「{pl.DESKTOP_FOLDER_NAME}」（推荐）", "value": p,
                     "hint": "选它就固定存这里，以后不再问"})
    opts.append({"label": "当前文件夹", "value": os.getcwd(),
                 "hint": "图会落在当前工作目录下"})
    opts.append({"label": "我来指定一个文件夹", "value": None,
                 "hint": "让用户说路径，例如 D:\\专利出图"})
    return {
        "ok": False,
        "need": "out_dir",
        "action": "auto",
        "stage": "out_dir",
        "product": cfg.get("_name"),
        "step_file": cfg.get("step_file"),
        "message": (
            "这是这台机器第一次出图，导出位置还没定过。"
            "问用户图想存哪个文件夹——**只问这一次**，选定后会永久记住。"
        ),
        "options": opts,
        "how_to_continue": (
            "拿到用户答复后先把它记住（下次不再问）：\n"
            "  patent-cli config --out-dir \"<选定路径>\"\n"
            f"然后重跑：patent-cli auto --step <同一文件> --mode {MODE_CUSTOM}"
        ),
        "forbidden": "禁止在用户没答复时自行决定导出目录，也不要用 --out-dir 临时绕过。",
    }


def _preview_failed_result(cfg: dict, what: str, errors: list) -> dict:
    """方位预览图一张都没渲染出来 → 明确报错。

    以前这里是"静默返回空列表"，agent 拿到 previews=[] + options=[] 就问不了用户，
    只能自己猜方位——正是本次事故的同类通道，所以必须当成硬错误。
    """
    return {
        "ok": False,
        "error": f"{what}预览图一张都没生成，无法让用户指认方位。",
        "details": (errors or [])[:6],
        "product": cfg.get("_name"),
        "hint": ("常见原因：导出目录不可写（用 --out-dir 或 config --out-dir 指定可写目录），"
                 "或模型几何异常（先跑 analyze 看 valid / solids）。"),
        "forbidden": "禁止在拿不到预览图时自行推断方位——修好预览，或改用 --mode one_shot。",
    }


def cmd_auto(cfg: dict) -> dict:
    """一步出图，但**出图方式与方位必须先由用户确认**。

    两种模式（用户一开始就要选，没有默认值）：
      one_shot 一键式 —— 方位按 auto_axes_by_bbox() 的规则判定，不再询问
      custom   自定义 —— 导出目录（首次）→ 主视图 → 上方向 → 外观件，逐项确认
    """
    name = cfg["_name"]
    mode = cfg.get("_mode")

    # ---- 0. 出图方式未定 → 必须问用户（没有默认值）----
    if not mode:
        return need_mode_result(cfg)
    if mode not in MODES:
        return {"ok": False, "error": f"未知出图模式：{mode}",
                "hint": f"--mode 只能是 {MODES[0]} 或 {MODES[1]}"}

    # ======================================================== 一键式
    if mode == MODE_ONE_SHOT:
        # 一键式的语义是"方位由规则判定"，因此不接受调用方指定方位——
        # 否则 agent 可以一边声称一键式、一边自己填 --front，等于绕开用户确认。
        if cfg.get("_front_explicit") or cfg.get("_up_explicit"):
            return {
                "ok": False,
                "input_error": True,
                "error": "一键式（--mode one_shot）不接受 --front / --up：方位由规则自动判定。",
                "hint": (f"想让用户自己定方位，请改用 --mode {MODE_CUSTOM} 逐项确认；"
                         "否则去掉 --front / --up 重跑。"),
            }

        r_analyze = cmd_analyze(cfg)
        model = r_analyze["model"]
        front, up, reason = auto_axes_by_bbox(model)
        cfg["front_axis"], cfg["up_axis"] = front, up
        cfg["solids_filtered"] = True          # 一键式不做实体筛选（无法自动判断内部件）
        cfg["_orientation_source"] = "auto_rule"
        cfg["_orientation_user_confirmed"] = False
        cfg["_orientation_rule"] = reason

        warnings = []
        if model["solids"] > 1:
            warnings.append(
                f"模型含 {model['solids']} 个实体，一键式按全量出图处理。"
                f"若其中含 PCB/螺丝/支架等内部结构，附图会不合格——"
                f"请改用 --mode {MODE_CUSTOM} 筛选外观件。"
            )
        if not model["valid"]:
            warnings.append(
                "模型 BRepCheck 判定无效"
                + (f"（{len(model.get('invalid_solids') or [])} 个实体有问题）"
                   if model.get("invalid_solids") else "")
                + "。无效几何可能导致附图丢线，出图后请人工检查外轮廓是否闭合。"
            )

        r_run = cmd_run(cfg, analyzed=model)
        r_run["mode"] = MODE_ONE_SHOT
        if not r_run.get("ok"):
            return r_run

        r_run["orientation"] = {
            "front_axis": front, "up_axis": up,
            "source": "auto_rule", "rule": reason, "user_confirmed": False,
        }
        if warnings:
            r_run.setdefault("warnings", []).extend(warnings)
        r_run["must_tell_user"] = (
            f"一键式：主视图按规则判定为 {front}、上方向 {up}（依据：{reason}）。"
            f"若与产品实际摆放不一致，说一句就重出（约 40 秒）。"
            + ("另：" + "；".join(warnings) if warnings else "")
        )
        return r_run

    # ======================================================== 自定义
    # ---- 1. 主视图方向未确认 → 给 6 张缩略图让用户指认 ----
    if not cfg.get("_front_explicit"):
        _errs = []
        previews = make_orientation_previews(cfg, kind="front", errors=_errs)
        if not previews:
            return _preview_failed_result(cfg, "主视图", _errs)
        # 生成自包含 HTML 选择页（内嵌图片 + 人话标注 + 点击生成命令）
        selection_page = make_selection_html(
            cfg, previews, kind="front", step_file=cfg["step_file"])
        return {
            "ok": False,
            "need": "orientation",
            "stage": "main_view",
            "action": "auto",
            "product": name,
            "step_file": cfg["step_file"],
            "selection_page": selection_page,
            "open_method": "agent_browser",
            "message": (
                "已生成选择页面。**用你自己的内置浏览器打开它**（不要调系统外部浏览器）：\n"
                f"  file:///{selection_page.replace(chr(92), '/')}\n"
                "用户在页面里点其中一张图，底部会自动显示命令，复制给你即可。"
                "也可以用户直接说「我选正面」之类的，你转成对应轴值。"
            ),
            "previews": previews,
            "options": [
                {"label": _AXIS_LABELS_CN.get(p["axis"], p["axis"]),
                 "value": p["axis"], "image": p["file"]}
                for p in previews
            ],
            "how_to_continue": (
                "**拿到用户答复后**（点 HTML 或打字），用 --front 重新调用（暂不给 --up）：\n"
                "  patent-cli auto --step <同一文件> --mode custom --front <用户选的轴>"
            ),
            "forbidden": "禁止在用户答复前传 --front；禁止用对称性/包围盒推断代替询问。",
        }

    # ---- 2. 上方向未确认 → 给 4 张候选（决定俯视图/仰视图）----
    if not cfg.get("_up_explicit"):
        front = cfg["front_axis"]
        default_up = default_up_for(front)
        _errs = []
        previews = make_orientation_previews(cfg, kind="up", front=front, errors=_errs)
        if not previews:
            return _preview_failed_result(cfg, "上方向", _errs)
        # 生成自包含 HTML 选择页（内嵌图片 + 人话标注 + 点击生成命令）
        selection_page = make_selection_html(
            cfg, previews, kind="up", front=front, step_file=cfg["step_file"])
        return {
            "ok": False,
            "need": "orientation",
            "stage": "up_axis",
            "action": "auto",
            "product": name,
            "step_file": cfg["step_file"],
            "main_view": front,
            "default_up": default_up,
            "selection_page": selection_page,
            "open_method": "agent_browser",
            "message": (
                "已生成选择页面。**用你自己的内置浏览器打开它**（不要调系统外部浏览器）：\n"
                f"  file:///{selection_page.replace(chr(92), '/')}\n"
                "用户在页面里点其中一张图，底部会自动显示命令，复制给你即可。"
                "也可以用户直接说「正着摆」之类的，你转成对应轴值。"
            ),
            "previews": previews,
            "options": [
                {"label": _up_label_cn(front, p["axis"]),
                 "value": p["axis"], "image": p["file"]}
                for p in previews
            ],
            "how_to_continue": (
                f"**拿到用户答复后**（点 HTML 或打字），两个参数一起传：\n"
                f"  patent-cli auto --step <同一文件> --mode custom "
                f"--front {front} --up <用户选的轴>"
            ),
            "forbidden": "禁止把 default_up 当作用户答复直接出图。",
        }

    # ---- 4. 分析模型 ----
    r_analyze = cmd_analyze(cfg)
    model = r_analyze["model"]

    # ---- 4. 多实体未筛选 → 让用户选外观件 ----
    if model["solids"] > 1 and not cfg.get("solids_filtered"):
        return {
            "ok": False,
            "need": "solid_selection",
            "action": "auto",
            "product": name,
            "model": model,
            "message": (
                f"模型含 {model['solids']} 个实体（装配体）。外观专利通常只保护外观件，"
                f"内部结构（PCB/螺丝/支架）画进附图会导致不合格。"
                f"**问用户**：全量出图，还是先筛选外观件？"
            ),
            "options": [
                {"label": "全量出图", "value": "all",
                 "hint": "用户确认后加 --solids-filtered 重跑"},
                {"label": "筛选外观件", "value": "filter",
                 "hint": f"先跑 python scripts/extract_solids.py list {cfg['step_file']} 看实体清单"},
            ],
            "forbidden": "禁止在用户答复前自行加 --solids-filtered。",
        }

    # ---- 5. 模型无效 → 提前告知风险（不阻断，继续出图）----
    warnings = []
    if not model["valid"]:
        warnings.append(
            f"模型 BRepCheck 判定无效"
            + (f"（{len(model['invalid_solids'])} 个实体有问题：{model['invalid_solids'][:8]}）"
               if model.get("invalid_solids") else "")
            + "。无效几何可能导致附图丢线，出图后请人工检查外轮廓是否闭合。"
        )

    # ---- 6. 跑全流程 ----
    # 方位/外观件都是用户确认过的，如实记进报告
    cfg["_orientation_source"] = "user"
    cfg["_orientation_user_confirmed"] = True
    r_run = cmd_run(cfg, analyzed=model)
    r_run["mode"] = MODE_CUSTOM
    if r_run.get("ok"):
        r_run["orientation"] = {
            "front_axis": cfg["front_axis"], "up_axis": cfg["up_axis"],
            "source": "user", "user_confirmed": True,
        }
    if warnings:
        r_run.setdefault("warnings", []).extend(warnings)
    return r_run


# ============================================================ 入口

def _emit(obj: dict, args, stream=None) -> None:
    """输出结果 JSON；若给了 --json-out，同时写一份到文件。

    为什么要文件：OCP 在 C++ 层会直接往 stdout 打印
    `**** ERR StepFile ...` 这类信息，Python 的 sys.stdout 重定向拦不住，
    会污染 JSON。agent 用 --json-out 从文件读就完全干净。
    """
    out = stream or sys.stdout
    text = json.dumps(obj, ensure_ascii=True, indent=None if getattr(args, "quiet", False) else 2)
    try:
        out.write(text + "\n")
        out.flush()
    except Exception:
        pass

    path = getattr(args, "json_out", None)
    if path:
        try:
            ap = os.path.abspath(path)
            os.makedirs(os.path.dirname(ap), exist_ok=True)
            with open(ap, "w", encoding="utf-8") as f:
                json.dump(obj, f, ensure_ascii=True, indent=2)
        except Exception:
            pass


def main():
    parser = argparse.ArgumentParser(
        prog="patent-cli",
        description="外观设计专利视图生成工具",
        epilog=(
            "首次使用：**必须先让用户选出图方式**（没有默认值）\n"
            "  patent-cli auto --step model.step                   → 返回 need=mode，问用户\n"
            "  patent-cli auto --step model.step --mode one_shot    → 一键式：方位按规则自动判定\n"
            "  patent-cli auto --step model.step --mode custom      → 自定义：逐项确认（含导出目录）\n"
            "\n"
            "换个导出位置（设置一次就记住）：\n"
            "  patent-cli config --out-dir \"D:/专利出图\"\n"
        ),
    )
    parser.add_argument("command",
                        choices=["auto", "analyze", "render", "dxf", "check", "run", "config"],
                        help="auto=出图主入口(必须先选 --mode) | analyze/render/dxf/check | run=已确认方位后的全流程 | config=设置导出目录")
    parser.add_argument("--config", help="job.json 路径（与 --step 二选一）")
    parser.add_argument("--step", help="直接给 STEP 文件路径（自动生成配置，无需写 json）")
    parser.add_argument("--product-name", help="产品名（用于输出目录命名）")
    parser.add_argument("--front", help="正面方向：+X/-X/+Y/-Y/+Z/-Z")
    parser.add_argument("--up", help="上方方向：+X/-X/+Y/-Y/+Z/-Z")
    parser.add_argument("--mode", choices=list(MODES),
                        help="出图方式（auto 必填，**没有默认值**）："
                             "one_shot=一键式（方位按包围盒规则自动判定，不再询问）| "
                             "custom=自定义（导出目录/主视图/上方向/外观件逐项确认）")
    parser.add_argument("--out-dir",
                        help="导出根目录。普通命令里只对这次生效；"
                             "配 config 命令使用时会被记住，以后一直用它。")
    parser.add_argument("--reset", action="store_true",
                        help="仅 config 命令：清除记住的导出目录，恢复默认")
    parser.add_argument("--solids-filtered", action="store_true",
                        help="声明已确认要全量出图（跳过 need=solid_selection 询问）")
    parser.add_argument("--quiet", action="store_true", help="只输出 JSON，不输出进度信息")
    parser.add_argument("--json-out",
                        help="把结果 JSON 同时写入该文件。OCP 在 C 层会往 stdout 打印错误信息，"
                             "解析不稳时用这个参数从文件读，保证干净。")

    args = parser.parse_args()

    # ---- config 子命令：只管偏好设置，不碰模型 ----
    if args.command == "config":
        result = cmd_config(args)
        _emit(result, args)
        raise SystemExit(EXIT_OK if result.get("ok") else EXIT_INPUT_ERROR)

    # ---- 加载配置：--config 或 --step 二选一 ----
    try:
        if args.config:
            cfg = load_job(args.config)
            # 命令行参数覆盖 config 里的值
            if args.front:
                cfg["front_axis"] = args.front
                cfg["_front_explicit"] = True
            if args.up:
                cfg["up_axis"] = args.up
                cfg["_up_explicit"] = True
        elif args.step:
            cfg = build_cfg_from_step(args.step, args.product_name, args.front, args.up)
        else:
            _emit({
                "ok": False,
                "error": "必须提供 --step <文件> 或 --config <json>",
                "examples": [
                    "patent-cli auto --step model.step",
                    "patent-cli run --config job.json --quiet",
                ],
            }, args)
            raise SystemExit(EXIT_INPUT_ERROR)
    except FileNotFoundError as e:
        _emit({"ok": False, "error": str(e)}, args)
        raise SystemExit(EXIT_INPUT_ERROR)
    except json.JSONDecodeError as e:
        _emit({"ok": False, "error": f"config JSON parse failed: {e}"}, args)
        raise SystemExit(EXIT_INPUT_ERROR)

    # 命令行开关覆盖配置
    if args.solids_filtered:
        cfg["solids_filtered"] = True
    cfg["_mode"] = args.mode

    # ---- 闸门 1：出图方式未定 → 必须问用户 ----
    # 刻意放在所有落盘动作之前：没定模式，磁盘上什么都不该出现。
    if args.command == "auto" and not args.mode:
        _emit(need_mode_result(cfg), args)
        raise SystemExit(EXIT_NEED_INPUT)

    # ---- 闸门 2：出图类命令不替用户猜方位 ----
    # run / render / dxf / check 都是"方位已确认后的（分步）出图"入口；
    # 没给方位就当成没确认，退回 auto 去问。analyze 不在此列（它只分析不出图）。
    _ORIENTATION_REQUIRED = {"run", "render", "dxf", "check"}
    if (args.command in _ORIENTATION_REQUIRED
            and not (cfg.get("_front_explicit") and cfg.get("_up_explicit"))):
        _emit({
            "ok": False,
            "need": "orientation",
            "stage": "unconfirmed",
            "action": args.command,
            "product": cfg.get("_name"),
            "message": (f"{args.command} 不会替用户猜方位。这个模型还没有确认过主视图/上方向，"
                        "请先用 auto 走完确认流程。"),
            "how_to_continue": (
                "  patent-cli auto --step <同一文件> --mode custom   （逐项确认）\n"
                "  patent-cli auto --step <同一文件> --mode one_shot （自动判定）"
            ),
            "forbidden": f"禁止在方位未确认时用 {args.command} 出图。",
        }, args)
        raise SystemExit(EXIT_NEED_INPUT)

    # ---- 定输出根目录（--out-dir > PATENT_OUT_DIR > 记住的目录 > 默认） ----
    try:
        pl.resolve_output_root(args.out_dir)
    except OSError as e:
        _emit({"ok": False,
               "error": f"输出目录不可用：{e}",
               "hint": "换一个可写目录，或用 patent-cli config --out-dir <路径> 设置。"}, args)
        raise SystemExit(EXIT_INPUT_ERROR)

    # ---- 分配输出目录 ----
    # 每个模型一个独立目录；同名但来自不同 STEP 时自动加 -2、-3 后缀，
    # 保证连着处理多个模型时，后一个不会把前一个的成果覆盖掉。
    try:
        _orig = cfg.get("_name") or "model"
        _final = pl.resolve_run_name(_orig, cfg.get("step_file"))
        if _final != _orig:
            cfg["_name_original"] = _orig
            cfg["_name"] = _final
        pl.write_model_meta(cfg["_name"], cfg.get("step_file"), cfg.get("product_name"))
    except OSError:
        pass

    # ---- 执行 ----
    real_stdout = sys.stdout
    try:
        # --quiet 模式：子模块的进度 print 重定向到 stderr，保持 stdout 纯净
        if args.quiet:
            sys.stdout = sys.stderr

        commands = {
            "auto": cmd_auto,
            "analyze": cmd_analyze,
            "render": cmd_render,
            "dxf": cmd_dxf,
            "check": cmd_check,
            "run": cmd_run,
        }
        result = commands[args.command](cfg)

        if args.quiet:
            sys.stdout = real_stdout

        if isinstance(result, dict):
            # need=out_dir 时不能说"导出到 X"——那正是还没定的东西
            if result.get("need") != "out_dir":
                result.setdefault("out_dir", pl.OUTPUT_ROOT)
                result.setdefault("out_dir_source", pl.OUTPUT_ROOT_SOURCE)
                if (result.get("out_dir_source") == "default"
                        and pl.DEFAULT_ROOT_FELL_BACK):
                    result.setdefault(
                        "note",
                        "桌面「外观专利视图」不可写，本次退回当前工作目录导出；"
                        "要用固定位置请 config --out-dir 指定。")
            if cfg.get("_mode"):
                result.setdefault("mode", cfg["_mode"])
            if cfg.get("_orientation_source"):
                result.setdefault("orientation_source", cfg["_orientation_source"])
                result.setdefault("orientation_user_confirmed",
                                  bool(cfg.get("_orientation_user_confirmed")))
            if cfg.get("_name"):
                result.setdefault("product_dir",
                                  os.path.join(pl.DIR_OUTPUT, cfg["_name"]))
            if cfg.get("_name_original"):
                result.setdefault("renamed_from", cfg["_name_original"])
                result.setdefault(
                    "renamed_reason",
                    f"已有同名模型占用 {cfg['_name_original']}/，"
                    f"本次结果放进 {cfg['_name']}/ 以免覆盖")

        # 输出 JSON。ensure_ascii=True → 纯 ASCII，任何编码下都不乱码。
        _emit(result, args, real_stdout)

        if not result.get("ok"):
            if result.get("need"):
                raise SystemExit(EXIT_NEED_INPUT)
            if result.get("input_error"):
                raise SystemExit(EXIT_INPUT_ERROR)
            raise SystemExit(EXIT_ENGINE_ERROR)
        raise SystemExit(EXIT_OK)

    except SystemExit:
        sys.stdout = real_stdout
        raise
    except Exception as e:
        sys.stdout = real_stdout
        tb = traceback.format_exc()
        _emit({
            "ok": False,
            "error": f"{type(e).__name__}: {e}",
            "hint": _error_hint(e),
            "traceback": tb if not args.quiet else None,
        }, args, real_stdout)
        raise SystemExit(EXIT_ENGINE_ERROR)


def cmd_config(args) -> dict:
    """导出目录的查看 / 设置 / 清除。

    `config --out-dir X` 会把 X 记到用户主目录下的配置文件里，
    以后所有命令默认导出到 X，除非再改或传 --out-dir 临时覆盖。
    """
    import userconfig

    saved = userconfig.get_out_dir()

    if args.reset:
        try:
            userconfig.clear_out_dir()
        except OSError as e:
            return {"ok": False, "action": "config",
                    "error": f"清除配置失败：{e}",
                    "hint": f"配置文件：{userconfig.config_file()}"}
        path, src = pl.resolve_output_root(None)
        return {
            "ok": True, "action": "config", "changed": "reset",
            "out_dir": path, "out_dir_source": src,
            "message": "已清除记住的导出目录，恢复默认位置。",
        }

    if args.out_dir:
        try:
            p = userconfig.set_out_dir(args.out_dir)
        except ValueError as e:
            return {"ok": False, "action": "config", "error": str(e),
                    "hint": "换一个已存在或可以创建的文件夹，例如 D:\\专利出图"}
        except OSError as e:
            return {"ok": False, "action": "config",
                    "error": f"配置写不进去：{e}",
                    "hint": f"目标文件：{userconfig.config_file()}"}
        pl.set_output_root(p, "config")
        out = {
            "ok": True, "action": "config", "changed": "out_dir",
            "out_dir": p, "out_dir_source": "config",
            "saved_to": userconfig.config_file(),
            "message": f"已记住：以后都导出到 {p}",
        }
        note = pl.default_root_note(p)
        if note:
            out["note"] = note
        return out

    path, src = pl.resolve_output_root(None)
    src_cn = {"arg": "命令行 --out-dir", "env": "环境变量 PATENT_OUT_DIR",
              "config": "你之前设置的目录", "default": "默认位置"}.get(src, src)
    out = {
        "ok": True, "action": "config", "changed": None,
        "out_dir": path, "out_dir_source": src, "out_dir_source_cn": src_cn,
        "saved_out_dir": saved,
        "saved_to": userconfig.config_file(),
        "message": f"当前导出到 {path}（来源：{src_cn}）",
    }
    if src == "default":
        note = pl.default_root_note(path)
        if note:
            out["note"] = note
        if pl.DEFAULT_ROOT_FELL_BACK:
            out["note"] = ("桌面「外观专利视图」不可写，已退回当前工作目录；"
                           "要用固定位置请 config --out-dir 指定。")
    return out


def _error_hint(e: Exception) -> str:
    """把异常翻译成一句人话 + 下一步建议（P4 的错误话术）。"""
    msg = str(e).lower()
    name = type(e).__name__

    if "dll load failed" in msg and "ocp" in msg:
        return "OCP 运行库缺失。轻量版请重跑 python install_deps.py；一键包请重新解压完整 zip。"
    if isinstance(e, FileNotFoundError):
        return "文件路径不对。检查 --step 指向的 STEP 文件是否存在（建议用绝对路径）。"
    if isinstance(e, ValueError) and "只支持 STEP" in str(e):
        return ("输入文件不是 STEP 格式。本工具只接受 .step / .stp；"
                "请在 CAD 中「另存为 / 导出」为 STEP（AP203 或 AP214）后重试。")
    if isinstance(e, PermissionError):
        return ("没有写权限。用 patent-cli config --out-dir <可写文件夹> 设置一次，"
                "以后都会导出到那里。")
    if "step 读取失败" in str(e) or "ifselect_retfail" in msg:
        return ("STEP 文件解析失败：通常是文件下载不完整、被截断，或不是真正的 STEP 文件。"
                "请确认文件以 END-ISO-10303-21 结尾，必要时重新获取。")
    if "memory" in msg:
        return "内存不足。模型可能过大，建议先在 CAD 中简化或只导出外观件。"
    if name == "KeyError":
        return "config 缺少必需字段。对照 SKILL.md 里的 job.json 示例补全。"
    return "请把上面的 error 和 traceback 反馈给开发者。"


if __name__ == "__main__":
    main()
