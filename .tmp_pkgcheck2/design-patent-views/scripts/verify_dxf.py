# -*- coding: utf-8 -*-
"""回读验证：读入导出的 DXF，用其中的实体重新渲染成图。

独立于写入路径的验证——若 DXF 结构有问题、坐标错位、圆弧角度错误，
渲染结果会立刻暴露。
"""
from __future__ import annotations

import math
import os
import sys

import ezdxf
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FONT_PATH = r"C:\Windows\Fonts\msyh.ttc"


def arc_points(cx, cy, r, a0_deg, a1_deg, step_deg=2.0):
    a0, a1 = math.radians(a0_deg), math.radians(a1_deg)
    if a1 <= a0:
        a1 += 2 * math.pi
    n = max(2, int(math.degrees(a1 - a0) / step_deg) + 1)
    return [
        (cx + r * math.cos(a0 + (a1 - a0) * i / (n - 1)),
         cy + r * math.sin(a0 + (a1 - a0) * i / (n - 1)))
        for i in range(n)
    ]


def verify(dxf_path: str, out_png: str, max_px: int = 1500):
    doc = ezdxf.readfile(dxf_path)
    auditor = doc.audit()
    print(f"图层: {[l.dxf.name for l in doc.layers]}")
    print(f"单位: {doc.header.get('$INSUNITS')} (4=mm)")
    print(f"audit: errors={len(auditor.errors)} fixes={len(auditor.fixes)}")

    msp = doc.modelspace()
    counts, segs, texts = {}, [], []
    for ent in msp:
        t = ent.dxftype()
        counts[t] = counts.get(t, 0) + 1
        if t == "LINE":
            a, b = ent.dxf.start, ent.dxf.end
            segs.append([(a.x, a.y), (b.x, b.y)])
        elif t == "CIRCLE":
            c, r = ent.dxf.center, ent.dxf.radius
            segs.append(arc_points(c.x, c.y, r, 0, 360))
        elif t == "ARC":
            c, r = ent.dxf.center, ent.dxf.radius
            segs.append(arc_points(c.x, c.y, r, ent.dxf.start_angle, ent.dxf.end_angle))
        elif t == "LWPOLYLINE":
            pts = [(p[0], p[1]) for p in ent.get_points()]
            if len(pts) >= 2:
                segs.append(pts)
        elif t in ("TEXT", "MTEXT"):
            texts.append((ent.dxf.insert.x, ent.dxf.insert.y, ent.dxf.text))

    print("实体统计:", counts)

    xs = [x for s in segs for x, _ in s]
    ys = [y for s in segs for _, y in s]
    # 把文字位置也纳入边界，否则名称会被裁掉
    xs += [t[0] for t in texts]
    ys += [t[1] for t in texts]
    x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
    print(f"图形范围: x[{x0:.1f},{x1:.1f}] y[{y0:.1f},{y1:.1f}] mm  "
          f"-> {x1-x0:.1f} x {y1-y0:.1f} mm")
    print(f"视图名称({len(texts)}): {[t[2] for t in texts]}")

    pad = 6.0
    w_mm, h_mm = (x1 - x0) + 2 * pad, (y1 - y0) + 2 * pad
    ppx = min(max_px / max(w_mm, 1e-6), max_px / max(h_mm, 1e-6), 8.0)
    W, H = int(w_mm * ppx), int(h_mm * ppx)
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    font = ImageFont.truetype(FONT_PATH, max(12, int(3.5 * ppx)))

    def m2p(x, y):
        return ((x - x0 + pad) * ppx, (y1 - y + pad) * ppx)

    for s in segs:
        d.line([m2p(x, y) for x, y in s], fill="black", width=1, joint="curve")
    for x, y, txt in texts:
        px, py = m2p(x, y)
        d.text((px, py), txt, fill="#2563eb", anchor="mm", font=font)

    img.save(out_png, "PNG")
    print(f"预览: {out_png}  ({W}x{H}px, {ppx:.2f}px/mm)")
    return counts, texts


if __name__ == "__main__":
    name = sys.argv[1] if len(sys.argv) > 1 else "spacemouse"
    p = os.path.join(BASE, "output", name, "all_views.dxf")
    out = os.path.join(BASE, "output", name, "_dxf_verify.png")
    verify(p, out)
