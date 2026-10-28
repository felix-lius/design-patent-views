# -*- coding: utf-8 -*-
"""② 几何预处理

职责
----
* 由主视图方位推导六视图 + 立体图的投影轴系（第一角投影）
* 对每个视图做 HLR 投影，得到 2D 折线，并记录其包围盒
* 计算**全局统一比例**（各视图共用，保证"各视图比例一致"）
* 输出 logs/02_<name>.json（含折线数据，供 ③ 直接渲染）

为什么把折线也存下来
--------------------
HLR 是整条链路最耗时的一步；存下来后 ③ 可以反复调渲染参数而不必重算几何。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geom_core as geom
import pipeline as pl
import render
import spec


def _count_kinds(prims) -> dict:
    out: dict = {}
    for p in prims:
        out[p["kind"]] = out.get(p["kind"], 0) + 1
    return out


def _round_prims(prims):
    """坐标保留 6 位，控制日志体积。"""
    out = []
    for p in prims:
        q = dict(p)
        if q["kind"] == "line":
            q["a"] = [round(q["a"][0], 6), round(q["a"][1], 6)]
            q["b"] = [round(q["b"][0], 6), round(q["b"][1], 6)]
        elif q["kind"] in ("circle", "arc"):
            q["c"] = [round(q["c"][0], 6), round(q["c"][1], 6)]
            q["r"] = round(q["r"], 6)
            if q["kind"] == "arc":
                q["start"] = round(q["start"], 8)
                q["end"] = round(q["end"], 8)
        else:
            q["pts"] = [[round(x, 6), round(y, 6)] for x, y in q["pts"]]
        out.append(q)
    return out


def run(name: str, deflection: float = 0.05) -> dict:
    rep01 = pl.read_json(pl.step_log_path("01", name))
    if not rep01.get("ok"):
        raise RuntimeError("第①步未通过，不能进入第②步")

    cfg = rep01["config"]
    front, up = cfg["front_axis"], cfg["up_axis"]
    warnings: list[str] = []

    shape = geom.load_step(rep01["step_file"])

    # 六视图轴系 + 立体图轴系
    axes = geom.view_axes(front, up)
    iso_cfg = cfg.get("iso", {})
    iso_d, iso_u = geom.iso_axes(
        front, up,
        azimuth_deg=iso_cfg.get("azimuth_deg", spec.ISO_AZIMUTH_DEG),
        elevation_deg=iso_cfg.get("elevation_deg", spec.ISO_ELEVATION_DEG),
    )
    axes["iso"] = (iso_d, iso_u)

    views_data: dict[str, dict] = {}
    hlr_mode = cfg.get("hlr_mode", "composite")
    verify_outline = bool(cfg.get("verify_outline", False))
    for v in cfg["views"]:
        if v in cfg["omit"]:
            continue
        d, u = axes[v]
        prims, polys = geom.project_by_mode(shape, d, u, mode=hlr_mode, deflection=deflection)
        bb = geom.polyline_bbox(polys)
        if not polys:
            warnings.append(f"{spec.VIEW_NAMES_CN.get(v, v)} 投影为空，已跳过")
            continue
        entry = {
            "view_dir": [round(c, 6) for c in d],
            "up_dir": [round(c, 6) for c in u],
            "bbox": [round(c, 6) for c in bb],
            "size": [round(bb[2] - bb[0], 6), round(bb[3] - bb[1], 6)],
            "n_polylines": len(polys),
            "n_points": sum(len(p) for p in polys),
            "n_primitives": len(prims),
            "primitive_kinds": _count_kinds(prims),
            "polylines": [[[round(x, 6), round(y, 6)] for x, y in p] for p in polys],
            "primitives": _round_prims(prims),
        }
        # 轮廓完整性：以"逐实体投影"为参照，评估当前结果对外边界的覆盖度
        if verify_outline and hlr_mode != "per_solid":
            # 参照用逐实体全量投影（PolyAlgo 剪影对圆柱面等几何会残缺，导致误报）
            sols = geom.split_solids(shape)
            ref_all = []
            for s in sols:
                _, p = geom.project_visible_full(s, d, u, deflection=deflection)
                ref_all.extend(p)
            cov = geom.outline_coverage(ref_all, polys, tol=1.0)
            entry["outline_coverage"] = round(cov, 4)
            if cov < 0.90:
                warnings.append(
                    f"{spec.VIEW_NAMES_CN.get(v, v)} 轮廓覆盖度 {cov*100:.1f}%，"
                    f"与逐实体投影差异较大，建议人工目检外轮廓是否完整闭合"
                )
        views_data[v] = entry

    if not views_data:
        raise RuntimeError("所有视图均为空，无法出图")

    # 全局统一比例
    #   六视图必须"各视图比例一致" → 共用一个 scale
    #   立体图属参考图，规范未要求与六视图同比例 → 单独按版心适配，
    #   避免它把六视图压得过小（导致图形尺寸逼近 3cm×8cm 下限）
    six_keys = [k for k in spec.SIX_VIEWS if k in views_data]
    six_bboxes = [tuple(views_data[k]["bbox"]) for k in six_keys]
    scale = render.uniform_scale(six_bboxes) if six_bboxes else render.uniform_scale(bboxes)

    iso_scale = None
    if "iso" in views_data:
        iso_scale = render.fit_scale(tuple(views_data["iso"]["bbox"]))
        views_data["iso"]["scale"] = iso_scale
    for k in six_keys:
        views_data[k]["scale"] = scale

    # 投影一致性校验（主↔俯 宽度、主↔左 高度、俯↔左 深度）
    consistency = {}
    def _sz(k):
        return views_data[k]["size"] if k in views_data else None
    checks = [
        ("front", 0, "top", 0, "主视图宽 = 俯视图宽"),
        ("front", 1, "left", 1, "主视图高 = 左视图高"),
        ("top", 1, "left", 0, "俯视图深 = 左视图宽"),
    ]
    for a, ai, b, bi, label in checks:
        sa, sb = _sz(a), _sz(b)
        if not sa or not sb:
            continue
        diff = abs(sa[ai] - sb[bi])
        ok = diff < 1e-3 * max(sa[ai], sb[bi], 1.0)
        consistency[label] = {"ok": ok, "diff": round(diff, 6)}
        if not ok:
            warnings.append(f"投影一致性异常：{label}（差 {diff:.4f}mm）")

    # 各视图在纸面上的实际图形尺寸（仅记录；是否达标由第⑤步合规自检分级判定）
    fig_mm = {}
    for k, v in views_data.items():
        vscale = v.get("scale", scale)
        w_mm, h_mm = render.figure_size_mm(tuple(v["bbox"]), vscale)
        fig_mm[k] = [round(w_mm, 2), round(h_mm, 2)]

    return {
        "ok": True,
        "stage": "02_orient",
        "name": name,
        "front_axis": front,
        "up_axis": up,
        "design_mode": cfg["design_mode"],
        "projection": spec.PROJECTION,
        "deflection": deflection,
        "uniform_scale_px_per_mm": scale,
        "iso_scale_px_per_mm": iso_scale,
        "hlr_mode": hlr_mode,
        "verify_outline": verify_outline,
        "dpi": spec.DPI,
        "page_mm": list(spec.PAGE_MM),
        "views": views_data,
        "consistency": consistency,
        "figure_size_mm": fig_mm,
        "warnings": warnings,
    }


def main():
    if len(sys.argv) < 2:
        print("usage: step02_orient.py <name>")
        raise SystemExit(2)
    name = sys.argv[1]
    rep = run(name)
    pl.write_json(pl.step_log_path("02", name), rep)
    print(f"[02] views={len(rep['views'])} scale={rep['uniform_scale_px_per_mm']:.3f} px/mm")
    for k, v in rep["views"].items():
        print(f"  {spec.VIEW_NAMES_CN.get(k,k):6s} size={v['size'][0]:.2f}x{v['size'][1]:.2f}mm "
              f"polys={v['n_polylines']} paper={rep['figure_size_mm'][k][0]:.1f}x{rep['figure_size_mm'][k][1]:.1f}mm")
    for label, c in rep["consistency"].items():
        print(f"  consistency {label}: {'OK' if c['ok'] else 'FAIL'} (diff={c['diff']})")
    for w in rep["warnings"]:
        print("  WARN:", w)


if __name__ == "__main__":
    main()
