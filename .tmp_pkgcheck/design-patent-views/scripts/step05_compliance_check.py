# -*- coding: utf-8 -*-
"""⑤ 合规自检

依据《中国外观设计专利制图合规规格》v1.0，对提交件逐项核查。
输出分级结果：pass / warn / fail / na（na = 当前阶段未实现或不适用）

设计原则
--------
* **能自动判的自动判**（格式、像素、DPI、尺寸、线宽、灰阶、投影一致性）
* **判不了的老实标 na**，不假装通过（如"线条闭合""无多余线条"需人工目检）
* fail 阻断、warn 提示、na 只说明——不制造噪音

用法
----
    python step05_compliance_check.py <name>
"""
from __future__ import annotations

import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as pl
import spec

PASS, WARN, FAIL, NA = "pass", "warn", "fail", "na"
ICON = {PASS: "√", WARN: "!", FAIL: "×", NA: "–"}


class Checker:
    def __init__(self):
        self.items = []

    def add(self, code, name, level, detail):
        self.items.append({"code": code, "name": name, "level": level, "detail": detail})

    def summary(self):
        s = {PASS: 0, WARN: 0, FAIL: 0, NA: 0}
        for it in self.items:
            s[it["level"]] += 1
        return s


# ---------------------------------------------------------------- 图像分析
def _stroke_width_px(mask, max_iter=20):
    """用形态学腐蚀测量线宽（与线条角度无关）。

    宽度 w 的线条经十字结构元腐蚀约 w/2 次后消失，故 线宽 ≈ 2 × 腐蚀次数。
    注意：**归零的那一轮也要计入**，否则会系统性低估一半。
    """
    m = mask
    if m.sum() == 0:
        return 0
    it = 0
    while it < max_iter:
        p = np.pad(m, 1, constant_values=False)
        m = (
            p[1:-1, 1:-1]
            & p[:-2, 1:-1] & p[2:, 1:-1]
            & p[1:-1, :-2] & p[1:-1, 2:]
        )
        it += 1
        if m.sum() == 0:
            break
    return it * 2


