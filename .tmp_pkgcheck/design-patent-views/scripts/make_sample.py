# -*- coding: utf-8 -*-
"""生成一个用于验证链路的示例产品 STEP 模型。

形状刻意做得像"外观设计产品"：带圆角的机身 + 顶部圆形按键 + 侧面凹槽，
用来检验 HLR 能否正确处理曲面轮廓线、圆角相切边、内凹可见边。
"""
import os
import sys

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut, BRepAlgoAPI_Fuse
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(BASE, "examples")
os.makedirs(OUT_DIR, exist_ok=True)
OUT_STEP = os.path.join(OUT_DIR, "sample_product.step")


def build():
    # 机身 100 × 62 × 22
    body = BRepPrimAPI_MakeBox(gp_Pnt(-50, -31, 0), 100, 62, 22).Shape()

    # 顶部圆形按键（凸起）
    btn = BRepPrimAPI_MakeCylinder(gp_Ax2(gp_Pnt(0, 0, 22), gp_Dir(0, 0, 1)), 14, 5).Shape()
    body = BRepAlgoAPI_Fuse(body, btn).Shape()

    # 正面横向凹槽
    slot = BRepPrimAPI_MakeBox(gp_Pnt(-38, -32, 12), 76, 6, 5).Shape()
    body = BRepAlgoAPI_Cut(body, slot).Shape()

    # 背面接口孔
    hole = BRepPrimAPI_MakeCylinder(
        gp_Ax2(gp_Pnt(30, 31, 11), gp_Dir(0, 1, 0)), 5, 6
    ).Shape()
    body = BRepAlgoAPI_Cut(body, hole).Shape()

    # 对竖直棱边做圆角，检验相切边/轮廓线
    fillet = BRepFilletAPI_MakeFillet(body)
    exp = TopExp_Explorer(body, TopAbs_EDGE)
    n = 0
    while exp.More():
        edge = exp.Current()
        try:
            fillet.Add(6.0, edge)
            n += 1
        except Exception:
            pass
        exp.Next()
    try:
        body = fillet.Shape()
        print(f"fillet applied on {n} edges")
    except Exception as e:
        print("fillet skipped:", e)
    return body


def export(shape, path):
    writer = STEPControl_Writer()
    writer.Transfer(shape, STEPControl_AsIs)
    status = writer.Write(path)
    if status != IFSelect_RetDone:
        raise RuntimeError(f"STEP write failed: {status}")
    print("written:", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    shape = build()
    export(shape, OUT_STEP)
