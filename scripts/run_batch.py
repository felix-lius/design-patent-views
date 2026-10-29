# -*- coding: utf-8 -*-
"""批处理总入口：串起 ① → ② → ③（MVP 链路）。

用法
----
    python run_batch.py                 # 跑 input/ 下全部 config
    python run_batch.py sample_product  # 只跑指定任务

单个任务失败不影响其他任务，结果汇总写入 logs/batch_summary.json。
"""
from __future__ import annotations

import glob
import os
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import pipeline as pl
import spec
import step01_parse_validate as s01
import step02_orient as s02
import step03_views as s03
import step04_normalize as s04
import step05_compliance_check as s05


def discover() -> list[str]:
    names = []
    for p in sorted(glob.glob(os.path.join(pl.DIR_INPUT, "*.json"))):
        names.append(os.path.splitext(os.path.basename(p))[0])
    return names


def run_one(name: str) -> dict:
    print(f"\n=== {name} ===")
    result = {"name": name, "steps": {}}

    try:
        rep01 = s01.run(name)
        pl.write_json(pl.step_log_path("01", name), rep01)
        result["steps"]["01"] = {"ok": rep01["ok"],
                                 "errors": rep01["errors"],
                                 "warnings": rep01["warnings"]}
        if not rep01["ok"]:
            result["ok"] = False
            return result

        rep02 = s02.run(name)
        pl.write_json(pl.step_log_path("02", name), rep02)
        result["steps"]["02"] = {"ok": rep02["ok"],
                                 "views": list(rep02["views"].keys()),
                                 "scale": rep02["uniform_scale_px_per_mm"],
                                 "warnings": rep02["warnings"]}

        rep03 = s03.run(name)
        pl.write_json(pl.step_log_path("03", name), rep03)
        result["steps"]["03"] = {"ok": rep03["ok"],
                                 "outputs": [o["file"] for o in rep03["outputs"]]}

        rep04 = s04.run(name)
        pl.write_json(pl.step_log_path("04", name), rep04)
        result["steps"]["04"] = {"ok": rep04["ok"],
                                 "files": [i["file"] for i in rep04["items"]],
                                 "total_mb": rep04["total_mb"]}

        rep05 = s05.run(name)
        pl.write_json(pl.step_log_path("05", name), rep05)
        result["steps"]["05"] = {"ok": rep05["ok"],
                                 "summary": rep05["summary"],
                                 "total_items": rep05["total_items"]}
        sm = rep05["summary"]
        print(f"  合规自检：共{rep05['total_items']}项  "
              f"通过{sm['pass']}/警告{sm['warn']}/失败{sm['fail']}/不适用{sm['na']}")

        # 第⑤步的 fail 不中止整批，但要如实反映在结果里
        result["ok"] = rep05["ok"]
    except Exception as e:
        result["ok"] = False
        result["exception"] = f"{type(e).__name__}: {e}"
        result["traceback"] = traceback.format_exc()
        print("  FAILED:", result["exception"])
    return result


def main():
    names = sys.argv[1:] or discover()
    if not names:
        print("input/ 下没有 config，请先放置 <name>.json")
        raise SystemExit(1)

    results = [run_one(n) for n in names]
    pl.write_json(os.path.join(pl.DIR_LOGS, "batch_summary.json"), results)

    print("\n================ 汇总 ================")
    for r in results:
        if r.get("ok"):
            flag = "OK   "
        elif r.get("exception"):
            flag = "ERROR"
        else:
            s5 = (r.get("steps", {}).get("05") or {}).get("summary") or {}
            flag = f"BLOCK" if s5.get("fail") else "FAIL "
        print(f"[{flag}] {r['name']}" +
              (f"  ← 合规未通过（{((r.get('steps',{}).get('05') or {}).get('summary') or {}).get('fail',0)} 项阻断）"
               if flag == "BLOCK" else ""))

    ok_names = [r["name"] for r in results if r.get("ok")]
    if ok_names:
        print("\n---------------- 交付物 ----------------")
        print(f"输出目录：{pl.DIR_OUTPUT}\\<产品名>\\")
        print("  raw/<view>.png        单视图（150×220mm @300DPI）")
        print("  sheet_first_angle.png 第一角投影图幅")
        print("  sheet_grid.png        网格图幅")
        print("  all_views.dxf         全部视图合一（可编辑矢量，1:1 mm）")
        print("  submission/<序号>-<视图名>.jpg  提交件（150×220mm @300DPI，可直接上传专利局）")
        print("  logs/05_<name>.json   合规自检报告")
        print("\n---------------- 在线查看 DXF ----------------")
        print("本机未装 CAD 时，可直接用浏览器打开下列网址上传 DXF 查看：")
        for label, url in spec.ONLINE_DXF_VIEWERS:
            print(f"  · {label}")
            print(f"    {url}")

    raise SystemExit(0 if all(r.get("ok") for r in results) else 1)


if __name__ == "__main__":
    main()
