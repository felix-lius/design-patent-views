# -*- coding: utf-8 -*-
"""核心几何：STEP 载入 / 校验 / 视图定向 / HLR 隐藏线消除 / 折线离散。

设计要点
--------
* 六视图与立体图共用同一条代码路径：都是"给定投影方向 → HLR → 2D 折线"，
  只是换一个投影轴系，保证线型、线宽、比例天然一致。
* 只取可见边（VCompound / Rg1LineVCompound / OutLineVCompound），
  完全丢弃隐藏边（HCompound 等）——符合"虚线禁用"的合规红线。
"""
from __future__ import annotations

import math
from typing import Dict, List, Tuple

from OCP.BRepAdaptor import BRepAdaptor_Curve
from OCP.BRepBndLib import BRepBndLib
from OCP.BRepCheck import BRepCheck_Analyzer
from OCP.Bnd import Bnd_Box
from OCP.GCPnts import GCPnts_QuasiUniformDeflection
from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Line
from OCP.HLRAlgo import HLRAlgo_Projector
from OCP.HLRBRep import HLRBRep_Algo, HLRBRep_HLRToShape
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_Reader
from OCP.TopAbs import (
    TopAbs_EDGE,
    TopAbs_FACE,
    TopAbs_SHELL,
    TopAbs_SOLID,
    TopAbs_VERTEX,
)
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

Polyline = List[Tuple[float, float]]
BBox = Tuple[float, float, float, float]  # xmin, ymin, xmax, ymax


# ------------------------------------------------------------------ 载入与校验
def load_step(path: str):
    reader = STEPControl_Reader()
    status = reader.ReadFile(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEP 读取失败 (status={status}): {path}")
    reader.TransferRoots()
    shape = reader.OneShape()
    if shape.IsNull():
        raise RuntimeError(f"STEP 内容为空: {path}")
    return shape


def _count(shape, kind) -> int:
    exp = TopExp_Explorer(shape, kind)
    n = 0
    while exp.More():
        n += 1
        exp.Next()
    return n


def shape_stats(shape) -> Dict[str, int]:
    return {
        "solids": _count(shape, TopAbs_SOLID),
        "shells": _count(shape, TopAbs_SHELL),
        "faces": _count(shape, TopAbs_FACE),
        "edges": _count(shape, TopAbs_EDGE),
        "vertices": _count(shape, TopAbs_VERTEX),
    }


def is_valid(shape) -> bool:
    try:
        return bool(BRepCheck_Analyzer(shape).IsValid())
    except Exception:
        return False


def bbox3d(shape) -> Tuple[Tuple[float, float, float], Tuple[float, float, float]]:
    box = Bnd_Box()
    BRepBndLib.Add_s(shape, box)
    xmin, ymin, zmin, xmax, ymax, zmax = box.Get()
    return (xmin, ymin, zmin), (xmax, ymax, zmax)


# ------------------------------------------------------------------ 视图轴系
def _unit(v: Tuple[float, float, float]) -> Tuple[float, float, float]:
    n = math.sqrt(sum(c * c for c in v))
    if n < 1e-12:
        raise ValueError("零向量无法归一化")
    return tuple(c / n for c in v)


def _cross(a, b):
    return (
        a[1] * b[2] - a[2] * b[1],
        a[2] * b[0] - a[0] * b[2],
        a[0] * b[1] - a[1] * b[0],
    )


def _neg(a):
    return (-a[0], -a[1], -a[2])


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1] + a[2] * b[2]


AXIS_VECTORS = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}


def view_axes(front: str = "+Y", up: str = "+Z") -> Dict[str, Tuple[tuple, tuple]]:
    """按第一角投影约定，由主视图方向推导其余视图的 (视线方向 d, 屏幕向上 u)。

    d 由物体指向观察者；屏幕右向量 r = u × d，且满足 r × u = d。
    """
    f = _unit(AXIS_VECTORS[front])
    u = _unit(AXIS_VECTORS[up])
    if abs(_dot(f, u)) > 1e-6:
        raise ValueError(f"主视图方向 {front} 与向上方向 {up} 不能平行")
    # 重新正交化
    r = _unit(_cross(u, f))
    u = _unit(_cross(f, r))

    return {
        "front": (f, u),
        "back": (_neg(f), u),
        "left": (_neg(r), u),
        "right": (r, u),
        "top": (u, _neg(f)),
        "bottom": (_neg(u), f),
    }


