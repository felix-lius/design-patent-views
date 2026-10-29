# -*- coding: utf-8 -*-
"""DXF 导出：把全部视图写进一个可编辑的 DXF 文件。

设计要点
--------
1. **保留原生实体类型**：直线写 LINE，圆弧写 ARC，整圆写 CIRCLE，
   只有样条等才退化为 LWPOLYLINE —— 这样在 AutoCAD / 中望 / 浩辰里
   可以直接改半径、拉伸端点，而不是拖一堆碎线段。
2. **单位 = 毫米，1:1**：图幅按专利 150×220mm 版面排布，从 CAD 打印即为实际尺寸。
3. **第一角投影排布**：与 sheet_first_angle.png 完全对应，立体图置于右侧。
4. **图层分离**：几何在 VIEW 层，视图名称在 LABEL 层，便于关闭/单独打印。
"""
from __future__ import annotations

import math
import os

import ezdxf
from ezdxf.enums import TextEntityAlignment

import render
import spec

LAYER_VIEW = "VIEW"
LAYER_LABEL = "LABEL"
LAYER_FRAME = "FRAME"
FRAME_MARGIN_MM = 10.0


def _setup(doc):
    doc.header["$INSUNITS"] = 4          # 4 = 毫米
    doc.header["$MEASUREMENT"] = 1       # 公制
    doc.header["$LUNITS"] = 2

    for name, color in ((LAYER_VIEW, 7), (LAYER_LABEL, 7), (LAYER_FRAME, 8)):
        if name not in doc.layers:
            lay = doc.layers.add(name)
            lay.color = color
    doc.layers.get(LAYER_VIEW).lineweight = 35   # 0.35mm
    doc.layers.get(LAYER_LABEL).lineweight = 25

    # 中文文字样式（宋体，Windows 自带）
    if "CN" not in doc.styles:
        doc.styles.add("CN", font="simsun.ttc")


def _text_height_mm() -> float:
    return 3.5


