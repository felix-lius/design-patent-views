# -*- coding: utf-8 -*-
"""生成验证结果信息图（单页 PNG）。"""
import os
from PIL import Image, ImageDraw, ImageFont

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(BASE, "output", "验证结果总览.png")

W, H = 1400, 1500
BG = "white"
INK = "#1e293b"
MUTED = "#64748b"
ACCENT = "#2563eb"
OK = "#16a34a"
WARN = "#d97706"
CARD = "#f8fafc"
LINE = "#cbd5e1"

F = {
    "h1": r"C:\Windows\Fonts\msyhbd.ttc",
    "h2": r"C:\Windows\Fonts\msyhbd.ttc",
    "b":  r"C:\Windows\Fonts\msyh.ttc",
    "bd": r"C:\Windows\Fonts\msyhbd.ttc",
}


def font(kind, size):
    p = F.get(kind, F["b"])
    if not os.path.exists(p):
        p = r"C:\Windows\Fonts\msyh.ttc"
    return ImageFont.truetype(p, size)


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def text(xy, s, kind="b", size=22, fill=INK, anchor="la"):
    d.text(xy, s, font=font(kind, size), fill=fill, anchor=anchor)


def rrect(box, r=14, fill=None, outline=None, width=2):
    d.rounded_rectangle(box, radius=r, fill=fill, outline=outline, width=width)


# ---------------- 标题 ----------------
text((60, 52), "外观设计专利视图自动生成 · 验证结果", "h1", 40)
text((60, 108), "真实电子产品模型（GitHub 开源 STEP）· 链路 ①→③ · 2026-10-28", "b", 20, MUTED)

# ---------------- 关键指标条 ----------------
stats = [
    ("5 / 5", "任务全部通过", OK),
    ("4 类", "电子产品形态", ACCENT),
    ("7 视图", "六视图 + 立体图", ACCENT),
    ("1772×2598", "150×220mm @300DPI", ACCENT),
]
bw = (W - 120 - 3 * 20) / 4
for i, (v, label, color) in enumerate(stats):
    x = 60 + i * (bw + 20)
    rrect((x, 160, x + bw, 262), 12, CARD, LINE, 2)
    text((x + bw / 2, 190), v, "h1", 34, color, "mm")
    text((x + bw / 2, 234), label, "b", 18, MUTED, "mm")

# ---------------- 表格 ----------------
text((60, 300), "各模型验证明细", "h2", 26)

rows = [
    ("三维鼠标 spacemouse", "13 / 562", "7", "通过", 121.2, 144.9, "98.40%", True),
    ("游戏手柄摇杆", "2 / 129", "7", "通过", 80.3, 126.0, "98.87%", True),
    ("充电宝 powerbank", "1 / 78", "7", "通过", 31.2, 126.0, "99.20%", True),
    ("自建示例件", "1 / 14", "7", "通过", 34.0, 126.0, "99.18%", True),
]

# 表头
hy = 348
text((72, hy), "模型", "bd", 18, MUTED)
text((392, hy), "实体/面", "bd", 18, MUTED)
text((520, hy), "视图", "bd", 18, MUTED)
text((612, hy), "投影一致性", "bd", 18, MUTED)
text((770, hy), "图形尺寸 (mm)", "bd", 18, MUTED)
text((1240, hy), "线型纯度", "bd", 18, MUTED)
d.line((60, hy + 34, W - 60, hy + 34), fill=LINE, width=2)