def iso_axes(
    front: str = "+Y",
    up: str = "+Z",
    azimuth_deg: float = 45.0,
    elevation_deg: float = 35.264,
) -> Tuple[tuple, tuple]:
    """等轴测/侧 45° 立体图轴系。"""
    axes = view_axes(front, up)
    f, u = axes["front"]
    r = _unit(_cross(u, f))
    az = math.radians(azimuth_deg)
    el = math.radians(elevation_deg)
    d = _unit(
        (
            f[0] * math.cos(el) * math.cos(az) + r[0] * math.cos(el) * math.sin(az) + u[0] * math.sin(el),
            f[1] * math.cos(el) * math.cos(az) + r[1] * math.cos(el) * math.sin(az) + u[1] * math.sin(el),
            f[2] * math.cos(el) * math.cos(az) + r[2] * math.cos(el) * math.sin(az) + u[2] * math.sin(el),
        )
    )
    # 屏幕向上取世界 up 在垂直 d 平面上的投影
    up_proj = _unit((u[0] - _dot(u, d) * d[0], u[1] - _dot(u, d) * d[1], u[2] - _dot(u, d) * d[2]))
    return d, up_proj


# ------------------------------------------------------------------ HLR 投影
def project_visible(shape, d, u, deflection: float = 0.05) -> List[Polyline]:
    """对给定视线方向做隐藏线消除，返回可见轮廓的 2D 折线集合。

    投影平面的 X 轴取屏幕右向量 r = u × d，Y 轴即 u，
    因此返回的 (x, y) 就是 (屏幕右, 屏幕上)，符合制图习惯。
    """
    r = _unit(_cross(u, d))
    ax2 = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*d), gp_Dir(*r))
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(HLRAlgo_Projector(ax2))
    algo.Update()
    try:
        algo.Hide()
    except Exception:
        pass  # OCCT 7.8+ 已内置，无需显式调用

    hlr = HLRBRep_HLRToShape(algo)
    parts = []
    for name in ("VCompound", "Rg1LineVCompound", "OutLineVCompound"):
        try:
            sub = getattr(hlr, name)()
        except Exception:
            continue
        if sub is None or sub.IsNull():
            continue
        parts.extend(_edges_to_polylines(sub, deflection))
    return parts


def _edges_to_polylines(shape, deflection: float) -> List[Polyline]:
    polys: List[Polyline] = []
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        try:
            edge = TopoDS.Edge_s(exp.Current())
            adaptor = BRepAdaptor_Curve(edge)
            disc = GCPnts_QuasiUniformDeflection(adaptor, deflection)
            if disc.IsDone() and disc.NbPoints() >= 2:
                pts: Polyline = []
                for i in range(1, disc.NbPoints() + 1):
                    p = disc.Value(i)
                    pts.append((p.X(), p.Y()))
                polys.append(pts)
        except Exception:
            pass
        exp.Next()
    return polys


def polyline_bbox(polys: List[Polyline]) -> BBox:
    xs = [x for p in polys for x, _ in p]
    ys = [y for p in polys for _, y in p]
    if not xs:
        return (0.0, 0.0, 0.0, 0.0)
    return (min(xs), min(ys), max(xs), max(ys))


# ------------------------------------------------------------------ 投影模式
def split_solids(shape) -> list:
    """把形状拆成实体列表。"""
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    out = []
    while exp.More():
        out.append(TopoDS.Solid_s(exp.Current()))
        exp.Next()
    return out


