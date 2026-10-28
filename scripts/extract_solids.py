# -*- coding: utf-8 -*-
"""实体清单与筛选工具。

用途
----
真实客户模型常是完整工程装配体（外壳 + 底盖 + 内部支架 + 按键 …），
直接投影会把内部结构画进外观图，违反外观设计"仅表达可见外观"的要求。

本工具做两件事：
  1. list  —— 列出每个实体的序号、面数、尺寸、包围盒，供人工挑选
  2. keep  —— 只保留指定序号的实体，另存为新的 STEP，再走主链路出图

用法
----
    python extract_solids.py list  examples/spacemouse.step
    python extract_solids.py keep  examples/spacemouse.step 0,8,9  examples/spacemouse_shell.step
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import geom_core as geom
from OCP.BRep import BRep_Builder
from OCP.BRepBndLib import BRepBndLib
from OCP.Bnd import Bnd_Box
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_SOLID
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS


def solids(shape):
    """按包围盒体积降序返回 [(原序号, solid, 尺寸, 包围盒)]。"""
    exp = TopExp_Explorer(shape, TopAbs_SOLID)
    out = []
    i = 0
    while exp.More():
        s = TopoDS.Solid_s(exp.Current())
        box = Bnd_Box()
        BRepBndLib.Add_s(s, box)
        bb = box.Get()
        dim = (bb[3] - bb[0], bb[4] - bb[1], bb[5] - bb[2])
        out.append((i, s, dim, bb))
        i += 1
        exp.Next()
    return out


def cmd_list(path: str):
    sh = geom.load_step(path)
    items = sorted(solids(sh), key=lambda r: -(r[2][0] * r[2][1] * r[2][2]))
    print(f"{len(items)} 个实体（按体积降序）")
    print(f"{'idx':<5}{'faces':<7}{'尺寸 X×Y×Z (mm)':<28}{'包围盒 z':<20}")
    print("-" * 66)
    for idx, s, dim, bb in items:
        nf = geom.shape_stats(s)["faces"]
        print(f"{idx:<5}{nf:<7}{dim[0]:6.1f} ×{dim[1]:6.1f} ×{dim[2]:6.1f}      "
              f"z[{bb[2]:6.1f},{bb[5]:6.1f}]")


def cmd_keep(src: str, keep_idx: str, dst: str):
    sh = geom.load_step(src)
    want = {int(x) for x in keep_idx.split(",") if x.strip() != ""}
    builder = BRep_Builder()
    from OCP.TopoDS import TopoDS_Compound
    comp = TopoDS_Compound()
    builder.MakeCompound(comp)
    kept = 0
    for idx, s, dim, bb in solids(sh):
        if idx in want:
            builder.Add(comp, s)
            kept += 1
    if kept == 0:
        raise SystemExit("没有匹配的实体序号")
    w = STEPControl_Writer()
    w.Transfer(comp, STEPControl_AsIs)
    if w.Write(dst) != IFSelect_RetDone:
        raise SystemExit("写出失败")
    print(f"保留 {kept} 个实体 -> {dst} ({os.path.getsize(dst)} bytes)")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__)
        raise SystemExit(2)
    cmd = sys.argv[1]
    if cmd == "list":
        cmd_list(sys.argv[2])
    elif cmd == "keep":
        cmd_keep(sys.argv[2], sys.argv[3], sys.argv[4])
    else:
        print(__doc__)
        raise SystemExit(2)
