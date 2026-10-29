# -*- coding: utf-8 -*-
"""用户级持久配置 —— 记住导出目录。

存放位置（按顺序探测，第一个能写的就是它）：

    1. ~/.design-patent-views/config.json          ← 正常情况
    2. <当前工作目录>/.design-patent-views/config.json  ← 主目录不可写时的退路

第 2 条是为受限环境准备的：某些沙箱/受管机器不允许写用户主目录
（Windows 上表现为 WinError 5 拒绝访问）。有了退路，功能不会因此废掉。

设计取舍
--------
* 只存用户自己的偏好（目前只有导出目录），不存模型内容、不联网。
* **读失败一律当成"没配置"**，绝不让一个坏掉的配置文件卡住出图。
* **写失败必须报错**，不能静默吞掉——否则用户以为记住了，下次发现没记住。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional

APP_DIRNAME = ".design-patent-views"
CONFIG_NAME = "config.json"


def _candidate_dirs() -> List[str]:
    dirs: List[str] = []
    try:
        home = os.path.expanduser("~")
        if home and home != "~":
            dirs.append(os.path.join(home, APP_DIRNAME))
    except Exception:
        pass
    try:
        dirs.append(os.path.join(os.getcwd(), APP_DIRNAME))
    except Exception:
        pass
    return dirs


def _path_in(d: str) -> str:
    return os.path.join(d, CONFIG_NAME)


def _writable_dir(d: str) -> bool:
    try:
        os.makedirs(d, exist_ok=True)
        probe = os.path.join(d, ".w")
        with open(probe, "w", encoding="utf-8") as f:
            f.write("")
        os.remove(probe)
        return True
    except OSError:
        return False


def config_file() -> str:
    """配置文件的实际路径：已存在的优先，否则第一个真正可写的位置。

    不能只返回"首选路径"——主目录不可写时那样会误导用户去一个
    根本不存在的文件里找配置。
    """
    cands = _candidate_dirs()
    for d in cands:
        p = _path_in(d)
        if os.path.exists(p):
            return p
    for d in cands:
        if _writable_dir(d):
            return _path_in(d)
    return _path_in(cands[0]) if cands else CONFIG_NAME


def load() -> Dict[str, Any]:
    """读配置。任何异常都返回空 dict（当作没配置）。"""
    for d in _candidate_dirs():
        path = _path_in(d)
        if not os.path.exists(path):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except (OSError, ValueError):
            continue
    return {}


def save(cfg: Dict[str, Any]) -> str:
    """写配置，返回实际写入的路径。全部位置都写不进去时抛 OSError。"""
    last_err: Optional[OSError] = None
    for d in _candidate_dirs():
        path = _path_in(d)
        try:
            os.makedirs(d, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(cfg, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
            return path
        except OSError as e:
            last_err = e
            continue
    raise last_err or OSError("没有可写的位置存放配置文件")


def get_out_dir() -> Optional[str]:
    v = load().get("out_dir")
    if isinstance(v, str) and v.strip():
        return v.strip()
    return None


def normalize_path(path: str) -> str:
    """展开 ~ 与环境变量，转绝对路径，去掉末尾分隔符。"""
    p = os.path.expandvars(os.path.expanduser(path.strip().strip('"').strip("'")))
    p = os.path.abspath(p)
    if len(p) > 3 and p.endswith(("\\", "/")):
        p = p.rstrip("\\/")
    return p


def check_writable(path: str) -> Optional[str]:
    """能创建并写入就返回 None，否则返回中文错误说明。"""
    p = normalize_path(path)
    if os.path.exists(p) and not os.path.isdir(p):
        return f"该路径已存在但不是文件夹：{p}"
    try:
        os.makedirs(p, exist_ok=True)
    except OSError as e:
        return f"无法创建文件夹：{p}（{e.strerror or e}）"
    probe = os.path.join(p, ".patent_write_test")
    try:
        with open(probe, "w", encoding="utf-8") as f:
            f.write("ok")
        os.remove(probe)
    except OSError as e:
        return f"文件夹不可写：{p}（{e.strerror or e}）"
    return None


def set_out_dir(path: str) -> str:
    """设置并持久化导出目录，返回规范化后的绝对路径。

    校验失败抛 ValueError（消息已是给用户看的中文）。
    """
    p = normalize_path(path)
    err = check_writable(p)
    if err:
        raise ValueError(err)
    cfg = load()
    cfg["out_dir"] = p
    save(cfg)
    return p


def clear_out_dir() -> None:
    cfg = load()
    cfg.pop("out_dir", None)
    save(cfg)