def project_by_mode(shape, d, u, mode: str = "composite", deflection: float = 0.05):
    """按模式投影。

    composite : 整体一次 HLR（内部被遮挡；但无效几何可能丢边）
    hybrid    : 精确 Algo 的 V+Rg1 + PolyAlgo 的 OutLine（推荐：轮廓完整 + 内部干净）
    per_solid : 逐实体分别 HLR 后合并（轮廓完整；但内部结构会暴露）
    """
    if mode == "hybrid":
        return project_hybrid(shape, d, u, deflection)
    if mode != "per_solid":
        return project_visible_full(shape, d, u, deflection)

    sols = split_solids(shape)
    if len(sols) <= 1:
        return project_visible_full(shape, d, u, deflection)

    primitives: List[dict] = []
    polylines: List[Polyline] = []
    for s in sols:
        p1, p2 = project_visible_full(s, d, u, deflection)
        primitives.extend(p1)
        polylines.extend(p2)
    return primitives, polylines


def project_outline_only(shape, d, u, deflection: float = 0.05, use_poly: bool = False):
    """只投影剪影线（OutLineVCompound），用于覆盖度参照和混合策略。

    use_poly=True 时用 PolyAlgo（网格化 HLR），对无效几何更稳健。
    """
    r = _unit(_cross(u, d))
    ax2 = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*d), gp_Dir(*r))

    if use_poly:
        from OCP.BRepMesh import BRepMesh_IncrementalMesh
        from OCP.HLRBRep import HLRBRep_PolyAlgo, HLRBRep_PolyHLRToShape
        mesh = BRepMesh_IncrementalMesh(shape, 0.1)
        mesh.Perform()
        algo = HLRBRep_PolyAlgo(shape)
        algo.Projector(HLRAlgo_Projector(ax2))
        algo.Update()
        try:
            algo.Hide()
        except Exception:
            pass
        hlr = HLRBRep_PolyHLRToShape()
        hlr.Update(algo)
    else:
        algo = HLRBRep_Algo()
        algo.Add(shape)
        algo.Projector(HLRAlgo_Projector(ax2))
        algo.Update()
        try:
            algo.Hide()
        except Exception:
            pass
        hlr = HLRBRep_HLRToShape(algo)

    prims, polys = [], []
    try:
        sub = hlr.OutLineVCompound()
        if sub and not sub.IsNull():
            _collect_edges(sub, deflection, prims, polys)
    except Exception:
        pass
    return prims, polys


def _dedup_polylines(polys: List[Polyline], tol: float = 0.3) -> List[Polyline]:
    """2D 去重：两条折线的**两端都匹配**（正序或反序）才视为重复，删除后者。

    仅共享一个端点的不同边不会被删除（它们是不同的几何）。
    """
    if len(polys) <= 1:
        return polys
    import math

    def close(p, q):
        return math.hypot(p[0] - q[0], p[1] - q[1]) < tol

    kept: List[Polyline] = []
    for pl in polys:
        if len(pl) < 2:
            kept.append(pl)
            continue
        a, b = pl[0], pl[-1]
        dup = False
        for other in kept:
            if len(other) < 2:
                continue
            c, d = other[0], other[-1]
            # 两端都匹配（正序 a≈c 且 b≈d，或反序 a≈d 且 b≈c）才算重复
            if (close(a, c) and close(b, d)) or (close(a, d) and close(b, c)):
                dup = True
                break
        if not dup:
            kept.append(pl)
    return kept


def project_hybrid(shape, d, u, deflection: float = 0.05):
    """混合 HLR：精确 Algo 的 V+Rg1 + PolyAlgo 的 OutLine，2D 去重。

    对有效几何：两种算法的剪影线重合，去重后等价于精确 Algo。
    对无效几何：精确 Algo 丢剪影，PolyAlgo 补上，去重后不重复。
    内部线条来自精确 Algo（被正确遮挡，干净）。
    """
    # 精确 Algo：V + Rg1（不含 OutLine，OutLine 由 PolyAlgo 提供）
    prims_exact, polys_vr = _project_named(shape, d, u,
                                           ["VCompound", "Rg1LineVCompound"], deflection)
    # PolyAlgo：OutLine（对无效几何更稳健）
    prims_poly, polys_ol = project_outline_only(shape, d, u, deflection, use_poly=True)

    # 合并 + 去重
    all_polys = _dedup_polylines(list(polys_vr) + list(polys_ol), tol=0.3)
    all_prims = list(prims_exact) + list(prims_poly)
    return all_prims, all_polys


