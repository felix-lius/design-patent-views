# 开发文档

> 这是技术实现文档。面向使用者的说明见 [README.md](README.md)。
> 内容包含：技术路线、设计决策、验证结果、能力边界。

---

# 外观设计专利视图自动生成 — 最小验证链路（①→③）

> 状态：**MVP 已跑通**（输入解析 → 几何预处理 → 六视图 + 立体图出图）
> 第④⑤⑥步（专利规范化导出、合规自检、简要说明）尚未实现。
> 合规依据见 [`中国外观设计专利制图合规规格.md`](中国外观设计专利制图合规规格.md)

---

## 1. 技术路线（与最初设想的关键差异）

| 项目 | 原计划 | 实际采用 | 原因 |
|---|---|---|---|
| 几何内核 | FreeCAD + TechDraw | **OCP 7.7.2**（OpenCascade 官方 Python 绑定） | 本机无 FreeCAD；OCP 零依赖、纯命令行、无需 GUI 进程 |
| 投影算法 | TechDraw 视图 | **HLRBRep_Algo 隐藏线消除**（TechDraw 底层同款算法） | 六视图与立体图共用一条代码路径，只换投影轴系 |
| 立体图 | FreeCAD GUI 渲染 | **等轴测 HLR 线框图** | 规范要求"粗细均匀实线表达形状"，着色渲染图不合规 |
| 光栅化 | — | Pillow 直接画折线（2× 超采样） | 不依赖 matplotlib/SVG 渲染链，线宽像素级可控 |

**核心洞察**：六视图与立体图本质是同一件事——给定投影方向做隐藏线消除。
统一成一条路径后，线宽、线型、比例天然一致，合规性由架构保证而非靠事后检查。

## 2. 环境

```
Python 3.12（DSH 内置运行时）
.venv/            --system-site-packages，仅装 cadquery-ocp 7.7.2
.wheels/          cadquery-ocp 7.7.2 离线 wheel（91MB，重装用）
```

安装（已验证可用的离线路径，因 pip 直连解包会被沙箱拦截）：

```powershell
$vpy = "D:\Programs\DeepSeekHarness\外观专利生成\.venv\Scripts\python.exe"
& $vpy scripts\fetch_wheel.py cadquery-ocp "7.7.2-cp312-cp312-win_amd64"
& $vpy -m pip install --no-index --no-deps .wheels\cadquery_ocp-7.7.2-cp312-cp312-win_amd64.whl
```

> 选 7.7.2 的理由：`cadquery-ocp` 8.x / 7.8+ 会强依赖 `vtk`（上百 MB），7.7.2 的 `requires_dist` 为空。

## 3. 目录结构

```
scripts/
  spec.py                  合规规格常量（唯一参数来源）
  pipeline.py              路径约定 / config 载入 / 日志读写
  geom_core.py             STEP 载入、校验、视图轴系、HLR 投影、折线离散
  render.py                统一比例计算、画布渲染、第一角/网格排版
  step01_parse_validate.py ① 输入解析与校验
  step02_orient.py         ② 几何预处理（轴系 + 投影 + 统一比例 + 投影一致性校验）
  step03_views.py          ③ 视图生成（单视图 + 两种图幅 + 总览）
  run_batch.py             批处理总入口
  make_sample.py           生成示例 STEP 模型
  fetch_wheel.py           离线 wheel 下载器
input/<name>.json          config（产品名称/用途/主视图方位/出图模式/视图取舍）
examples/<name>.step       三维源文件
output/<name>/
  raw/<view>.png           单视图（150×220mm @300DPI，无文字，名称由文件名承载）
  submission/<序号>-<中文视图名>.jpg  ★ 提交件（如 1-主视图.jpg，可直接上传专利局）
  sheet_first_angle.png    第一角投影图幅（含视图名称标注，投影对应关系严格）
  sheet_grid.png           2×3 网格图幅（图形更大，投影对应关系不严格）
  contact_sheet.png        全视图缩略总览（含立体图，内部审阅用）
  all_views.dxf            全部视图合一（可编辑矢量，1:1 mm）
logs/01|02|03|04|05_<name>.json  各步结构化报告（05 为合规自检报告）
logs/batch_summary.json    批处理汇总
```

