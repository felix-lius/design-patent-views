# -*- coding: utf-8 -*-
"""合规规格常量 —— 依据《中国外观设计专利制图合规规格》v1.0

本文件是唯一参数来源，任何出图/自检逻辑都必须引用这里，不得硬编码。
"""
from __future__ import annotations

# ---------------------------------------------------------------- 官方硬性规格
IMAGE_FORMAT = "JPEG"                 # 外观图片仅 JPEG
PAGE_MM = (150.0, 220.0)              # 版面 ≤ 150mm × 220mm
DPI = 300                             # 72–300 DPI 区间，取上限保清晰
PIXEL_SIZE = (1772, 2598)             # 150/220mm @300DPI
PIXEL_MIN = (467.7, 694.4)            # 官方下限（对应 165×245mm @72DPI）
PIXEL_MAX = (1948.8, 2893.7)          # 官方上限（对应 165×245mm @300DPI）
DPI_RANGE = (72, 300)
FIGURE_MIN_MM = (30.0, 80.0)          # 产品图形 ≥ 3cm × 8cm（细长物品除外）
FIGURE_MAX_MM = (150.0, 220.0)
TOTAL_SIZE_MAX_MB = 30

# ---------------------------------------------------------------- 线条规格
LINE_WIDTH_MM = (0.25, 0.50)          # 统一线宽区间
LINE_WIDTH_DEFAULT_MM = 0.35
PROJECTION = "first_angle"            # 中国采用第一角投影
HIDE_HIDDEN_LINES = True              # 虚线禁用 → 必须关闭隐藏线

# ---------------------------------------------------------------- 视图命名
VIEW_ORDER = ["front", "back", "left", "right", "top", "bottom", "iso"]
VIEW_NAMES_CN = {
    "front": "主视图",
    "back": "后视图",
    "left": "左视图",
    "right": "右视图",
    "top": "俯视图",
    "bottom": "仰视图",
    "iso": "立体图",
}
SIX_VIEWS = ["front", "back", "left", "right", "top", "bottom"]

# ---------------------------------------------------------------- 立体图
ISO_AZIMUTH_DEG = 45.0                # 侧 45° 视角
ISO_ELEVATION_DEG = 35.264            # 等轴测标准仰角

# ---------------------------------------------------------------- 局部外观模式
DESIGN_MODES = ("overall", "partial")
PARTIAL_DESIGN_EXEMPT_LINES = ("dashed", "dashdot")   # 局部外观可豁免的线型

# ---------------------------------------------------------------- 工具换算
def mm_to_px(mm: float, dpi: int = DPI) -> float:
    return mm / 25.4 * dpi


def line_width_px(width_mm: float = LINE_WIDTH_DEFAULT_MM, dpi: int = DPI) -> int:
    """线宽 mm → 像素，至少 2px 保证可见。"""
    return max(2, int(round(mm_to_px(width_mm, dpi))))


# 内容区留白（版心），用于计算统一比例
MARGIN_MM = {"left": 12.0, "right": 12.0, "top": 14.0, "bottom": 14.0}

# 在线查看器：不装 CAD 也能看 DXF（已实测可访问）
ONLINE_DXF_VIEWERS = [
    ("Aspose CAD Viewer（免登录，DXF 直达）", "https://products.aspose.app/cad/viewer/dxf"),
    ("Autodesk Viewer（需注册，支持多格式）", "https://viewer.autodesk.com"),
]

SPEC = {
    "image_format": IMAGE_FORMAT,
    "page_mm": PAGE_MM,
    "dpi": DPI,
    "pixel_size": PIXEL_SIZE,
    "pixel_min": PIXEL_MIN,
    "pixel_max": PIXEL_MAX,
    "dpi_range": DPI_RANGE,
    "figure_min_mm": FIGURE_MIN_MM,
    "figure_max_mm": FIGURE_MAX_MM,
    "total_size_max_mb": TOTAL_SIZE_MAX_MB,
    "line_width_mm": LINE_WIDTH_MM,
    "projection": PROJECTION,
    "hide_hidden_lines": HIDE_HIDDEN_LINES,
    "view_names": VIEW_NAMES_CN,
    "isometric_angle_deg": ISO_AZIMUTH_DEG,
    "forbidden_line_types": ["dashed", "dashdot", "center", "dimension", "hatch"],
    "partial_design_exempt": list(PARTIAL_DESIGN_EXEMPT_LINES),
}