def _project_named(shape, d, u, names, deflection=0.05):
    """用精确 HLRBRep_Algo 投影指定类别的边。"""
    r = _unit(_cross(u, d))
    ax2 = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*d), gp_Dir(*r))
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(HLRAlgo_Projector(ax2))
    algo.Update()
    try:
        algo.Hide()
    except Exception:
        pass
    hlr = HLRBRep_HLRToShape(algo)
    prims, polys = [], []
    for name in names:
        try:
            sub = getattr(hlr, name)()
        except Exception:
            continue
        if sub is None or sub.IsNull():
            continue
        _collect_edges(sub, deflection, prims, polys)
    return prims, polys


def outline_coverage(ref_polys: List[Polyline], cand_polys: List[Polyline],
                     tol: float = 1.0) -> float:
    """评估 cand 对 ref 外边界包络的覆盖率（0~1），用于检测"丢线"。

    ref  : 逐实体投影结果（作为"应可见轮廓"的参照）
    cand : 实际输出结果
    做法  : 取 ref 的逐行/逐列极值点构成包络；检查这些点附近 tol 内是否有 cand 的点。

    tol 取 1.0mm 是标定结果：正常模型 100%、已知丢线模型 82.6%，
    0.35mm 会因离散/抗锯齿误判（正常模型仅 88.8%），不宜用。
    """
    import numpy as np

    if not ref_polys or not cand_polys:
        return 1.0
    ref = np.array([pt for pl in ref_polys for pt in pl], dtype=float)
    cand = np.array([pt for pl in cand_polys for pt in pl], dtype=float)
    if ref.size == 0 or cand.size == 0:
        return 1.0

    x0, y0 = ref.min(axis=0)
    x1, y1 = ref.max(axis=0)
    res = max(tol, 1e-6)
    W = max(2, int((x1 - x0) / res) + 3)
    H = max(2, int((y1 - y0) / res) + 3)

    mask = np.zeros((H, W), dtype=bool)
    ix = np.clip(((cand[:, 0] - x0) / res + 1).astype(int), 0, W - 1)
    iy = np.clip(((cand[:, 1] - y0) / res + 1).astype(int), 0, H - 1)
    mask[iy, ix] = True
    # 膨胀一格（等价 tol 容差）
    m2 = mask.copy()
    m2[1:, :] |= mask[:-1, :]
    m2[:-1, :] |= mask[1:, :]
    m2[:, 1:] |= mask[:, :-1]
    m2[:, :-1] |= mask[:, 1:]

    # ref 的包络点：每行的 x 极值 + 每列的 y 极值；逐点检查 cand 是否覆盖
    rix = np.clip(((ref[:, 0] - x0) / res + 1).astype(int), 0, W - 1)
    riy = np.clip(((ref[:, 1] - y0) / res + 1).astype(int), 0, H - 1)

    covered = 0
    total = 0
    for grid, coord, row_major in ((riy, rix, True), (rix, riy, False)):
        order = np.argsort(grid, kind="stable")
        g_sorted, c_sorted = grid[order], coord[order]
        _uniq, starts = np.unique(g_sorted, return_index=True)
        ends = np.append(starts[1:], len(g_sorted))
        for st, en in zip(starts, ends):
            c_vals = c_sorted[st:en]
            g = int(g_sorted[st])
            for cc in (int(c_vals.min()), int(c_vals.max())):
                yy, xx = (g, cc) if row_major else (cc, g)
                total += 1
                if 0 <= yy < H and 0 <= xx < W and m2[yy, xx]:
                    covered += 1
    return covered / total if total else 1.0