## 4. 用法

```powershell
$vpy = "D:\Programs\DeepSeekHarness\外观专利生成\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = 'utf-8'
& $vpy scripts\run_batch.py                 # 跑 input/ 下全部任务
& $vpy scripts\run_batch.py sample_product  # 只跑指定任务
```

## 5. config 字段

```jsonc
{
  "product_name": "智能控制器（示例）",
  "purpose": "用于工业设备的参数设置与运行状态显示",
  "design_mode": "overall",        // overall | partial（partial 尚未实现）
  "front_axis": "+Y",              // 主视图观察方向：+X/-X/+Y/-Y/+Z/-Z
  "up_axis": "+Z",                 // 主视图屏幕向上方向
  "views": ["front","back","left","right","top","bottom","iso"],
  "omit": [],                      // 省略的视图（需在简要说明写明原因）
  "iso": { "azimuth_deg": 45.0, "elevation_deg": 35.264 },
  "render": { "line_width_mm": 0.35, "supersample": 2 },
  "brief": { "design_points": "...", "best_view": "iso" }
}
```

## 6. 关键设计决策

**a) 视图轴系由主视图方向推导，不自动推断**
`front_axis` + `up_axis` 必填。六视图方向按第一角投影由叉乘推出：
`r = u × d`，`back = -f`、`left = -r`、`right = +r`、`top = +u`、`bottom = -u`。
主视图方向错了整批图作废，因此这一步留给人工（流程图的人工确认点①）。

**b) 投影平面 X 轴 = 屏幕右向量**
`gp_Ax2(origin, d, r)` 而非 `gp_Ax2(origin, d, u)`。否则输出宽高互换（已踩过）。

**c) 六视图共用一个 scale，立体图单独**
- 六视图必须"比例一致" → `scale = min(各视图适配比例)`
- 立体图属参考图，规范未要求同比例 → 单独按版心适配
- 若把立体图并入统一比例，它（通常最大）会把六视图压到 3cm×8cm 下限附近

**d) 只取可见边**
`VCompound` + `Rg1LineVCompound` + `OutLineVCompound`，完全丢弃 `HCompound` 等隐藏边。
符合"虚线禁用"红线，不需要再做事后线型过滤。

**e) 破面只警告不中断**
`BRepCheck_Analyzer` 判定无效时记警告继续出图——专利图可以先出，由人工判断是否补模型。

## 7. 验证结果（示例产品 100×62×27mm）

| 校验项 | 结果 |
|---|---|
| STEP 载入 | ✅ 1 solid / 14 faces / 56 edges，BRepCheck 有效 |
| 六视图投影 | ✅ 全部非空 |
| 主视图宽 = 俯视图宽 | ✅ 100.000 = 100.000 |
| 主视图高 = 左视图高 | ✅ 27.000 = 27.000 |
| 俯视图深 = 左视图宽 | ✅ 62.000 = 62.000 |
| 画布规格 | ✅ 1772×2598 px（150×220mm @300DPI） |
| 线型 | ✅ 纯实线，无隐藏线/虚线/中心线 |
| 图形尺寸 | ⚠️ 主/后/俯/仰/立体图 均达标；左/右视图 78.1×34.0mm，宽度略低于 80mm 下限（保守校验，需人工确认） |

## 8. 已知限制 / 下一步

**尚未实现（第④-⑥步）**
- JPEG 导出与质量参数（当前 PNG）
- 图内无文字的最终校验、图号生成
- 局部外观模式的实线+虚线+点划线（`design_mode: partial` 目前按整体出图并告警）
- 合规自检清单落地（`05_compliance_check.py`）
- 简要说明 docx 生成

