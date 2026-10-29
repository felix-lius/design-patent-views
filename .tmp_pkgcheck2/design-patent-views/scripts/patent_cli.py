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

    必须剥离以下划线开头的内部字段（_name / _front_explicit / _up_explicit 等），
    否则会把内部状态写回用户的配置文件，污染它。
    """
    clean = {k: v for k, v in cfg.items() if not k.startswith("_")}
    path = pl.config_path(name)
    pl.write_json(path, clean)
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


def cmd_run(cfg: dict) -> dict:
    """全流程：分析 → 出图 → DXF → 自检。"""
    name = cfg["_name"]

    # 1. analyze
    r_analyze = cmd_analyze(cfg)

    # 如果多实体未筛选，返回 need（让 agent 问用户）
    if r_analyze["model"]["solids"] > 1 and not cfg.get("solids_filtered"):
        return {
            "ok": False,
            "need": "solid_selection",
            "action": "run",
            "product": name,
            "analyze": r_analyze["model"],
            "message": f"模型含 {r_analyze['model']['solids']} 个实体（装配体）。"
                       f"外观专利通常只保留外观件，建议用 extract_solids.py 筛选后重试。"
                       f"如确认要全量出图，请在 config 中设置 \"solids_filtered\": true。",
            "options": [
                {"label": "全量出图", "value": "all", "hint": "设置 solids_filtered=true 后重试"},
                {"label": "筛选外观件", "value": "filter", "hint": "用 extract_solids.py keep <step> <ids> <out>"},
            ],
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
        "analyze": r_analyze["model"],
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
                              target_px: int = 420) -> list:
    """渲染方位候选缩略图。

    kind="front" : 6 个候选主视图方向（±X/±Y/±Z）
    kind="up"    : 4 个候选上方向（垂直于给定 front）
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
        except Exception:
            continue
    return results


def cmd_auto(cfg: dict) -> dict:
    """首次体验：一步到位出图，缺信息时返回 need 让 agent 问用户。"""
    name = cfg["_name"]

    # ---- 1. 主视图方向未确认 → 给 6 张缩略图让用户指认 ----
    if not cfg.get("_front_explicit"):
        previews = make_orientation_previews(cfg, kind="front")
        return {
            "ok": False,
            "need": "orientation",
            "stage": "main_view",
            "action": "auto",
            "product": name,
            "step_file": cfg["step_file"],
            "message": (
                "模型的坐标轴和产品实际朝向不一定一致，出图前需要确认主视图方向。"
                "请把下面 6 张图给用户看，问：「哪一张作为**主视图**"
                "（即产品正常摆放时，从正面看过去的那一面）？」"
            ),
            "previews": previews,
            "options": [
                {"label": f"主视图 = {p['axis']}", "value": p["axis"], "image": p["file"]}
                for p in previews
            ],
            "how_to_continue": (
                "用户选定主视图后，先用 --front 重新调用（暂不给 --up），"
                "系统会接着询问上方向：\n"
                "  patent-cli auto --step <同一文件> --front +Y"
            ),
        }

    # ---- 2. 上方向未确认 → 给 4 张候选（决定俯视图/仰视图）----
    if not cfg.get("_up_explicit"):
        front = cfg["front_axis"]
        default_up = default_up_for(front)
        previews = make_orientation_previews(cfg, kind="up", front=front)
        return {
            "ok": False,
            "need": "orientation",
            "stage": "up_axis",
            "action": "auto",
            "product": name,
            "step_file": cfg["step_file"],
            "main_view": front,
            "default_up": default_up,
            "message": (
                f"主视图方向已定为 {front}。还需确认**上方向**——"
                f"它决定俯视图和仰视图哪个在上、哪个在下，弄反会导致附图形式缺陷。\n"
                f"请把下面 4 张图给用户看，问：「哪一张的朝向符合产品正常摆放时的"
                f"**上方向**？」\n"
                f"如果不想逐张看，直接用默认值 {default_up} 也可以。"
            ),
            "previews": previews,
            "options": [
                {"label": f"上方向 = {p['axis']}", "value": p["axis"], "image": p["file"]}
                for p in previews
            ],
            "how_to_continue": (
                f"用户选定后（或接受默认 {default_up}），用 --front 和 --up 一起调用：\n"
                f"  patent-cli auto --step <同一文件> --front {front} --up {default_up}"
            ),
        }

    # ---- 3. 分析模型 ----
    r_analyze = cmd_analyze(cfg)
    model = r_analyze["model"]

    # ---- 3. 多实体未筛选 → 让用户选外观件 ----
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
            ),
            "options": [
                {"label": "全量出图", "value": "all",
                 "hint": "在 config 加 \"solids_filtered\": true 后重试"},
                {"label": "筛选外观件", "value": "filter",
                 "hint": f"先跑 python scripts/extract_solids.py list {cfg['step_file']} 看实体清单"},
            ],
        }

    # ---- 4. 模型无效 → 提前告知风险（不阻断，继续出图）----
    warnings = []
    if not model["valid"]:
        warnings.append(
            f"模型 BRepCheck 判定无效"
            + (f"（{len(model['invalid_solids'])} 个实体有问题：{model['invalid_solids'][:8]}）"
               if model.get("invalid_solids") else "")
            + "。无效几何可能导致附图丢线，出图后请人工检查外轮廓是否闭合。"
        )

    # ---- 5. 跑全流程 ----
    r_run = cmd_run(cfg)
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
            "首次使用（最省事）：\n"
            "  patent-cli auto --step model.step\n"
            "  → 若返回 need=orientation，把 previews 给用户指认正面，\n"
            "    再跑 patent-cli auto --step model.step --front +Y --up +Z\n"
        ),
    )
    parser.add_argument("command",
                        choices=["auto", "analyze", "render", "dxf", "check", "run"],
                        help="auto=首次体验(自动+引导) | analyze/render/dxf/check | run=全流程")
    parser.add_argument("--config", help="job.json 路径（与 --step 二选一）")
    parser.add_argument("--step", help="直接给 STEP 文件路径（自动生成配置，无需写 json）")
    parser.add_argument("--product-name", help="产品名（用于输出目录命名）")
    parser.add_argument("--front", help="正面方向：+X/-X/+Y/-Y/+Z/-Z")
    parser.add_argument("--up", help="上方方向：+X/-X/+Y/-Y/+Z/-Z")
    parser.add_argument("--solids-filtered", action="store_true",
                        help="声明已确认要全量出图（跳过 need=solid_selection 询问）")
    parser.add_argument("--quiet", action="store_true", help="只输出 JSON，不输出进度信息")
    parser.add_argument("--json-out",
                        help="把结果 JSON 同时写入该文件。OCP 在 C 层会往 stdout 打印错误信息，"
                             "解析不稳时用这个参数从文件读，保证干净。")

    args = parser.parse_args()

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

        # 输出 JSON。ensure_ascii=True → 纯 ASCII，任何编码下都不乱码。
        _emit(result, args, real_stdout)

        if not result.get("ok"):
            if result.get("need"):
                raise SystemExit(EXIT_NEED_INPUT)
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
        return "没有写权限。换一个可写目录运行，或设置环境变量 PATENT_OUT_DIR 指定输出目录。"
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
