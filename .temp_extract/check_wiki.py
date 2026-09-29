# -*- coding: utf-8 -*-
"""Validate wiki markdown: internal links, front matter, heading structure."""
import os
import re
import glob

WIKI = r"d:\WorkPlace\projects\GuDao_Wiki\wiki"
issues = []
files = glob.glob(os.path.join(WIKI, "**", "*.md"), recursive=True)
print(f"Total md files: {len(files)}\n")

for path in files:
    rel = os.path.relpath(path, WIKI)
    with open(path, encoding="utf-8") as f:
        text = f.read()
    base = os.path.dirname(path)

    # 1. front matter
    if not text.startswith("---"):
        issues.append(f"[front-matter] {rel}: missing YAML front matter")
    else:
        m = re.match(r"^---\n(.*?)\n---", text, re.S)
        if not m:
            issues.append(f"[front-matter] {rel}: malformed front matter")
        else:
            fm = m.group(1)
            for key in ("title", "分类", "更新日期"):
                if key not in fm:
                    issues.append(f"[front-matter] {rel}: missing key '{key}'")

    # 2. H1 check
    h1 = re.findall(r"^# .+$", text, re.M)
    if len(h1) != 1:
        issues.append(f"[heading] {rel}: expected exactly 1 H1, found {len(h1)}")

    # 3. links
    links = re.findall(r"\[([^\]]+)\]\(([^)]+)\)", text)
    for label, target in links:
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        target = target.split("#")[0]
        if not target:
            continue
        resolved = os.path.normpath(os.path.join(base, target))
        if not os.path.exists(resolved):
            issues.append(f"[link] {rel}: broken link [{label}]({target})")

print(f"Issues found: {len(issues)}")
for i in issues:
    print(" -", i)