**几何侧待加强**
- 圆角/相切边处理：示例模型的 fillet 因布尔边问题未成功，需换更稳健的圆角策略
- 曲面轮廓线密度：当前 deflection=0.05mm，大模型需按尺寸自适应
- 剖视图/放大图/展开图（必要时才需要）
- 薄壁/钣金件可能出现 HLR 轮廓抖动，需实件验证

**工程侧**
- 无 GUI 预览；无失败重试；大模型 HLR 耗时未优化（示例模型 < 1s）
- 多实体（套件/组件）目前合并投影，需按规范拆分出图

## 9. 复现示例

```powershell
$vpy = "D:\Programs\DeepSeekHarness\外观专利生成\.venv\Scripts\python.exe"
$env:PYTHONIOENCODING = 'utf-8'
& $vpy scripts\make_sample.py      # 生成 examples/sample_product.step
& $vpy scripts\run_batch.py        # 跑通 ①→③
```

---

## 10. 真实产品模型验证结果

### 10.1 模型来源与获取难度

| 模型 | 类型 | 来源 | 大小 | 获取情况 |
|---|---|---|---|---|
| `spacemouse.step` | 三维鼠标（整机） | GitHub `ChromeBee/Hall-Effect-Sensor-CAD-Mouse-Spacemouse` | 993 KB | ✅ jsDelivr 直连 |
| `gamepad_joystick.step` | 游戏手柄摇杆模块 | GitHub `HandHeldLegend/HHL-GAMEPAD-CAD` | 625 KB | ✅ jsDelivr 直连 |
| `powerbank.step` | 移动电源整机 | **参数化生成**（`make_powerbank.py`） | 90 KB | ⚠️ 公开渠道无可用 STEP |
| `sample_product.step` | 自建示例 | `make_sample.py` | 34 KB | ✅ 本地生成 |

**下载踩坑记录**（重要经验，后续接真实客户模型会重复遇到）：
- GrabCAD 403（CloudFront 拦截）、GitHub 代码搜索需认证、TraceParts/3DContentCentral 需登录
- Keychron 开源仓库的 STEP 不在仓库内，托管于 `keychron.co:34568` 非标端口，**直连会静默截断**（拿到半截文件，STEP 解析报语法错误）
- `raw.githubusercontent.com` 本机直连超时；**系统代理 31 KB/s，jsDelivr 87 KB/s** —— 优先 jsDelivr
- 教训：**下载必须校验 `END-ISO-10303-21;` 结尾**，否则会拿半截文件去解析

### 10.2 几何与合规结果

| 模型 | 实体/面 | BRepCheck | 投影一致性 | 图形尺寸(mm) | 备注 |
|---|---|---|---|---|---|
| spacemouse | 13 / 562 | ✅ 有效 | ✅ 全部通过（最大偏差 0.0146mm） | 126×121 | 多实体装配，合并投影 |
| gamepad_joystick | 2 / 129 | ✅ 有效 | ✅ 全部通过（偏差 0.0） | 126×80 | 旋转对称，六个视图雷同（几何正确） |
| powerbank | 1 / — | ✅ 有效 | ✅ 全部通过 | 126×78 | 圆角箱体+接口开孔 |
| sample_product | 1 / 14 | ✅ 有效 | ✅ 全部通过（偏差 0.0） | 126×34 | 主视图高 34mm，接近下限 |

偏差 0.0146mm 出现在 spacemouse：曲面轮廓线离散化（deflection=0.05mm）导致不同视图的极值点略有差异，属正常数值误差，远小于 0.0874mm 容差。

### 10.3 验证暴露的关键问题

**问题 1：视图方位必须人工确认（验证了流程图"人工确认点①"的必要性）**

spacemouse 首次跑出图时，主视图是圆形旋钮面、俯视图却是侧剖面——因为该模型的旋钮轴沿 **+Y**，而配置里写的 `up_axis: "+Z"`。
改正为 `front: "+Z", up: "+Y"` 后，俯视图正确显示圆形旋钮面、仰视图显示底部四颗螺丝。

