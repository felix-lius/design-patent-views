# -*- coding: utf-8 -*-
"""④ 专利规范化处理（导出提交件）

职责
----
* 把 ③ 产出的单视图 PNG 转为**专利局可接受的 JPEG**
* 写入 300 DPI 元数据（150×220mm 版面 → 1772×2598px）
* 保证：白底、RGB、无文字、无图号、纯实线（由 ③ 的渲染路径保证）
* 输出 output/<name>/submission/<序号>-<中文视图名>.jpg + logs/04_<name>.json

为什么单视图提交、图幅不提交
--------------------------
CNIPA 电子申请的外观图片是**每张视图一个文件**。sheet_*.png 含视图名称文字，
属于内部审阅用，不作为提交件——否则会触碰"图中不得有文字"的红线。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as pl
import spec

JPEG_QUALITY = 92          # 规格要求 ≥90


def run(name: str) -> dict:
    rep03 = pl.read_json(pl.step_log_path("03", name))
    if not rep03.get("ok"):
        raise RuntimeError("第③步未通过，不能进入第④步")

    cfg = pl.load_config(name)
    out_dir = os.path.join(pl.DIR_OUTPUT, name, "submission")
    os.makedirs(out_dir, exist_ok=True)

    # 清掉上次留下的 JPEG（含旧版英文命名），否则新旧混在一起，上传时容易传错
    for f in os.listdir(out_dir):
        if f.lower().endswith((".jpg", ".jpeg")):
            try:
                os.remove(os.path.join(out_dir, f))
            except OSError:
                pass

    from PIL import Image

    items = []
    total_bytes = 0
    for o in rep03["outputs"]:
        view = o["view"]
        src = o["file"]
        if not os.path.exists(src):
            raise RuntimeError(f"缺少源图：{src}")

        im = Image.open(src)
        # 统一为白底 RGB（JPEG 不支持透明，防止出现黑底）
        if im.mode in ("RGBA", "LA", "P"):
            im = im.convert("RGBA")
            bg = Image.new("RGB", im.size, (255, 255, 255))
            bg.paste(im, mask=im.split()[-1])
            im = bg
        elif im.mode != "RGB":
            im = im.convert("RGB")

        dst = os.path.join(out_dir, f"{spec.view_filename(view)}.jpg")
        im.save(
            dst,
            "JPEG",
            quality=JPEG_QUALITY,
            dpi=(spec.DPI, spec.DPI),
            subsampling=0,          # 4:4:4，避免锐利线条产生色边
            optimize=True,
        )
        size = os.path.getsize(dst)
        total_bytes += size

        # 回读校验：确认 JPEG 元数据与像素真的写进去了
        chk = Image.open(dst)
        dpi_read = chk.info.get("dpi", (None, None))
        items.append({
            "view": view,
            "name_cn": o["name_cn"],
            "filename": os.path.basename(dst),
            "file": dst,
            "format": chk.format,
            "pixel": list(chk.size),
            "dpi": [round(dpi_read[0], 1) if dpi_read[0] else None,
                    round(dpi_read[1], 1) if dpi_read[1] else None],
            "size_bytes": size,
            "figure_mm": o["figure_mm"],
        })

    rep = {
        "ok": True,
        "stage": "04_normalize",
        "name": name,
        "format": "JPEG",
        "quality": JPEG_QUALITY,
        "dpi": spec.DPI,
        "page_mm": list(spec.PAGE_MM),
        "submission_dir": out_dir,
        "total_bytes": total_bytes,
        "total_mb": round(total_bytes / 1048576, 3),
        "items": items,
        "note": "单视图 JPEG 为提交件；sheet_*.png 含视图名称文字，仅内部审阅用",
    }
    return rep


def main():
    if len(sys.argv) < 2:
        print("usage: step04_normalize.py <name>")
        raise SystemExit(2)
    name = sys.argv[1]
    rep = run(name)
    pl.write_json(pl.step_log_path("04", name), rep)
    print(f"[04] {len(rep['items'])} 张 JPEG，共 {rep['total_mb']} MB -> {rep['submission_dir']}")
    for it in rep["items"]:
        print(f"  {it['filename']:14s} {it['pixel'][0]}x{it['pixel'][1]}px  "
              f"{it['dpi'][0]}dpi  {it['size_bytes']//1024}KB")


if __name__ == "__main__":
    main()