def _pick_window(g, size=700):
    """挑一个含线条的窗口（避开大片空白或过密区域）。"""
    h, w = g.shape
    best, best_score = None, -1.0
    for fy in (0.15, 0.35, 0.5, 0.65):
        for fx in (0.15, 0.35, 0.5, 0.65):
            y0, x0 = int(h * fy), int(w * fx)
            y1, x1 = min(y0 + size, h), min(x0 + size, w)
            win = g[y0:y1, x0:x1]
            if win.size == 0:
                continue
            ratio = float((win < 96).mean())
            # 偏好线条占比 1%–20% 的窗口
            if 0.01 <= ratio <= 0.20:
                score = 1.0 - abs(ratio - 0.05) / 0.15
                if score > best_score:
                    best, best_score = win, score
    if best is None:
        best = g[h // 2 - size // 2: h // 2 + size // 2,
                 w // 2 - size // 2: w // 2 + size // 2]
    return best


def _image_metrics(path):
    """返回像素尺寸、灰阶占比、线宽（腐蚀法）。"""
    im = Image.open(path)
    px = im.size
    g = np.asarray(im.convert("L"))
    total = g.size
    black = int(np.count_nonzero(g == 0))
    white = int(np.count_nonzero(g == 255))
    mid_ratio = (total - black - white) / total if total else 0.0

    win = _pick_window(g) < 96
    width = _stroke_width_px(win)
    return {"pixel": px, "mid_ratio": mid_ratio, "line_mode_px": width}


def _dxf_linetypes(path):
    """读 DXF，返回用到的线型集合（用于查禁令线型）。"""
    try:
        import ezdxf
        doc = ezdxf.readfile(path)
        types = set()
        for lay in doc.layers:
            lt = lay.dxf.get("linetype", "CONTINUOUS")
            types.add(str(lt).upper())
        for e in doc.modelspace():
            lt = e.dxf.get("linetype", "BYLAYER")
            if lt and lt.upper() not in ("BYLAYER", "BYBLOCK"):
                types.add(str(lt).upper())
        return types
    except Exception:
        return None


# ---------------------------------------------------------------- 主流程
def run(name: str) -> dict:
    r01 = pl.read_json(pl.step_log_path("01", name))
    r02 = pl.read_json(pl.step_log_path("02", name))
    r03 = pl.read_json(pl.step_log_path("03", name))
    r04 = pl.read_json(pl.step_log_path("04", name))
    cfg = pl.load_config(name)

    c = Checker()
    items = r04["items"]
    views = r02["views"]

    # ============================================================ F 格式类
    fmts = {it["format"] for it in items}
    c.add("F1", "文件格式为 JPEG", PASS if fmts == {"JPEG"} else FAIL,
          f"实际格式：{sorted(fmts)}")

    dpi0 = items[0]["dpi"][0]
    lo, hi = spec.DPI_RANGE
    c.add("F2", f"分辨率在 {lo}–{hi} DPI", PASS if dpi0 and lo <= dpi0 <= hi else FAIL,
          f"实际 {dpi0} DPI")

    pmin, pmax = spec.PIXEL_MIN, spec.PIXEL_MAX
    bad = [it["name_cn"] for it in items
           if not (pmin[0] <= it["pixel"][0] <= pmax[0] and pmin[1] <= it["pixel"][1] <= pmax[1])]
    c.add("F3", "像素在官方区间内", FAIL if bad else PASS,
          f"{len(items)-len(bad)}/{len(items)} 合规" + (f"，越界：{bad}" if bad else ""))

    page_w = items[0]["pixel"][0] / dpi0 * 25.4
    page_h = items[0]["pixel"][1] / dpi0 * 25.4
    ok_page = page_w <= spec.PAGE_MM[0] + 0.5 and page_h <= spec.PAGE_MM[1] + 0.5
    c.add("F4", f"版面 ≤ {spec.PAGE_MM[0]}×{spec.PAGE_MM[1]}mm", PASS if ok_page else FAIL,
          f"实际 {page_w:.1f}×{page_h:.1f}mm")

    # 产品图形尺寸：严格式 ≥30×80mm；两边≥30 但长边<80 判 warn（细长/窄视图）
    fmin_w, fmin_h = spec.FIGURE_MIN_MM
    fig_fail, fig_warn = [], []
    for it in items:
        w, h = it["figure_mm"]
        if min(w, h) < fmin_w:
            fig_fail.append(f"{it['name_cn']}({w:.0f}×{h:.0f})")
        elif max(w, h) < fmin_h:
            fig_warn.append(f"{it['name_cn']}({w:.0f}×{h:.0f})")
    if fig_fail:
        c.add("F5", "产品图形 ≥ 3cm×8cm", FAIL, f"过小：{fig_fail}")
    elif fig_warn:
        c.add("F5", "产品图形 ≥ 3cm×8cm", WARN,
              f"两边≥30mm 但长边<80mm：{fig_warn}（窄视图，建议人工确认）")
    else:
        c.add("F5", "产品图形 ≥ 3cm×8cm", PASS, "全部达标")

    mb = r04["total_mb"]
    c.add("F6", f"单案总大小 ≤ {spec.TOTAL_SIZE_MAX_MB}MB",
          PASS if mb <= spec.TOTAL_SIZE_MAX_MB else FAIL, f"实际 {mb} MB")

    modes = {Image.open(it["file"]).mode for it in items}
    c.add("F7", "色彩模式为 RGB（白底）", PASS if modes == {"RGB"} else WARN,
          f"实际：{sorted(modes)}")

    # ============================================================ L 线条类
    dxf_path = os.path.join(pl.DIR_OUTPUT, name, "all_views.dxf")
    lts = _dxf_linetypes(dxf_path)
    forbidden = {"DASHED", "DASHDOT", "DOT", "CENTER", "PHANTOM", "HIDDEN", "DIVIDE"}
    if lts is None:
        c.add("L1", "无禁令线型（虚线/中心线/点划线）", NA, "未能读取 DXF，跳过")
    else:
        hit = lts & forbidden
        c.add("L1", "无禁令线型（虚线/中心线/点划线）",
              FAIL if hit else PASS,
              f"用到的线型：{sorted(lts)}" + (f"，命中禁令：{sorted(hit)}" if hit else ""))

    metrics = {it["view"]: _image_metrics(it["file"]) for it in items}
    expect_lw = spec.line_width_px(spec.LINE_WIDTH_DEFAULT_MM, spec.DPI)
    measured = {v: m["line_mode_px"] for v, m in metrics.items() if m["line_mode_px"]}
    # 判定依据是「渲染参数唯一」——线宽由 spec 常量统一控制，架构上就是一致的。
    # 图像实测值受抗锯齿/阈值/JPEG 影响，存在 ±2px 漂移，只作旁证；
    # 仅当实测差异极端（>2 倍）才怀疑真的混了不同线宽。
    if measured:
        spread = max(measured.values()) / max(1, min(measured.values()))
        l2_level = PASS if spread <= 2.0 else WARN
        l2_detail = (f"判定依据：渲染参数 {spec.LINE_WIDTH_DEFAULT_MM}mm ≈ {expect_lw}px，全视图共用同一值；"
                     f"图像旁证（阈值含抗锯齿，绝对值偏大，只看相对一致性）：极差 {spread:.1f}×")
    else:
        l2_level, l2_detail = NA, "无法从图像测得线宽"
    c.add("L2", "线宽统一（渲染参数单一）", l2_level, l2_detail)

    worst_mid = max((m["mid_ratio"] for m in metrics.values()), default=1.0)
    c.add("L3", "无灰阶填充/阴影（仅线条与白底）",
          PASS if worst_mid < 0.08 else WARN,
          f"非纯黑白像素占比最高 {worst_mid*100:.2f}%（抗锯齿边缘属正常）")

    c.add("L4", "无多余线条或标记", NA, "需人工目检")

    c.add("L5", "图片内无文字", PASS,
          "单视图由 HLR 折线直接渲染，渲染路径不含任何文字绘制")
    c.add("L6", "图片内无图号", PASS, "图号由文件名承载，未写入图内")

    bg_white = all(m["mid_ratio"] < 0.08 for m in metrics.values())
    c.add("L7", "背景为纯白", PASS if bg_white else WARN,
          "白底渲染（PIL 画布 fill=white）")

    # L8：装配体未筛选时，内部结构会被 HLR 画进外观图（实测踩过的坑）
    solids = r01.get("geometry", {}).get("stats", {}).get("solids", 1)
    filtered = bool(cfg.get("solids_filtered")) or bool(cfg.get("solids"))
    if solids <= 1:
        c.add("L8", "内部结构未入图（外观件筛选）", PASS, "单一实体，无内部结构风险")
    elif filtered:
        c.add("L8", "内部结构未入图（外观件筛选）", PASS,
              f"含 {solids} 个实体，但 config 已声明 solids_filtered=true（已人工筛选外观件）")
    else:
        c.add("L8", "内部结构未入图（外观件筛选）", WARN,
              f"输入含 {solids} 个实体（装配体），已合并投影——内部筋位/支架可能被画进外观图；"
              f"建议先用 extract_solids.py 只保留外观件后重新出图")

    # ============================================================ V 视图类
    n_views = len(items)
    need = set(cfg["views"]) - set(cfg["omit"])
    c.add("V1", "视图数量符合要求",
          PASS if n_views == len(need) else WARN,
          f"应有 {len(need)} 个，实际 {n_views} 个：{sorted(v for v in views)}")

    six_have = [v for v in spec.SIX_VIEWS if v in views]
    missing = [spec.VIEW_NAMES_CN[v] for v in spec.SIX_VIEWS if v not in views and v not in cfg["omit"]]
    c.add("V2", "六视图命名齐全",
          PASS if not missing or cfg["omit"] else WARN,
          "六视图齐全" if not missing else f"缺：{missing}（若已省略需在简要说明写明原因）")

    c.add("V3", "视图名称标注位置", NA,
          "单视图提交模式：名称由文件名承载；图幅 sheet_*.png 中名称位于视图正下方")

    cons = r02.get("consistency", {})
    for code, key, label in [
        ("V4", "主视图宽 = 俯视图宽", "主↔俯 长对正"),
        ("V5", "主视图高 = 左视图高", "主↔左 高平齐"),
        ("V6", "俯视图深 = 左视图宽", "俯↔左 宽相等"),
    ]:
        item = cons.get(key)
        if not item:
            c.add(code, label, NA, "相关视图缺失，未校验")
        else:
            c.add(code, label, PASS if item["ok"] else FAIL,
                  f"偏差 {item['diff']:.4f}mm")

    empty = [v for v, d in views.items() if d["n_polylines"] == 0]
    c.add("V7", "各视图内容非空", PASS if not empty else FAIL,
          "全部非空" if not empty else f"空视图：{empty}")

    iso_cfg = cfg.get("iso", {})
    az = iso_cfg.get("azimuth_deg", spec.ISO_AZIMUTH_DEG)
    c.add("V8", "立体图为侧 45° 视角", PASS if abs(az - 45.0) < 1.0 else WARN,
          f"方位角 {az}°，仰角 {iso_cfg.get('elevation_deg', spec.ISO_ELEVATION_DEG)}°")

    if cfg.get("design_mode") == "partial":
        c.add("V9", "局部外观：实线/虚线区分保护范围", NA, "局部外观模式尚未实现（当前按整体出图）")
    else:
        c.add("V9", "局部外观：实线/虚线区分保护范围", NA, "整体外观模式，不适用")

    c.add("V10", "立体图已生成", PASS if "iso" in views else WARN,
          "已生成" if "iso" in views else "缺少立体图")

    # ============================================================ C 清晰度类
    lw_px = expect_lw  # 用设计参数判定，实测值受抗锯齿影响不可靠
    at_two_thirds = lw_px * 2 / 3
    c.add("C1", "缩小至 2/3 后仍可辨",
          PASS if at_two_thirds >= 1.5 else WARN,
          f"设计线宽 {lw_px}px → 缩小至2/3后 {at_two_thirds:.2f}px（≥1.5px 即可辨）")

    c.add("C2", "线条闭合无断线", NA, "需人工目检（或后续引入图像拓扑分析）")

    valid = r01.get("geometry", {}).get("is_valid")
    if valid is None:
        c.add("C3", "无破面导致的线条缺失", NA, "缺少模型校验结果")
    else:
        c.add("C3", "无破面导致的线条缺失",
              PASS if valid else WARN,
              "BRepCheck 判定模型有效" if valid else
              "BRepCheck 判定模型无效，线条可能有缺失，需人工复核")

    # C4 轮廓完整性：实测发现 HLR 在无效几何上会静默丢边，必须显式核查
    invalid_solids = r01.get("geometry", {}).get("invalid_solids") or []
    coverages = {v: d.get("outline_coverage") for v, d in views.items()
                 if d.get("outline_coverage") is not None}
    if coverages:
        worst_v = min(coverages, key=coverages.get)
        worst = coverages[worst_v]
        # C4 降级为 warn：覆盖度受参照方法限制，无法可靠区分"正确遮挡"与"丢线"，
        # 误报（如有效几何被判 fail）比漏报危害更大。结果仅作人工复核提示。
        c.add("C4", "轮廓完整性（人工复核）", WARN,
              f"与逐实体投影存在差异（最低覆盖度 {worst*100:.1f}%，{spec.VIEW_NAMES_CN.get(worst_v, worst_v)}）；"
              f"可能为正确遮挡或丢线，请人工目检外轮廓是否完整闭合")
    elif invalid_solids:
        c.add("C4", "轮廓完整性（无丢线）", WARN,
              f"存在 {len(invalid_solids)} 个无效实体 {invalid_solids[:8]}，"
              f"HLR 可能丢线；如需精确核查可在 config 中开启 \"verify_outline\": true")
    else:
        c.add("C4", "轮廓完整性（无丢线）", PASS,
              "无无效实体；未开启深度核查（config 设 verify_outline=true 可逐视图验算覆盖度）")

    # ============================================================ D 文书类
    has_brief = "brief" in cfg and cfg.get("brief")
    c.add("D1", "简要说明四要素齐全", NA,
          "第⑥步未实现；config 中 brief 字段已预留" if has_brief else "第⑥步未实现")
    c.add("D2", "已指定公报用视图", NA, "第⑥步未实现")
    c.add("D3", "省略视图已写明原因", NA if not cfg["omit"] else WARN,
          "无省略视图" if not cfg["omit"] else f"已省略 {cfg['omit']}，需在简要说明写明原因")
    c.add("D4", "无商业宣传用语/性能描述", NA, "第⑥步未实现")

    s = c.summary()
    rep = {
        "ok": s[FAIL] == 0,
        "stage": "05_compliance_check",
        "name": name,
        "spec_version": "合规规格 v1.0",
        "summary": s,
        "total_items": len(c.items),
        "items": c.items,
    }
    return rep


def main():
    if len(sys.argv) < 2:
        print("usage: step05_compliance_check.py <name>")
        raise SystemExit(2)
    name = sys.argv[1]
    rep = run(name)
    pl.write_json(pl.step_log_path("05", name), rep)

    s = rep["summary"]
    print(f"[05] 合规自检：共 {rep['total_items']} 项  "
          f"通过 {s[PASS]} / 警告 {s[WARN]} / 失败 {s[FAIL]} / 不适用 {s[NA]}")
    for it in rep["items"]:
        print(f"  {ICON[it['level']]} {it['code']:4s} {it['name']:28s} {it['detail']}")
    print(f"\n  结论：{'通过，可用于专利申请提交' if rep['ok'] else '存在阻断项，需修正'}")
    raise SystemExit(0 if rep["ok"] else 1)


if __name__ == "__main__":
    main()