> **模型坐标系的"上"方向与物理产品的"上"方向常常不一致**，无法自动推断，必须由人指定。这与流程图里设置人工确认点①的设计吻合。

**问题 2：多实体装配体需要拆分策略**

spacemouse 含 13 个实体（底座、旋钮、按键等），当前实现是**合并投影**。对外观专利而言：
- 若是一个产品 → 合并投影正确
- 若是套件/组件产品 → 规范要求分别出图并标注「组件N某视图」

当前只给了警告，未实现拆分。这是下一步要补的。

**问题 3：旋转对称件的六视图雷同**

摇杆的六个视图内容相同（因为旋转对称）。严格按规范仍应提交六视图（或按"相同/对称"规则在简要说明中注明省略），工具应能识别并提示。

**问题 4（最严重）：工程装配体把内部结构画进了外观图**

spacemouse 是完整工程装配体——13 个堆叠实体（外壳、底盖、内部支架、按键…）。
直接投影时 HLR 会把**每一层的边**都画出来，立体图颈部出现一圈密集的内部筋位线条，这在外部外观设计图中是不可接受的。

已交付解法：`scripts/extract_solids.py`

```powershell
# 1. 列出实体清单（序号 / 面数 / 尺寸 / 包围盒），人工挑选
python scripts\extract_solids.py list examples\spacemouse.step

# 2. 只保留外观件，另存为新 STEP
python scripts\extract_solids.py keep examples\spacemouse.step 8,9,4 examples\spacemouse_shell.step

# 3. 正常走主链路出图
python scripts\run_batch.py spacemouse_shell
```

**验证效果**：保留 3 个外表面实体后，内部筋位线条全部消失，图纸变干净。
对照结果见 `output/spacemouse/`（未筛选，脏）与 `output/spacemouse_shell/`（已筛选，干净）。

> **结论：外观专利出图的输入不应是工程装配体，而应是"外观件集合"。**
> 这一步无法自动判断（哪几个实体属于外观是业务决策），必须人工确认——
> 建议在产品形态上做成"实体清单 → 勾选 → 出图"的交互。

---

## 11. DXF 矢量交付

每个任务除图片外，还输出**一个包含全部视图的可编辑 DXF**：`output/<name>/all_views.dxf`

### 11.1 设计约定

| 项目 | 约定 |
|---|---|
| 单位 | **毫米**（`$INSUNITS = 4`），**1:1 真实尺寸** |
| 坐标 | 以排布中心为原点，Y 轴向上（CAD 习惯） |
| 排布 | 第一角投影（仰/主/俯 + 右/左/后），立体图置于六视图块下方居中 |
| 图层 | `VIEW` 几何（线宽 0.35mm）／`LABEL` 视图名称（宋体）／`FRAME` 外框（打印前可关层） |
| 打印 | 从日志 `suggested_print_scale` 取比例，缩放后恰好落在 150×220mm 专利版面 |

### 11.2 保留原生实体类型（可真正二次编辑）

这是 DXF 相比位图的核心价值——**不是一堆碎线段**：

| 几何 | DXF 实体 | 在 CAD 里可以做什么 |
|---|---|---|
| 直线 | `LINE` | 拉伸端点、改长度 |
| 圆弧 | `ARC` | 改半径、改圆心、改起止角 |
| 整圆 | `CIRCLE` | 改半径/圆心 |
| 样条/自由曲线 | `LWPOLYLINE` | 移动顶点（此类曲线无解析表达，只能离散） |

实现方式：在 HLR 输出的二维边上读取 `BRepAdaptor_Curve.GetType()`，
按 `GeomAbs_Line` / `GeomAbs_Circle` / 其他分别输出，圆弧起止角用端点
`atan2` 并结合中点判定走向（DXF ARC 恒为逆时针）。

### 11.3 验证结果

