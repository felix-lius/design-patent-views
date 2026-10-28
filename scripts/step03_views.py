# -*- coding: utf-8 -*-
"""③ 视图生成（③a 六视图 + ③b 立体图）

职责
----
* 读 ② 的折线与统一比例，逐视图渲染成 150×220mm @300DPI 画布
* 六视图与立体图走完全相同的渲染路径，线宽/比例天然一致
* 输出三种图幅：
    raw/<view>.png        单视图干净图（无文字，名称由文件名承载）
    sheet.png             六视图按第一角投影排布的总图（含视图名称标注）
    contact_sheet.png     全视图缩略总览（含立体图，内部审阅用）
* 输出 logs/03_<name>.json
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as pl
import render
import spec

FONT_CANDIDATES = [
    r"C:\Windows\Fonts\msyh.ttc",
    r"C:\Windows\Fonts\msyhl.ttc",
    r"C:\Windows\Fonts\simhei.ttf",
    r"C:\Windows\Fonts\simsun.ttc",
]


def _find_font() -> str | None:
    for p in FONT_CANDIDATES:
        if os.path.exists(p):
            return p
    return None


def run(name: str) -> dict:
    rep02 = pl.read_json(pl.step_log_path("02", name))
    if not rep02.get("ok"):
        raise RuntimeError("第②步未通过，不能进入第③步")

    cfg = pl.load_config(name)
    rc = cfg.get("render", {})
    line_width_mm = float(rc.get("line_width_mm", spec.LINE_WIDTH_DEFAULT_MM))
    supersample = int(rc.get("supersample", 2))
    font_path = _find_font()

    out_dir = os.path.join(pl.DIR_OUTPUT, name, "raw")
    os.makedirs(out_dir, exist_ok=True)

    scale = rep02["uniform_scale_px_per_mm"]
    dpi = rep02["dpi"]

    # ---------- 单视图输出 ----------
    outputs = []
    view_polys = {}
    view_bbox = {}
    for view, vd in rep02["views"].items():
        polys = [[tuple(pt) for pt in poly] for poly in vd["polylines"]]
        bbox = tuple(vd["bbox"])
        view_polys[view] = polys
        view_bbox[view] = bbox
        vscale = vd.get("scale", scale)
        img = render.render_view(
            polys, bbox, vscale,
            dpi=dpi, line_width_mm=line_width_mm, supersample=supersample,
        )
        fpath = os.path.join(out_dir, f"{view}.png")
        img.save(fpath, "PNG")
        outputs.append({
            "view": view,
            "name_cn": spec.VIEW_NAMES_CN.get(view, view),
            "file": fpath,
            "pixel": list(img.size),
            "figure_mm": rep02["figure_size_mm"][view],
        })
        print(f"  {spec.VIEW_NAMES_CN.get(view, view):6s} -> raw/{view}.png  {img.size[0]}x{img.size[1]}px")

    # ---------- 图幅排版（两种版式都出） ----------
    sheet_paths = {}
    six = [v for v in spec.SIX_VIEWS if v in view_polys]
    if "front" in view_polys and len(six) >= 2:
        sizes = {v: (view_bbox[v][2] - view_bbox[v][0], view_bbox[v][3] - view_bbox[v][1]) for v in six}
        views_in = [(v, view_polys[v], view_bbox[v]) for v in six]
        layouts = {
            "sheet_first_angle": render.layout_first_angle,
            "sheet_grid": render.layout_grid,
        }
        for fname, fn in layouts.items():
            rects = fn(sizes)
            arr = render.arrangement_bbox(rects)
            arr_scale = render.fit_scale(arr, dpi)
            sheet = render.render_sheet(
                views_in, rects, arr_scale,
                dpi=dpi, line_width_mm=line_width_mm, supersample=supersample,
                labels=True, font_path=font_path,
            )
            p = os.path.join(pl.DIR_OUTPUT, name, f"{fname}.png")
            sheet.save(p, "PNG")
            sheet_paths[fname] = p
            print(f"  {fname:18s} -> {fname}.png  scale={arr_scale:.3f}  "
                  f"主视图宽≈{(sizes['front'][0]*arr_scale/25.4*25.4):.1f}mm")
    else:
        print("  ! 缺主视图或视图不足，跳过图幅排版")

    # ---------- DXF（全部视图，可编辑矢量） ----------
    dxf_path = None
    dxf_stats = None
    try:
        import dxf_export
        dxf_path = os.path.join(pl.DIR_OUTPUT, name, "all_views.dxf")
        views_for_dxf = {
            k: {"primitives": v["primitives"], "bbox": v["bbox"], "size": v["size"]}
            for k, v in rep02["views"].items()
            if "primitives" in v
        }
        if views_for_dxf:
            dxf_stats = dxf_export.export_all_views(name, views_for_dxf, dxf_path, dpi=dpi)
            tot = {}
            for vn in dxf_stats["views"].values():
                for k, c in vn.items():
                    tot[k] = tot.get(k, 0) + c
            print(f"  DXF(全视图) -> all_views.dxf  "
                  f"LINE={tot.get('line',0)} ARC={tot.get('arc',0)} "
                  f"CIRCLE={tot.get('circle',0)} POLY={tot.get('polyline',0)}  "
                  f"{dxf_stats['size_bytes']//1024}KB")
            print(f"      本机若无 CAD，可在线查看：{spec.ONLINE_DXF_VIEWERS[0][1]}")
        else:
            print("  ! 无 primitive 数据，跳过 DXF 导出")
    except Exception as e:
        print(f"  ! DXF 导出失败: {type(e).__name__}: {e}")

    # ---------- 缩略总览 ----------
    sheet_contact = _make_contact_sheet(out_dir, list(view_polys.keys()))
    contact_path = os.path.join(pl.DIR_OUTPUT, name, "contact_sheet.png")
    if sheet_contact is not None:
        sheet_contact.save(contact_path, "PNG")
        print(f"  总览 -> contact_sheet.png")

    return {
        "ok": True,
        "stage": "03_views",
        "name": name,
        "dpi": dpi,
        "page_mm": rep02["page_mm"],
        "line_width_mm": line_width_mm,
        "uniform_scale_px_per_mm": scale,
        "outputs": outputs,
        "sheets": sheet_paths,
        "dxf": dxf_stats,
        "contact_sheet": contact_path if sheet_contact is not None else None,
        "warnings": rep02.get("warnings", []),
    }


def _make_contact_sheet(out_dir: str, views: list):
    from PIL import Image
    thumbs = []
    for v in views:
        p = os.path.join(out_dir, f"{v}.png")
        if not os.path.exists(p):
            continue
        im = Image.open(p)
        im.thumbnail((500, 740), Image.LANCZOS)
        thumbs.append(im)
    if not thumbs:
        return None
    cols = 4
    rows = (len(thumbs) + cols - 1) // cols
    cw, ch = 520, 780
    sheet = Image.new("RGB", (cols * cw, rows * ch), "white")
    for i, im in enumerate(thumbs):
        r, c = divmod(i, cols)
        sheet.paste(im, (c * cw + (cw - im.width) // 2, r * ch + (ch - im.height) // 2))
    return sheet


def main():
    if len(sys.argv) < 2:
        print("usage: step03_views.py <name>")
        raise SystemExit(2)
    name = sys.argv[1]
    rep = run(name)
    pl.write_json(pl.step_log_path("03", name), rep)
    print(f"[03] ok={rep['ok']} views={len(rep['outputs'])}")


if __name__ == "__main__":
    main()
