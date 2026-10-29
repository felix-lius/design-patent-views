# -*- coding: utf-8 -*-
"""渲染：把 2D 折线按统一比例画进专利规格画布。

比例一致性的实现方式
--------------------
第 ② 步对全部视图只算**一个** scale（取各视图适配比例的最小值），
第 ③ 步所有视图都用这个 scale 绘制，因此天然满足"各视图比例一致"。
"""
from __future__ import annotations

from typing import List, Tuple

from PIL import Image, ImageDraw, ImageFont

import spec

Polyline = List[Tuple[float, float]]
BBox = Tuple[float, float, float, float]


def page_px(dpi: int = spec.DPI) -> Tuple[int, int]:
    w_mm, h_mm = spec.PAGE_MM
    return (
        int(round(spec.mm_to_px(w_mm, dpi))),
        int(round(spec.mm_to_px(h_mm, dpi))),
    )


def content_px(dpi: int = spec.DPI) -> Tuple[float, float]:
    w_mm, h_mm = spec.PAGE_MM
    m = spec.MARGIN_MM
    return (
        spec.mm_to_px(w_mm - m["left"] - m["right"], dpi),
        spec.mm_to_px(h_mm - m["top"] - m["bottom"], dpi),
    )


def fit_scale(bbox: BBox, dpi: int = spec.DPI) -> float:
    """单个视图在版心内的最大适配比例（像素 / 模型单位）。"""
    xmin, ymin, xmax, ymax = bbox
    w = max(xmax - xmin, 1e-6)
    h = max(ymax - ymin, 1e-6)
    cw, ch = content_px(dpi)
    return min(cw / w, ch / h)


def uniform_scale(bboxes: List[BBox], dpi: int = spec.DPI) -> float:
    """全部视图共用比例：取各视图适配比例的最小值。"""
    scales = [fit_scale(b, dpi) for b in bboxes if b[2] > b[0] and b[3] > b[1]]
    if not scales:
        raise ValueError("没有任何非空视图，无法计算比例")
    return min(scales)


def render_view(
    polys: List[Polyline],
    bbox: BBox,
    scale: float,
    dpi: int = spec.DPI,
    line_width_mm: float = spec.LINE_WIDTH_DEFAULT_MM,
    supersample: int = 2,
    background: str = "white",
    color: str = "black",
) -> Image.Image:
    """按给定比例把折线画进 150×220mm @300DPI 画布，居中。"""
    pw, ph = page_px(dpi)
    ss = max(1, int(supersample))
    canvas = Image.new("RGB", (pw * ss, ph * ss), background)
    draw = ImageDraw.Draw(canvas)

    s = scale * ss
    xmin, ymin, xmax, ymax = bbox
    cx_model = (xmin + xmax) / 2.0
    cy_model = (ymin + ymax) / 2.0
    cx = pw * ss / 2.0
    cy = ph * ss / 2.0

    lw = max(1, spec.line_width_px(line_width_mm, dpi) * ss)

    for poly in polys:
        if len(poly) < 2:
            continue
        pts = [
            (cx + (x - cx_model) * s, cy - (y - cy_model) * s)
            for x, y in poly
        ]
        draw.line(pts, fill=color, width=lw, joint="curve")

    if ss > 1:
        canvas = canvas.resize((pw, ph), Image.LANCZOS)
    return canvas


def figure_size_mm(bbox: BBox, scale: float, dpi: int = spec.DPI) -> Tuple[float, float]:
    """算出图形在纸面上的实际尺寸（mm），用于合规自检。"""
    xmin, ymin, xmax, ymax = bbox
    return (
        (xmax - xmin) * scale / dpi * 25.4,
        (ymax - ymin) * scale / dpi * 25.4,
    )


# ------------------------------------------------------------------ 第一角投影图幅排版
def layout_first_angle(sizes: dict, gap_ratio: float = 0.26, min_gap: float = 0.0) -> dict:
    """按第一角投影约定排布六视图，返回每个视图在模型坐标系中的矩形 (x0,y0,x1,y1)。

    布局（第一角投影，中国标准）::

                       [仰视图]
        [右视图] [主视图] [左视图] [后视图]
                       [俯视图]

    约束：主↔俯 长对正（同宽、上下对齐）；主↔左/右/后 高平齐（同高、同一水平线）。
    """
    W = {k: float(v[0]) for k, v in sizes.items()}
    H = {k: float(v[1]) for k, v in sizes.items()}
    have = set(sizes)
    if "front" not in have:
        raise ValueError("图幅排版必须有主视图")

    Wf, Hf = W["front"], H["front"]
    g = max(gap_ratio * max(Wf, Hf), min_gap)
    rects: dict = {"front": (0.0, 0.0, Wf, Hf)}

    # 同一水平带（高平齐）：右视图在左，左视图、后视图在右
    x = Wf + g
    for v in ("left", "back"):
        if v in have:
            rects[v] = (x, 0.0, x + W[v], H[v])
            x += W[v] + g
    x = -g
    if "right" in have:
        rects["right"] = (x - W["right"], 0.0, x, H["right"])

    # 主视图正下方（长对正）：俯视图
    if "top" in have:
        rects["top"] = (0.0, -(H["top"] + g), Wf, -g)
    # 主视图正上方：仰视图
    if "bottom" in have:
        rects["bottom"] = (0.0, Hf + g, Wf, Hf + g + H["bottom"])

    return rects