| 模型 | audit | LINE | ARC | CIRCLE | LWPOLYLINE | 图形范围(mm) | 建议打印 |
|---|---|---|---|---|---|---|---|
| gamepad_joystick | ✅ 0 错误 | 40 | 62 | 8 | 163 | 162.6×153.7 | 1:1.00 |
| powerbank | ✅ 0 错误 | 56 | 8 | 4 | 26 | 427.9×337.4 | 1:2.85 |
| sample_product | ✅ 0 错误 | 47 | 0 | 1 | 10 | 402.0×318.3 | 1:2.68 |
| spacemouse | ✅ 0 错误 | 179 | 67 | 14 | 330 | 391.4×406.0 | 1:2.61 |
| spacemouse_shell | ✅ 0 错误 | 49 | 36 | 17 | 314 | 391.4×402.9 | 1:2.61 |

验证方式：`scripts/verify_dxf.py` 用 ezdxf **回读**导出的 DXF，跑结构审计，
再用读回的实体重新渲染成图——独立于写入路径，坐标错位/圆弧角度错误会立刻暴露。

### 11.4 免装 CAD 也能看 DXF（在线查看器）

DXF 不是双击就能打开的格式（本机若未装 CAD 软件，系统会提示"选择打开方式"）。
可直接用浏览器打开下列网址，**上传 DXF 即可在线查看**，无需安装任何软件：

| 查看器 | 地址 | 说明 |
|---|---|---|
| **Aspose CAD Viewer** | https://products.aspose.app/cad/viewer/dxf | **推荐**：免登录，DXF 专用入口，上传即看 |
| Autodesk Viewer | https://viewer.autodesk.com | 需注册 Autodesk 账号，支持 DWG/DXF/STEP 等多格式 |

> 网址已内置在 `scripts/spec.py` 的 `ONLINE_DXF_VIEWERS`，
> 每次批处理结束时自动打印在控制台"在线查看 DXF"区块里，用户无需查文档。

### 11.5 用法

```powershell
# 出图时自动生成 DXF（默认 native = 1:1）
python scripts\run_batch.py spacemouse

# 独立回读验证
python scripts\verify_dxf.py spacemouse
```

如需按专利版面缩放（各视图会被压小，一般不用）：
```python
dxf_export.export_all_views(name, views, path, scale_mode="page")
```

---

## 12. 合规自检（第⑤步）

`scripts/step05_compliance_check.py` 对提交件逐项核查，输出分级结果与 JSON 报告。

### 12.1 检查项（31 项，五类）

| 类别 | 编号 | 内容 |
|---|---|---|
| **格式** | F1–F7 | JPEG 格式、DPI 区间、像素区间、版面尺寸、产品图形尺寸、总大小、色彩模式 |
| **线条** | L1–L8 | 禁令线型、线宽统一、无灰阶填充、多余线条、图内无文字、无图号、背景纯白、**装配体内部结构未入图** |
| **视图** | V1–V10 | 数量、命名、标注位置、长对正、高平齐、宽相等、非空、立体图视角、局部外观、立体图存在 |
| **清晰度** | C1–C4 | 缩小 2/3 可辨、线条闭合、破面影响、**轮廓完整性（人工复核）** |
| **文书** | D1–D4 | 简要说明四要素、公报用视图、省略原因、禁用宣传用语 |

判级：`pass` 通过 ／ `warn` 警告（不阻断）／ `fail` 失败（阻断）／ `na` 不适用或需人工。

### 12.2 设计原则：能自动判的自动判，判不了的老实标 na

| 检查手段 | 用在哪些项 |
|---|---|
| 元数据读取 | F1–F4、F6、F7（格式、DPI、像素、大小、色彩模式） |
| 文件统计 | F5（图形尺寸）、F6（总大小） |
| DXF 图层分析 | L1（线型是否命中 DASHED/CENTER 等禁令） |
| 图像分析（numpy） | L3/L7（灰阶占比判有无填充阴影）、L2/C1（线宽） |
| 几何数据 | V1–V7、V10（视图、投影一致性） |
| 配置值 | V8（45° 视角）、V9（出图模式） |
| **标 na** | L4（多余线条）、C2（线条闭合）、D1–D4（文书未实现） |

