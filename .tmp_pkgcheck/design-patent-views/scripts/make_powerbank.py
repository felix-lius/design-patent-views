# -*- coding: utf-8 -*-
"""生成充电宝示例模型（外形接近真实产品，用于验证链路）。

说明：公开渠道未找到可直接下载的充电宝整机 STEP，故按典型产品参数建模：
圆角矩形机身 + USB-C 输入口 + USB-A 输出口 + 侧边电源键 + 正面电量指示灯。
这类"箱体 + 开孔 + 圆角"正是外观设计专利最常见的形态，验证价值高。
"""
import os

from OCP.BRepAlgoAPI import BRepAlgoAPI_Cut
from OCP.BRepFilletAPI import BRepFilletAPI_MakeFillet
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakeCylinder
from OCP.IFSelect import IFSelect_RetDone
from OCP.STEPControl import STEPControl_AsIs, STEPControl_Writer
from OCP.TopAbs import TopAbs_EDGE
from OCP.TopExp import TopExp_Explorer
from OCP.TopoDS import TopoDS
from OCP.gp import gp_Ax2, gp_Dir, gp_Pnt

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "examples", "powerbank.step")

# 机身 105(x) × 68(y) × 26(z)，以原点为中心、底面 z=0
L, W, H = 105.0, 68.0, 26.0


def build():
    body = BRepPrimAPI_MakeBox(gp_Pnt(-L / 2, -W / 2, 0), L, W, H).Shape()

    # 竖直四条棱倒圆角 R8（只选竖直方向边，避免布尔后选边失败）
    fillet = BRepFilletAPI_MakeFillet(body)
    exp = TopExp_Explorer(body, TopAbs_EDGE)
    picked = 0
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        try:
            from OCP.BRepAdaptor import BRepAdaptor_Curve
            ad = BRepAdaptor_Curve(edge)
            p1 = ad.Value(ad.FirstParameter())
            p2 = ad.Value(ad.LastParameter())
            # 竖直边：两端点 x,y 基本相同、z 不同
            if abs(p1.X() - p2.X()) < 1e-6 and abs(p1.Y() - p2.Y()) < 1e-6 and abs(p1.Z() - p2.Z()) > 1.0:
                fillet.Add(8.0, edge)
                picked += 1
        except Exception:
            pass
        exp.Next()
    if picked:
        body = fillet.Shape()
    print(f"  vertical fillet on {picked} edges")

    cuts = []
    # 底部 USB-C 接口（扁孔）
    cuts.append(BRepPrimAPI_MakeBox(gp_Pnt(-9, -W / 2 - 1, 4), 18, 5, 8).Shape())
    # 底部 USB-A 接口
    cuts.append(BRepPrimAPI_MakeBox(gp_Pnt(14, -W / 2 - 1, 5), 14, 5, 12).Shape())
    # 侧边电源键凹槽
    cuts.append(BRepPrimAPI_MakeBox(gp_Pnt(L / 2 - 1, -8, 9), 5, 16, 6).Shape())
    # 正面电量指示灯（4 个圆形浅孔）
    for i, x in enumerate([-22, -12, -2, 8]):
        cuts.append(
            BRepPrimAPI_MakeCylinder(
                gp_Ax2(gp_Pnt(x, -W / 2, H - 4), gp_Dir(0, 1, 0)), 2.2, 3.0
            ).Shape()
        )

    for c in cuts:
        body = BRepAlgoAPI_Cut(body, c).Shape()
    print(f"  applied {len(cuts)} cutouts")
    return body


def export(shape, path):
    w = STEPControl_Writer()
    w.Transfer(shape, STEPControl_AsIs)
    if w.Write(path) != IFSelect_RetDone:
        raise RuntimeError("STEP write failed")
    print("written:", path, os.path.getsize(path), "bytes")


if __name__ == "__main__":
    export(build(), OUT)