# 条形图比例：最长 126mm 对应 330px
BAR_X, BAR_W = 770, 330
BAR_MAX = 152.0
ry = hy + 52
for name, sf, vw, cons, fmin, fmax, pur, okflag in rows:
    text((72, ry + 8), name, "b", 21)
    text((392, ry + 8), sf, "b", 20, MUTED)
    text((520, ry + 8), vw, "b", 20, MUTED)
    text((612, ry + 8), "√ " + cons, "bd", 20, OK)
    # 条形：表示尺寸区间
    x0 = BAR_X + fmin / BAR_MAX * BAR_W
    x1 = BAR_X + fmax / BAR_MAX * BAR_W
    d.rounded_rectangle((BAR_X, ry + 10, BAR_X + BAR_W, ry + 28), radius=9, fill="#eef2f7")
    d.rounded_rectangle((x0, ry + 10, max(x0 + 6, x1), ry + 28), radius=9, fill=ACCENT)
    text((BAR_X + BAR_W + 12, ry + 8), f"{fmin:.0f}~{fmax:.0f}", "b", 18, INK)
    text((1240, ry + 8), pur, "b", 20, MUTED)
    d.line((60, ry + 46, W - 60, ry + 46), fill="#eef2f7", width=1)
    ry += 52



# ---------------- 关键发现 ----------------
fy = 620
rrect((60, fy, W - 60, fy + 520), 16, "white", LINE, 2)
text((90, fy + 24), "关键发现：工程装配体会把内部结构画进外观图", "h2", 26, "#b91c1c")
text((90, fy + 66), "spacemouse 是 13 个实体堆叠的完整装配体，隐藏线消除会把每一层的边都画出来 →", "b", 20, INK)
text((90, fy + 96), "颈部出现密集内部筋位线条。这在外部外观设计图中不可提交。", "b", 20, INK)

# 前后对比缩略图
crop_box = (600, 600, 1350, 1230)
thumbs = []
for idx, (p, cap, col) in enumerate([
    (os.path.join(BASE, "output", "spacemouse", "raw", "iso.png"), "13 实体全投影 · 内部筋位暴露", "#b91c1c"),
    (os.path.join(BASE, "output", "spacemouse_shell", "raw", "iso.png"), "仅保留 3 个外观件 · 图纸干净", OK),
]):
    im = Image.open(p).crop(crop_box)
    im.thumbnail((360, 320), Image.LANCZOS)
    tx = 90 + idx * 400
    ty = fy + 140
    img.paste(im, (tx, ty))
    d.rectangle((tx, ty, tx + im.width, ty + im.height), outline=LINE, width=2)
    text((tx + im.width / 2, ty + im.height + 12), cap, "bd", 18, col, "ma")
    if idx == 0:
        text((tx + im.width + 24, ty + 130), "→", "h1", 44, MUTED, "mm")

# 解法
text((860, fy + 150), "解法：extract_solids.py", "h2", 22, ACCENT)
text((860, fy + 186), "1  列出实体清单（序号/面数/尺寸）", "b", 18, INK)
text((860, fy + 216), "2  人工勾选外观件", "b", 18, INK)
text((860, fy + 246), "3  另存 STEP → 走主链路出图", "b", 18, INK)
text((860, fy + 292), "筛选后内部边线全部消失", "bd", 18, OK)
text((860, fy + 322), "但「哪些属于外观件」是业务判断，", "b", 17, MUTED)
text((860, fy + 348), "无法自动推断 → 必须人工确认。", "b", 17, MUTED)

# ---------------- 结论 ----------------
cy = fy + 550
rrect((60, cy, W - 60, cy + 232), 16, "#f0fdf4", "#86efac", 2)
text((90, cy + 22), "结论", "h2", 26, OK)
text((90, cy + 64), "1   几何链路已验证：STEP → HLR 正交投影 → 黑白线条图，4 类产品全部通过", "b", 21, INK)
text((90, cy + 104), "2   投影一致性误差 ≤0.015mm（曲面离散误差，远小于容差）", "b", 21, INK)
text((90, cy + 144), "3   输入必须是「外观件集合」而非工程装配体 —— 这是产品化的核心约束", "bd", 21, INK)
text((90, cy + 180), "4   方位与外观件选择需人工确认 → 下一步做可视化勾选交互", "b", 21, MUTED)

img.save(OUT, "PNG")
print("saved", OUT, os.path.getsize(OUT))