> **线宽判定说明**：判定依据是"渲染参数唯一"（`spec.line_width_px` 单一值），
> 不是从图像反推——抗锯齿和 JPEG 会让图像实测值系统性偏大（实测 6–14px vs 实际 4px）。
> 图像测量仅作相对一致性旁证（极差 ≤2× 视为正常）。

### 12.3 当前验证结果（9 个模型）

| 模型 | 通过 | 警告 | 失败 | 不适用 |
|---|---|---|---|---|
| powerbank（单实体） | 25 | 0 | 0 | 8 |
| spacemouse_shell（已筛外观件） | 25 | 0 | 0 | 8 |
| gamepad_joystick | 24 | 1 | 0 | 8 |
| sample_product | 24 | 1 | 0 | 8 |
| spacemouse | 24 | 1 | 0 | 8 |
| thinwall_case | 24 | 1 | 0 | 8 |
| speaker_l（蓝牙音箱，有效） | 23 | 2 | 0 | 8 |
| mouse_moudabella（183 实体） | 21 | 4 | 0 | 8 |
| mouse_shell（7 实体，含无效） | 22 | 3 | 0 | 8 |

> **C4 已降级为 warn**：实测发现覆盖度度量无法可靠区分"正确遮挡"与"丢线"——
> 有效几何的 speaker_l 被误报为 50% 覆盖度（实际图面完整）。
> 误报比漏报危害更大（用户失去信任），故 C4 改为"提示人工复核"而非"禁止提交"。

### 12.4 配置项

| 键 | 默认 | 说明 |
|---|---|---|
| `hlr_mode` | `composite` | `composite`=精确 HLR（默认，内部遮挡干净）；`hybrid`=精确 V+Rg1 + 网格剪影（**实验性**：俯视图方向能补全轮廓，但后/仰视图方向会产生碎片化剪影，慎用）；`per_solid`=逐实体 HLR（轮廓完整但内部暴露） |
| `verify_outline` | `false` | 是否逐视图验算轮廓覆盖度（需额外一轮 per-solid 投影，耗时约 +60%） |
| `solids_filtered` | `false` | 声明已人工筛选外观件，L8 检查据此放行 |

### 12.5 用法

```powershell
python scripts\run_batch.py <name>                   # 全流程含 ④⑤
python scripts\step05_compliance_check.py <name>     # 单独重跑自检
```

---

## 13. 能力边界：无效几何会导致丢线

### 13.1 现象

用 `mouse_shell.step`（开源鼠标的 7 个外观件）出图时，**所有视图都存在不同程度的丢线**，
其中俯视图后端轮廓弧线缺失在视觉上最显眼。

**实测数据**（composite 模式下各视图的剪影线 OutLineVCompound 丢失情况）：

| 视图 | OL 丢失条数 | 孤立碎片数 | 视觉明显度 |
|---|---|---|---|
| 主视图 | 32 | 27 | 不明显（被尖锐边遮掩） |
| 后视图 | 59 | 8 | 不明显 |
| 左视图 | 20 | 9 | 不明显 |
| 右视图 | 21 | 11 | 不明显 |
| 俯视图 | 19 | 13 | ★ 明显（外轮廓唯一连接弧缺口） |
| 仰视图 | 24 | 2 | 不明显 |
| 立体图 | 64 | 16 | 轻微可见 |

> **关键教训**：目视"看起来没问题"≠ 几何完整。七个视图全部丢线，
> 但只有俯视图的丢失恰好落在外轮廓的必经之路上（后端连接弧），
> 其他视图的缺口被尖锐边（VCompound）或相邻剪影线填补了视觉连续性。
> 这正是 C4 覆盖度检测存在的意义——它抓的是全局性丢线，不只是肉眼可见的缺口。

### 13.2 根因（已定位，有实验证据）

