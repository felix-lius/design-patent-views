# INSTALL — 安装指引（给 AI agent 读）

> 用户只会说一句「帮我装一下这个工具」。具体怎么做看这份文件。

## 一、先判断用哪个方案

```bash
# 检查是否有 Python 3.10+
python --version
```

| 情况 | 用哪个方案 |
|---|---|
| 有 Python 3.10+（推荐 3.12） | **方案 B 轻量版**（下载 <1MB + 依赖 91MB） |
| 没有 Python / 版本太旧 / 用户不想折腾 | **方案 A 一键包**（92MB 解压即用） |
| 非 Windows | 目前只支持 Windows x64，直接告知用户 |

**默认推荐方案 A**——除非用户明确说有 Python 环境。

---

## 二、方案 A · 一键包

**下载地址由用户提供**（在用户给你的安装提示词里）。拿到地址后：

```bash
# 1. 下载 design-patent-views-win64.zip（约 92MB）

# 2. 解压到任意目录（用户目录、桌面等均可）
#    解压后根目录应有：patent-cli.exe、_internal\、examples\、SKILL.md

# 3. 验证
# 进入解压后的目录
patent-cli.exe --help
# 应看到 auto / analyze / render / dxf / check / run / config 七个子命令

# 4. 冒烟测试（用包内自带的示例）
patent-cli.exe auto --step examples\powerbank.step --front +Y --up +Z --quiet
# 返回 JSON 且 "ok": true 即成功
```

**注意**：
- 不要修改或删除 `_internal/` 目录（运行库）
- 如果杀软拦截，先告知用户，不要强行放行
- 输出默认写到**桌面上的「外观专利视图」文件夹**（桌面不可写时退回当前工作目录）；
  用户想换位置，用 `patent-cli.exe config --out-dir <路径>`，设置一次永久记住
- 冒烟测试显式给了 `--front/--up` 是为了跳过交互。**实际使用时不给这两个参数**，
  工具会分两轮返回 `need: orientation`（先问主视图、再问上方向），
  由你把预览图给用户指认 —— 详见 `SKILL.md`。

---

## 三、方案 B · 轻量版

**前提**：技能文件已经在本地（平台自动装的，或用户自己 clone 的）。
依赖都是公开 PyPI 包，**不需要任何私有下载地址**。

```bash
# 1. 进入技能目录（install_deps.py 所在位置）

# 2. 安装依赖（自动下载 OCP 约 91MB + Pillow/ezdxf/numpy）
python install_deps.py

# 3. 验证（四项都 ✓ 才算成功）
python install_deps.py --check

# 4. 冒烟测试
python scripts\patent_cli.py auto --step examples\powerbank.step --front +Y --up +Z --quiet
```

依赖版本已固定在 `install_deps.py` 里（`OCP 7.7.2` 零依赖版本），
镜像默认清华，失败可加 `--mirror pypi` 切官方源。

**安装完成后**：把 `SKILL.md` 装进你的技能目录（若支持），
之后用户直接说「把这个 STEP 出六视图」即可。

---

## 四、失败处理

按顺序排查，**不要擅自升级/降级依赖版本，也不要换 Python 版本**——先告诉用户。

| 报错 | 处理 |
|---|---|
| `No module named pip` | `python -m ensurepip --upgrade`；仍失败则改用方案 A |
| Python 不是 3.12 | 告知用户需装 3.12（OCP 只提供 cp312 wheel），或改用方案 A |
| 下载 OCP 慢/超时 | `python install_deps.py --mirror pypi` |
| `PermissionError` | 换用户目录，或用虚拟环境 |
| `import OCP` 失败 | `python install_deps.py --force-ocp` |
| `DLL load failed ... OCP` | 依赖不完整，重跑安装；一键包则重新解压完整 zip |
| 杀软报毒 | 告知用户，暂停安装，不要加白名单 |

---

## 五、装完之后

1. 告诉用户装到了哪个路径
2. 报告验证结果（冒烟测试是否 `ok: true`）
3. 如果支持 SKILL.md，说明已装好，可以直接下达出图任务
4. 提醒一句：**工具全程本地运行，模型不会上传**

---

## 六、不要做的事

- ❌ 不要只回「你需要安装依赖」就结束——要真的装，或给出可执行的下一步
- ❌ 不要自行修改 `_internal/` 或依赖版本
- ❌ 不要在非 Windows 上尝试装一键包
- ❌ 不要把用户的 STEP 模型上传到任何在线服务