# ------------------------------------------------------------------ 原生图元提取（供 DXF 用）
def project_visible_full(shape, d, u, deflection: float = 0.05):
    """HLR 投影，同时返回「原生图元」与「离散折线」。

    原生图元保留几何语义（直线→LINE，圆弧→ARC，整圆→CIRCLE），
    这样导出的 DXF 在 CAD 里可以按几何编辑（改半径、拉伸端点），
    而不是一堆碎线段。只有样条/其他曲线才退化为多段线。

    返回
    ----
    primitives : list[dict]  见下方 kind 说明
    polylines  : list[list[(x,y)]]  用于位图渲染
    """
    r = _unit(_cross(u, d))
    ax2 = gp_Ax2(gp_Pnt(0, 0, 0), gp_Dir(*d), gp_Dir(*r))
    algo = HLRBRep_Algo()
    algo.Add(shape)
    algo.Projector(HLRAlgo_Projector(ax2))
    algo.Update()
    try:
        algo.Hide()
    except Exception:
        pass

    hlr = HLRBRep_HLRToShape(algo)
    primitives: List[dict] = []
    polylines: List[Polyline] = []
    for name in ("VCompound", "Rg1LineVCompound", "OutLineVCompound"):
        try:
            sub = getattr(hlr, name)()
        except Exception:
            continue
        if sub is None or sub.IsNull():
            continue
        _collect_edges(sub, deflection, primitives, polylines)
    return primitives, polylines


def _collect_edges(shape, deflection: float, primitives: List[dict], polylines: List[Polyline]):
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        try:
            edge = TopoDS.Edge_s(exp.Current())
            ad = BRepAdaptor_Curve(edge)
            t = ad.GetType()
            t_first, t_last = ad.FirstParameter(), ad.LastParameter()

            if t == GeomAbs_Line:
                p1, p2 = ad.Value(t_first), ad.Value(t_last)
                a = (p1.X(), p1.Y())
                b = (p2.X(), p2.Y())
                primitives.append({"kind": "line", "a": a, "b": b})
                polylines.append([a, b])

            elif t == GeomAbs_Circle:
                circ = ad.Circle()
                c = (circ.Location().X(), circ.Location().Y())
                rad = circ.Radius()
                p_s, p_e = ad.Value(t_first), ad.Value(t_last)
                a_s = math.atan2(p_s.Y() - c[1], p_s.X() - c[0])
                a_e = math.atan2(p_e.Y() - c[1], p_e.X() - c[0])
                sweep = abs(t_last - t_first)
                if sweep >= 2 * math.pi - 1e-6:
                    primitives.append({"kind": "circle", "c": c, "r": rad})
                else:
                    # 用中点判断圆弧走向，DXF ARC 恒为逆时针
                    tm = (t_first + t_last) / 2.0
                    p_m = ad.Value(tm)
                    a_m = math.atan2(p_m.Y() - c[1], p_m.X() - c[0])
                    s_ccw = (a_e - a_s) % (2 * math.pi)
                    m_ccw = (a_m - a_s) % (2 * math.pi)
                    if m_ccw <= s_ccw:
                        start, end = a_s, a_e
                    else:
                        start, end = a_e, a_s
                    primitives.append(
                        {"kind": "arc", "c": c, "r": rad, "start": start, "end": end}
                    )
                poly = _discretize(ad, deflection)
                if len(poly) >= 2:
                    polylines.append(poly)

            else:
                poly = _discretize(ad, deflection)
                if len(poly) >= 2:
                    primitives.append({"kind": "polyline", "pts": poly})
                    polylines.append(poly)
        except Exception:
            pass
        exp.Next()


def _discretize(adaptor, deflection: float) -> Polyline:
    try:
        disc = GCPnts_QuasiUniformDeflection(adaptor, deflection)
        if disc.IsDone() and disc.NbPoints() >= 2:
            return [(disc.Value(i).X(), disc.Value(i).Y()) for i in range(1, disc.NbPoints() + 1)]
    except Exception:
        pass
    return []