def layout_grid(sizes: dict, gap_ratio: float = 0.22) -> dict:
    """2 列 × 3 行网格排布，竖版页面上图形更饱满（比四视图横排大约 1.7 倍）。

    布局::

        [主视图] [左视图]
        [俯视图] [右视图]
        [仰视图] [后视图]

    各视图仍保持统一比例，投影对应关系由数据本身保证。
    """
    W = {k: float(v[0]) for k, v in sizes.items()}
    H = {k: float(v[1]) for k, v in sizes.items()}
    have = set(sizes)
    if "front" not in have:
        raise ValueError("图幅排版必须有主视图")

    cols = [["front", "top", "bottom"], ["left", "right", "back"]]
    max_w = max(W.values())
    g = gap_ratio * max_w

    col_w = [max([W[v] for v in col if v in have] or [0.0]) for col in cols]
    row_h = []
    for r in range(3):
        hs = [H[cols[c][r]] for c in range(2) if cols[c][r] in have]
        row_h.append(max(hs) if hs else 0.0)

    col_x = [0.0, col_w[0] + g]
    row_top = [0.0]
    for r in range(2):
        row_top.append(row_top[-1] - (row_h[r] + g))

    rects: dict = {}
    for c, col in enumerate(cols):
        for r, v in enumerate(col):
            if v not in have:
                continue
            x = col_x[c] + (col_w[c] - W[v]) / 2.0
            row_bottom = row_top[r] - row_h[r]
            y = row_bottom + (row_h[r] - H[v]) / 2.0
            rects[v] = (x, y, x + W[v], y + H[v])
    return rects


def arrangement_bbox(rects: dict) -> BBox:
    xs0 = [r[0] for r in rects.values()]
    ys0 = [r[1] for r in rects.values()]
    xs1 = [r[2] for r in rects.values()]
    ys1 = [r[3] for r in rects.values()]
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def render_sheet(
    views: list,
    rects: dict,
    scale: float,
    dpi: int = spec.DPI,
    line_width_mm: float = spec.LINE_WIDTH_DEFAULT_MM,
    supersample: int = 2,
    labels: bool = True,
    font_path: str | None = None,
) -> Image.Image:
    """把多个视图按第一角投影排布画进同一张 150×220mm 图幅。

    views: [(view_key, polylines, bbox), ...]
    rects: {view_key: (x0,y0,x1,y1)}  模型坐标系中的目标矩形
    """
    pw, ph = page_px(dpi)
    ss = max(1, int(supersample))
    canvas = Image.new("RGB", (pw * ss, ph * ss), "white")
    draw = ImageDraw.Draw(canvas)

    total = arrangement_bbox(rects)
    s = scale * ss
    tc_x = (total[0] + total[2]) / 2.0
    tc_y = (total[1] + total[3]) / 2.0
    cx = pw * ss / 2.0
    cy = ph * ss / 2.0
    lw = max(1, spec.line_width_px(line_width_mm, dpi) * ss)

    label_jobs = []
    for view_key, polys, bbox in views:
        if view_key not in rects:
            continue
        rx0, ry0, rx1, ry1 = rects[view_key]
        xmin, ymin, xmax, ymax = bbox
        # 视图自身 bbox 的 min 对齐到目标矩形的 min
        tx = rx0 - xmin
        ty = ry0 - ymin
        for poly in polys:
            if len(poly) < 2:
                continue
            pts = [
                (cx + (x + tx - tc_x) * s, cy - (y + ty - tc_y) * s)
                for x, y in poly
            ]
            draw.line(pts, fill="black", width=lw, joint="curve")
        # 名称标注位置：视图正下方
        label_jobs.append((view_key, rx0, ry0, rx1, ry1))

    if labels and font_path:
        try:
            # 字号与间隙按 mm 换算，确保名称落在视图下方预留的 gap 内、不压邻图
            fs = int(spec.mm_to_px(3.5, dpi)) * ss
            gap_px = int(spec.mm_to_px(1.2, dpi)) * ss
            font = ImageFont.truetype(font_path, fs)
            for view_key, rx0, ry0, rx1, ry1 in label_jobs:
                name = spec.VIEW_NAMES_CN.get(view_key, view_key)
                lx = cx + ((rx0 + rx1) / 2.0 - tc_x) * s
                ly = cy - (ry0 - tc_y) * s + gap_px
                bbox_txt = draw.textbbox((0, 0), name, font=font)
                tw = bbox_txt[2] - bbox_txt[0]
                draw.text((lx - tw / 2.0, ly), name, font=font, fill="black")
        except Exception:
            pass

    if ss > 1:
        canvas = canvas.resize((pw, ph), Image.LANCZOS)
    return canvas
