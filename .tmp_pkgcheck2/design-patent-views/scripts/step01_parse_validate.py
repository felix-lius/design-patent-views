# -*- coding: utf-8 -*-
"""① 输入解析与校验

职责
----
* 读取 config（产品名称/用途/主视图方位/出图模式/视图取舍）
* 载入 STEP，统计拓扑规模，做完整性校验
* 输出结构化报告 logs/01_<name>.json

设计原则
--------
破面、非流形等问题**只警告不中断**——专利出图可以先出，再由人工判断。
只有"文件读不进来""模型为空"这类硬失败才终止。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geom_core as geom
import pipeline as pl
import spec

SOLID_CHECK_LIMIT = 250   # 逐实体有效性检查的实体数上限（超出则跳过，避免耗时过长）


def run(name: str) -> dict:
    cfg = pl.load_config(name)
    warnings: list[str] = []
    errors: list[str] = []

    # --- 配置合法性 ---
    if cfg["front_axis"] not in geom.AXIS_VECTORS:
        errors.append(f"front_axis 非法: {cfg['front_axis']}")
    if cfg["up_axis"] not in geom.AXIS_VECTORS:
        errors.append(f"up_axis 非法: {cfg['up_axis']}")
    if cfg["design_mode"] not in ("overall", "partial"):
        errors.append(f"design_mode 非法: {cfg['design_mode']}")
    if cfg["front_axis"] in geom.AXIS_VECTORS and cfg["up_axis"] in geom.AXIS_VECTORS:
        f = geom.AXIS_VECTORS[cfg["front_axis"]]
        u = geom.AXIS_VECTORS[cfg["up_axis"]]
        if abs(sum(a * b for a, b in zip(f, u))) > 1e-6:
            errors.append("front_axis 与 up_axis 平行，无法构成视图坐标系")

    valid_views = set(spec.VIEW_NAMES_CN.keys())
    unknown_views = [v for v in cfg["views"] if v not in valid_views]
    if unknown_views:
        errors.append(f"未知视图名: {unknown_views}（可用: {sorted(valid_views)}）")
    unknown_omit = [v for v in cfg["omit"] if v not in valid_views]
    if unknown_omit:
        errors.append(f"omit 中存在未知视图名: {unknown_omit}")
    if cfg["design_mode"] == "partial":
        warnings.append("局部外观模式：第③步需实线+虚线区分保护范围，MVP 暂未实现，当前按整体外观出图")

    if errors:
        return {"ok": False, "stage": "01_parse_validate", "errors": errors,
                "warnings": warnings, "config": cfg}

    # --- STEP 载入 ---
    try:
        step_file = pl.step_path(name, cfg)
    except FileNotFoundError as e:
        return {"ok": False, "stage": "01_parse_validate", "errors": [str(e)],
                "warnings": warnings, "config": cfg}

    try:
        shape = geom.load_model(step_file)
    except Exception as e:
        return {"ok": False, "stage": "01_parse_validate",
                "errors": [f"STEP 载入失败: {type(e).__name__}: {e}"],
                "warnings": warnings, "config": cfg}

    stats = geom.shape_stats(shape)
    valid = geom.is_valid(shape)
    bb = geom.bbox3d(shape)

    # 实体级有效性：整机无效时，要知道是哪几个实体无效（决定该修什么）
    invalid_solids: list[int] = []
    solids_checked = 0
    if stats["solids"] > 1 and stats["solids"] <= SOLID_CHECK_LIMIT:
        from OCP.BRepCheck import BRepCheck_Analyzer
        sols = geom.split_solids(shape)
        for idx, s in enumerate(sols):
            solids_checked += 1
            try:
                if not BRepCheck_Analyzer(s).IsValid():
                    invalid_solids.append(idx)
            except Exception:
                pass
    elif stats["solids"] > SOLID_CHECK_LIMIT:
        warnings.append(
            f"实体数 {stats['solids']} 超过逐实体校验上限 {SOLID_CHECK_LIMIT}，已跳过实体级有效性检查"
        )

    if invalid_solids:
        warnings.append(
            f"检测到 {len(invalid_solids)}/{solids_checked} 个无效实体（破面/自交）："
            f"{invalid_solids[:10]}{' …' if len(invalid_solids) > 10 else ''}。"
            f"无效实体可能导致 HLR 丢线（轮廓不完整），建议在 CAD 中修复后重新导出"
        )

    # --- 完整性判断（警告级）---
    if not valid:
        warnings.append("BRepCheck 判定模型无效（可能存在破面/自交），出图结果需人工复核")
    if stats["solids"] == 0:
        errors.append("模型不含任何实体（solid），无法生成外观视图")
    if stats["solids"] > 1:
        warnings.append(f"模型含 {stats['solids']} 个实体，将合并投影（套件/组件产品需分别出图）")
    if stats["faces"] == 0:
        errors.append("模型不含任何面")

    size = tuple(bb[1][i] - bb[0][i] for i in range(3))
    if min(size) < 1.0:
        warnings.append(f"模型某一方向尺寸过小 ({min(size):.3f}mm)，疑似薄片或单位异常")

    report = {
        "ok": not errors,
        "stage": "01_parse_validate",
        "name": name,
        "step_file": step_file,
        "step_size_bytes": os.path.getsize(step_file),
        "config": cfg,
        "geometry": {
            "stats": stats,
            "is_valid": valid,
            "invalid_solids": invalid_solids,
            "solids_checked": solids_checked,
            "bbox_min": list(bb[0]),
            "bbox_max": list(bb[1]),
            "size": list(size),
        },
        "errors": errors,
        "warnings": warnings,
    }
    return report


def main():
    if len(sys.argv) < 2:
        print("usage: step01_parse_validate.py <name>")
        raise SystemExit(2)
    name = sys.argv[1]
    rep = run(name)
    pl.write_json(pl.step_log_path("01", name), rep)
    print(f"[01] ok={rep['ok']} errors={len(rep['errors'])} warnings={len(rep['warnings'])}")
    for w in rep["warnings"]:
        print("  WARN:", w)
    for e in rep["errors"]:
        print("  ERR :", e)
    if rep["ok"]:
        g = rep["geometry"]
        print(f"  step: {rep['step_file']}  ({rep['step_size_bytes']} bytes)")
        print(f"  solids={g['stats']['solids']} faces={g['stats']['faces']} edges={g['stats']['edges']}")
        if g.get("invalid_solids"):
            print(f"  无效实体：{g['invalid_solids']}（共校验 {g['solids_checked']} 个）")
        print(f"  size={g['size'][0]:.2f} x {g['size'][1]:.2f} x {g['size'][2]:.2f} mm")
    raise SystemExit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
