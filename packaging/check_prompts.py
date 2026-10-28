# -*- coding: utf-8 -*-
"""校验 安装.md 与 SKILL.md 里的提示词块是否完全一致。"""
import difflib
import os
import re

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def blocks(path):
    s = open(path, encoding="utf-8").read()
    # 匹配 ``` ... ``` 里以「帮我装」开头的段落（安装提示词）
    out = []
    for m in re.finditer(r"```[^\n]*\n(.*?)```", s, re.S):
        body = m.group(1)
        if body.lstrip().startswith("帮我装"):
            out.append(body.strip())
    return out


a = blocks(os.path.join(BASE, "README.md"))
b = blocks(os.path.join(BASE, "SKILL.md"))
print(f"README.md  提示词块: {len(a)}")
print(f"SKILL.md 提示词块: {len(b)}")

ok = True
for i, (x, y) in enumerate(zip(a, b), 1):
    same = x == y
    print(f"  第 {i} 段一致: {same}")
    if not same:
        ok = False
        for line in list(difflib.unified_diff(x.splitlines(), y.splitlines(),
                                              fromfile="README.md", tofile="SKILL.md",
                                              lineterm=""))[:15]:
            print("   ", line)

if len(a) != len(b):
    ok = False
    print(f"  ✗ 段数不一致：{len(a)} vs {len(b)}")

print("\n✓ 完全一致" if ok else "\n✗ 存在差异")