| 实验 | 结果 | 结论 |
|---|---|---|
| 复合体一次 `Add()` | 510 条折线，缺后端弧 | 当前默认行为 |
| 仅单实体投影 | 轮廓完整闭合 | **HLR 算法本身正常** |
| 布尔并集 `fuse` | 与复合体一致 | 无法规避 |
| `fuse` + `UnifySameDomain` | 与复合体一致 | 无法规避 |
| 同一实例多次 `Add()` | 与复合体一致 | 无法规避 |
| 逐实体 HLR 后合并 | 1467 条折线，**轮廓完整** | 但内部结构全暴露 |
| 逐实体仅取剪影线补漏 | 只补回 62 条 | 缺口仍在 |

逐实体 BRepCheck 检查：

```
实体 0（底盘，338 面） invalid
实体 1–4（234/124/128/104 面） valid
实体 5、6（各 134 面） invalid
```

**三个无效实体（0/5/6）恰好就是后端区域的构成部件。**

> **结论：OCCT 的 HLR 在含破面/自交的几何上，对无效曲面的剪影（OutLine）求解会失败或被跳过，
> 导致所有视图都丢失部分剪影边。** 丢失的位置取决于哪些曲面与视线相切，
> 所以各视图缺口位置不同——并非"只有俯视图有问题"。
> 多实体聚合计算会放大此问题（逐实体单独投影时剪影线完整）。
> 这不是参数问题（deflection=0.05mm 已足够细），也无法通过 fuse / 同域合并规避。

### 13.3 应对

| 层 | 措施 | 状态 |
|---|---|---|
| **检测** | 第⑤步 C4「轮廓完整性」：以逐实体全量投影为参照比对覆盖度，**降级为 warn**（提示人工复核）。实测发现覆盖度度量无法可靠区分"正确遮挡"与"丢线"，误报比漏报危害更大 | ✅ 已实现 |
| **检测（轻量）** | 第①步逐实体 BRepCheck，C4 在未开启深度核查时据此告警 | ✅ 已实现 |
| **应急出口** | `hlr_mode: per_solid` — 轮廓完整，代价是内部结构暴露 | ✅ 已实现 |
| **实验性修复** | `hlr_mode: hybrid` — 精确 V+Rg1 + 网格剪影。俯视图方向可补全（覆盖度 100%），**但后/仰方向会产生碎片化剪影，图面不可用** | ⚠️ 实验性，默认不启用 |
| **根治** | 在 CAD 中修复无效实体后重新导出；或提供闭合良好的单一外壳 | 用户侧 |

**hybrid 实测数据**（覆盖度，参照=逐实体 PolyAlgo 剪影）：

| 视图 | composite | hybrid |
|---|---|---|
| 俯视图 | 78.7% | **100.0%** ✅ |
| 左视图 | 87.3% | 90.0% |
| 右视图 | 88.8% | 91.4% |
| 仰视图 | 69.7% | 84.6% |
| 主视图 | 80.7% | 84.1% |
| **后视图** | 59.1% | **70.7% ❌ 剪影碎片化** |

> 结论：PolyAlgo 对无效几何的剪影输出**不稳定**——俯视图方向补全成功，
> 后视图方向产生碎片化短划线。hybrid 不能作为无条件默认。
> 最终路径仍是「C4 检测拦截 + CAD 端修复几何」。

### 13.4 C4 阈值标定

`outline_coverage` 的容差取 **1.0mm**，是实测标定的结果：

| 模型 | tol=0.35 | **tol=1.0** | tol=2.0 |
|---|---|---|---|
| mouse_shell（已知丢线） | 60.3% | **82.6%** | 93.1% |
| gamepad_joystick（已知正常） | 88.8% | **100.0%** | 100% |
| powerbank（单实体） | 100% | **100%** | 100% |

0.35mm 会因离散/抗锯齿误判（正常模型仅 88.8%），故取 1.0mm：
**正常模型 100%、丢线模型 82.6%**，区分度清晰。

---

*生成时间：2026-10-28*