def export_all_views(
    name: str,
    views: dict,
    txt_path: str,
    dpi: int = spec.DPI,
    gap_ratio: float = 0.26,
    scale_mode: str = "native",
) -> dict:
    """views: {view_key: {"primitives": [...], "bbox": [...], "size": [...]}}

    scale_mode
    ----------
    native : 1 单位 = 1mm 真实尺寸（1:1），CAD 里可直接量测。默认。
    page   : 缩放到 150×220mm 专利版面（各视图会被压小，仅用于出图比对）
    """
    # ---------- 1. 排布（模型单位） ----------
    six = [v for v in spec.SIX_VIEWS if v in views]
    if "front" not in views:
        raise ValueError("DXF 导出必须有主视图")

    sizes = {v: (views[v]["size"][0], views[v]["size"][1]) for v in six}
    # min_gap: 保证视图间距足够放下 3.5mm 的视图名称，避免名称压到相邻视图
    rects = render.layout_first_angle(sizes, gap_ratio=gap_ratio, min_gap=14.0) if len(six) >= 2 else {
        "front": (0.0, 0.0, views["front"]["size"][0], views["front"]["size"][1])
    }
    arr = render.arrangement_bbox(rects)

    # 立体图单独放六视图块下方、水平居中（避免把横向拉得过长）
    if "iso" in views:
        iw, ih = views["iso"]["size"]
        g = max(gap_ratio * max(sizes["front"][0], sizes["front"][1]) * 1.2, 16.0)
        cx_arr = (arr[0] + arr[2]) / 2.0
        y_top = arr[1] - g
        rects["iso"] = (cx_arr - iw / 2.0, y_top - ih, cx_arr + iw / 2.0, y_top)
        arr = render.arrangement_bbox(rects)

    # ---------- 2. 比例 ----------
    if scale_mode == "page":
        px_scale = render.fit_scale(arr, dpi)          # px / 模型单位
        mm_scale = px_scale * 25.4 / dpi               # mm / 模型单位
    else:
        mm_scale = 1.0                                  # 1:1 真实尺寸

    tc_x = (arr[0] + arr[2]) / 2.0
    tc_y = (arr[1] + arr[3]) / 2.0

    def tx(x, y):
        """模型坐标 → DXF 坐标（以排布中心为原点，Y 轴向上）。"""
        return ((x - tc_x) * mm_scale, (y - tc_y) * mm_scale)

    # ---------- 3. 写 DXF ----------
    doc = ezdxf.new("R2010", setup=False)
    _setup(doc)
    msp = doc.modelspace()

    stats = {"views": {}, "scale_mm_per_unit": mm_scale, "scale_mode": scale_mode}

    for view_key, vd in views.items():
        if view_key not in rects:
            continue
        rx0, ry0, rx1, ry1 = rects[view_key]
        bx0, by0 = vd["bbox"][0], vd["bbox"][1]
        dx = rx0 - bx0
        dy = ry0 - by0

        n = {"line": 0, "arc": 0, "circle": 0, "polyline": 0}
        for p in vd["primitives"]:
            k = p["kind"]
            if k == "line":
                a = tx(p["a"][0] + dx, p["a"][1] + dy)
                b = tx(p["b"][0] + dx, p["b"][1] + dy)
                msp.add_line(a, b, dxfattribs={"layer": LAYER_VIEW})
                n["line"] += 1
            elif k == "circle":
                c = tx(p["c"][0] + dx, p["c"][1] + dy)
                msp.add_circle(c, p["r"] * mm_scale, dxfattribs={"layer": LAYER_VIEW})
                n["circle"] += 1
            elif k == "arc":
                c = tx(p["c"][0] + dx, p["c"][1] + dy)
                msp.add_arc(
                    c,
                    p["r"] * mm_scale,
                    math.degrees(p["start"]),
                    math.degrees(p["end"]),
                    dxfattribs={"layer": LAYER_VIEW},
                )
                n["arc"] += 1
            else:
                pts = [tx(x + dx, y + dy) for x, y in p["pts"]]
                if len(pts) >= 2:
                    msp.add_lwpolyline(pts, dxfattribs={"layer": LAYER_VIEW})
                    n["polyline"] += 1
        stats["views"][view_key] = n

        # 视图名称：视图正下方
        label_x, label_y = tx((rx0 + rx1) / 2.0, ry0)
        msp.add_text(
            spec.VIEW_NAMES_CN.get(view_key, view_key),
            height=_text_height_mm(),
            dxfattribs={"layer": LAYER_LABEL, "style": "CN"},
        ).set_placement((label_x, label_y - 6.0), align=TextEntityAlignment.MIDDLE_CENTER)

    # ---------- 4. 外框：包住全部图形与视图名称 ----------
    arr_w = (arr[2] - arr[0]) * mm_scale
    arr_h = (arr[3] - arr[1]) * mm_scale
    pw, ph = spec.PAGE_MM
    print_scale = max(1.0, max(arr_w / pw, arr_h / ph))   # 建议打印比例 1:print_scale
    if scale_mode == "page":
        fw, fh = pw, ph
    else:
        # 四周留 10mm，保证视图名称（下移 6mm + 3.5mm 字高）落在框内
        fw, fh = arr_w + 2 * FRAME_MARGIN_MM, arr_h + 2 * FRAME_MARGIN_MM
    msp.add_lwpolyline(
        [(-fw / 2, -fh / 2), (fw / 2, -fh / 2), (fw / 2, fh / 2), (-fw / 2, fh / 2)],
        close=True,
        dxfattribs={"layer": LAYER_FRAME},
    )

    doc.saveas(txt_path)
    stats.update({
        "path": txt_path,
        "size_bytes": os.path.getsize(txt_path),
        "drawing_extent_mm": [round(arr_w, 1), round(arr_h, 1)],
        "suggested_print_scale": f"1:{print_scale:.2f}",
        "layers": [LAYER_VIEW, LAYER_LABEL, LAYER_FRAME],
    })
    return stats
