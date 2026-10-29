# -*- coding: utf-8 -*-
"""生成《六视图生成流程图》SVG。

为什么要用脚本生成而不是手写 SVG
--------------------------------
手写时每个框/箭头的坐标都是散落的魔法数字，改一个字就要重排全图，
结果是"线穿框""底部文字压边框"这类问题永远修不干净。这里把布局
参数化：改一个 y 值，下面的元素整体让位，连线自动跟着走。

输出：六视图生成流程图.svg（仓库根目录）
"""
from __future__ import annotations

import os
import sys

# ---------------------------------------------------------------- 样式
C_BOX_FILL, C_BOX_STROKE = "#dae8fc", "#6c8ebf"      # 自动化处理
C_OK_FILL, C_OK_STROKE = "#d5e8d4", "#82b366"        # 交付
C_PART_FILL, C_PART_STROKE = "#e1d5e7", "#9673a6"    # 局部外观
C_HUMAN_FILL, C_HUMAN_STROKE = "#ffe6cc", "#d79b00"  # 人工确认点
C_ERR_FILL, C_ERR_STROKE = "#f8cecc", "#b85450"      # 异常
C_LINE = "#475569"
C_TITLE = "#1e293b"
C_TEXT = "#475569"

W = 1000
CX = 500


def esc(s: str) -> str:
    return (s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


class SVG:
    def __init__(self):
        self.parts: list[str] = []

    def add(self, s: str):
        self.parts.append(s)

    def rect(self, x, y, w, h, fill, stroke, rx=8, dash=None):
        d = f' stroke-dasharray="{dash}"' if dash else ""
        self.add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"{d}/>')

    def text(self, x, y, s, size=12, fill=C_TEXT, bold=False, anchor="middle"):
        w = ' font-weight="bold"' if bold else ""
        self.add(f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"'
                 f' fill="{fill}"{w}>{esc(s)}</text>')

    def lines(self, cx, y0, items, size=12, fill=C_TEXT, lh=17, bold_first=False):
        for i, s in enumerate(items):
            self.text(cx, y0 + i * lh, s, size=size, fill=fill,
                      bold=(bold_first and i == 0))

    def box(self, x, y, w, h, title, sub=(), fill=C_BOX_FILL, stroke=C_BOX_STROKE,
            size=13):
        self.rect(x, y, w, h, fill, stroke)
        cy = y + h / 2
        n = len(sub)
        first = cy - (n * 17) / 2 + (0 if n else 5)
        self.text(x + w / 2, first, title, size=size, fill=C_TITLE, bold=True)
        for i, s in enumerate(sub):
            self.text(x + w / 2, first + 19 + i * 17, s, size=11, fill=C_TEXT)

    def diamond(self, cx, cy, w, h, title, sub=(), fill=C_HUMAN_FILL,
                stroke=C_HUMAN_STROKE, size=12):
        pts = f"{cx},{cy-h/2} {cx+w/2},{cy} {cx},{cy+h/2} {cx-w/2},{cy}"
        self.add(f'<polygon points="{pts}" fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        if sub:
            self.text(cx, cy - 2, title, size=size, fill=C_TITLE, bold=True)
            self.text(cx, cy + 15, sub[0], size=10, fill=C_TEXT)
        else:
            self.text(cx, cy + 4, title, size=size, fill=C_TITLE, bold=True)

    def ellipse(self, cx, cy, rx, ry, title, fill=C_OK_FILL, stroke=C_OK_STROKE, size=13):
        self.add(f'<ellipse cx="{cx}" cy="{cy}" rx="{rx}" ry="{ry}" '
                 f'fill="{fill}" stroke="{stroke}" stroke-width="1.5"/>')
        self.text(cx, cy + 5, title, size=size, fill=C_TITLE, bold=True)

    def arrow(self, pts, color=C_LINE, dash=None, head=True, label=None,
              label_at=None):
        """折线箭头。pts 为 [(x,y), ...]，最后一段带箭头。"""
        d = " ".join(f"{'M' if i == 0 else 'L'} {x} {y}" for i, (x, y) in enumerate(pts))
        da = f' stroke-dasharray="{dash}"' if dash else ""
        marker = ""
        if head:
            marker = ' marker-end="url(#arrowred)"' if color == C_ERR_STROKE else ' marker-end="url(#arrow)"'
        self.add(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.5"'
                 f'{da}{marker}/>')
        if label and label_at:
            self.text(label_at[0], label_at[1], label, size=11, fill=color)


def build() -> str:
    s = SVG()
    s.add(f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="1560" '
          f'viewBox="0 0 {W} 1560" font-family="Microsoft YaHei, PingFang SC, sans-serif">')
    s.add('<defs>')
    for mid, col in (("arrow", C_LINE), ("arrowred", C_ERR_STROKE)):
        s.add(f'<marker id="{mid}" viewBox="0 0 10 10" refX="9" refY="5" '
              f'markerWidth="7" markerHeight="7" orient="auto-start-reverse">'
              f'<path d="M 0 0 L 10 5 L 0 10 z" fill="{col}"/></marker>')
    s.add('</defs>')
    s.add(f'<rect width="{W}" height="1560" fill="#ffffff"/>')

    # ---------------- 标题 ----------------
    s.text(CX, 44, "外观设计专利视图自动生成 — 实现流程图", size=22, fill=C_TITLE, bold=True)
    s.text(CX, 70, "六视图 + 立体图 + JPEG 提交件 + 可编辑 DXF ｜ 全程本地运行，模型不上传",
           size=13, fill=C_TEXT)

    # ---------------- 主链路 ----------------
    s.ellipse(CX, 118, 96, 22, "开始：本地批处理")

    s.arrow([(CX, 140), (CX, 158)])

    s.box(300, 158, 400, 66, "输入准备", [
        "STEP / STP 模型文件",
        "产品名 / 用途 / 主视图方位 / 上方向",
    ])

    s.arrow([(CX, 224), (CX, 242)])

    s.box(270, 242, 460, 78, "① 输入解析与校验", [
        "STEP → OCP 载入（B-Rep 实体拓扑）",
        "逐实体 BRepCheck：破面 / 自交 → 警告不中断",
        "格式校验：仅接受 .step / .stp",
    ])

    # 失败分支
    s.arrow([(730, 281), (752, 281)], color=C_ERR_STROKE, dash="6,4")
    s.box(752, 250, 208, 62, "失败 → 错误报告", [
        "非 STEP / 文件截断 / 无法解析",
        "不进入后续步骤",
    ], fill=C_ERR_FILL, stroke=C_ERR_STROKE, size=12)

    s.arrow([(CX, 320), (CX, 338)])

    s.diamond(CX, 366, 250, 56, "人工确认点 ①", ("核对主视图方位",))

    s.arrow([(CX, 394), (CX, 412)])

    s.box(260, 412, 480, 78, "② 几何预处理", [
        "按主视图方位定轴系 → 计算包围盒",
        "推导六视图方位 + 统一比例（六视图共用 scale）",
        "投影一致性自校验（长对正 / 高平齐 / 宽相等）",
    ])

    s.arrow([(CX, 490), (CX, 508)])

    s.diamond(CX, 536, 240, 56, "出图模式", ("整体 / 局部外观",),
              fill=C_PART_FILL, stroke=C_PART_STROKE)

    s.arrow([(620, 536), (742, 536)], color=C_PART_STROKE, dash="6,4")
    s.box(742, 498, 218, 76, "局部外观模式", [
        "实线 = 要求保护的局部",
        "虚线 = 其他部分",
        "无明确分界线 → 点划线",
    ], fill=C_PART_FILL, stroke=C_PART_STROKE, size=12)

    s.arrow([(CX, 564), (CX, 582)])

    s.diamond(CX, 602, 116, 34, "并行", fill="#f5f5f5", stroke="#999999", size=11)

    # 并行分支
    s.arrow([(442, 602), (350, 602), (350, 626)])
    s.arrow([(558, 602), (650, 602), (650, 626)])

    s.box(200, 626, 300, 84, "③a 六视图（正交投影）", [
        "OCP HLR 隐藏线消除",
        "主 / 后 / 左 / 右 / 俯 / 仰",
        "关闭隐藏线（虚线禁用）",
    ])
    s.box(500, 626, 300, 84, "③b 立体图（等轴测线框）", [
        "方位 45° / 仰角 35.264°",
        "线框图，不用着色渲染",
        "比例独立（不受六视图约束）",
    ])

    # 汇合：两条分支线先并到中线，再由一条带箭头的线向下（否则两个箭头会顶在一起）
    s.arrow([(350, 710), (350, 736), (CX, 736)], head=False)
    s.arrow([(650, 710), (650, 736), (CX, 736)], head=False)
    s.arrow([(CX, 736), (CX, 754)])

    s.box(270, 754, 460, 92, "④ 专利规范化处理（官方规格固化）", [
        "统一线宽实线（0.25–0.50mm），无多余线条",
        "版面 150×220mm @300DPI → 1772×2598 px，JPEG",
        "产品图形 ≥ 3cm×8cm（细长物品除外）",
        "提交件中文命名：1-主视图 … 7-立体图",
    ])

    s.arrow([(CX, 846), (CX, 864)])

    s.box(262, 864, 476, 92, "⑤ 合规自检（33 项硬性校验）", [
        "格式：JPEG / DPI / 像素区间 / 总大小 ≤ 30MB",
        "线条：线型禁令、线宽统一、图内无文字与图号",
        "视图：数量、命名、长对正 / 高平齐 / 宽相等",
        "清晰度：缩小 2/3 可辨、轮廓完整性（人工复核）",
    ])

    # 不合规回路（不穿框：从右侧走）
    s.arrow([(738, 910), (760, 910)], color=C_ERR_STROKE, dash="6,4")
    s.box(760, 872, 200, 76, "不合规 → 返回修正", [
        "自动重出图（换比例 / 线宽）",
        "仍不合规 → 转人工复核",
    ], fill=C_ERR_FILL, stroke=C_ERR_STROKE, size=12)

    s.arrow([(CX, 956), (CX, 974)])

    s.diamond(CX, 1002, 210, 56, "合规通过？", fill="#fff2cc", stroke="#d6b656")

    s.arrow([(605, 1002), (860, 1002), (860, 950)], color=C_ERR_STROKE, dash="6,4")
    s.text(700, 994, "否", size=11, fill=C_ERR_STROKE)

    s.arrow([(CX, 1030), (CX, 1048)])
    s.text(512, 1044, "是", size=11, fill=C_LINE, anchor="start")

    s.box(250, 1048, 500, 92, "⑥ 交付", [
        "output/<产品名>/submission/  →  7 张 JPEG 提交件（可直接上传）",
        "output/<产品名>/all_views.dxf  →  1:1 mm 可编辑矢量",
        "logs/05_<name>.json  →  33 项合规自检报告",
        "每个模型一个独立目录，同名自动加序号，不互相覆盖",
    ], fill=C_OK_FILL, stroke=C_OK_STROKE)

    s.arrow([(CX, 1140), (CX, 1158)])

    s.diamond(CX, 1186, 260, 56, "人工确认点 ②", ("按自检报告与图面复核",))

    s.arrow([(CX, 1214), (CX, 1232)])

    s.ellipse(CX, 1258, 128, 24, "结束：可用于专利申请提交")

    # ---------------- 图例 ----------------
    ly = 1310
    s.rect(40, ly, 920, 104, "#f8fafc", "#cbd5e1", rx=10)
    s.text(70, ly + 26, "图例", size=13, fill=C_TITLE, bold=True, anchor="start")
    items = [
        (70, C_BOX_FILL, C_BOX_STROKE, "自动化处理（OCP / Python）"),
        (390, C_OK_FILL, C_OK_STROKE, "交付物"),
        (650, C_PART_FILL, C_PART_STROKE, "局部外观模式"),
    ]
    for x, f, st, label in items:
        s.rect(x, ly + 38, 26, 16, f, st, rx=3)
        s.text(x + 36, ly + 51, label, size=11, fill=C_TEXT, anchor="start")
    s.diamond(83, ly + 76, 26, 16, "", fill=C_HUMAN_FILL, stroke=C_HUMAN_STROKE)
    s.text(106, ly + 81, "人工确认点", size=11, fill=C_TEXT, anchor="start")
    s.rect(390, ly + 68, 26, 16, C_ERR_FILL, C_ERR_STROKE, rx=3)
    s.text(426, ly + 81, "异常 / 不合规分支（含返回修正回路）", size=11,
           fill=C_TEXT, anchor="start")
    s.text(650, ly + 81, "红色虚线 = 异常路径", size=11, fill=C_ERR_STROKE, anchor="start")

    # ---------------- 包结构 ----------------
    py = 1444
    s.text(40, py, "实现文件（scripts/）：", size=12, fill=C_TITLE, bold=True, anchor="start")
    s.text(40, py + 22,
           "patent_cli.py 命令行主入口 ／ spec.py 合规常量 ／ pipeline.py 路径与日志 ／ "
           "userconfig.py 用户偏好", size=11, fill=C_TEXT, anchor="start")
    s.text(40, py + 42,
           "step01_parse_validate.py ① ／ step02_orient.py ② ／ step03_views.py ③ ／ "
           "step04_normalize.py ④ ／ step05_compliance_check.py ⑤",
           size=11, fill=C_TEXT, anchor="start")
    s.text(40, py + 62,
           "geom_core.py 几何与 HLR ／ render.py 光栅化 ／ dxf_export.py DXF ／ "
           "extract_solids.py 实体筛选 ／ verify_dxf.py DXF 回读验证",
           size=11, fill=C_TEXT, anchor="start")
    s.text(40, py + 88,
           "依据：CNIPA《关于规范提交专利电子申请指引的通知》(2023-05-29)、"
           "《专利审查指南》(2024)、专利法实施细则第 30 条", size=11, fill="#94a3b8",
           anchor="start")

    s.add('</svg>')
    return "\n".join(s.parts)


def main():
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = os.path.join(base, "六视图生成流程图.svg")
    svg = build()
    with open(out, "w", encoding="utf-8") as f:
        f.write('<?xml version="1.0" encoding="UTF-8"?>\n')
        f.write(svg)
    print(f"已生成：{out}  ({len(svg)/1024:.1f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
