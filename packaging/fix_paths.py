# -*- coding: utf-8 -*-
"""一次性修复：把文档里的开发机硬编码路径替换为通用占位符。

用法: python packaging/fix_paths.py
"""
import os
import re

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# 匹配 "$vpy = "...python.exe"" 这种开发机专用路径
PATTERNS = [
    # PowerShell 变量赋值
    (re.compile(r'\$vpy\s*=\s*"[^"]*\.venv\\Scripts\\python\.exe"'),
     '$vpy = "<你的虚拟环境>\\Scripts\\python.exe"'),
    # 裸路径
    (re.compile(r'D:\\Programs\\DeepSeekHarness\\[^\s"\'\)]*'),
     '<项目根目录>'),
    (re.compile(r'C:\\Tools\\design-patent-views'),
     '<解压目录>'),
]

TARGETS = ["DEVELOPMENT.md", "README.md", "INSTALL.md", "SKILL.md"]


def main() -> int:
    total = 0
    for rel in TARGETS:
        p = os.path.join(ROOT, rel)
        if not os.path.exists(p):
            continue
        s = open(p, encoding="utf-8").read()
        orig = s
        n = 0
        for pat, repl in PATTERNS:
            # 用 lambda 避免 re 把替换串里的反斜杠当转义序列
            s, k = pat.subn(lambda m, r=repl: r, s)
            n += k
        if s != orig:
            open(p, "w", encoding="utf-8").write(s)
            print(f"  {rel}: 替换 {n} 处")
            total += n
    print(f"合计 {total} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
