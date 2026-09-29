# -*- coding: utf-8 -*-
"""
build_manifest.py —— 为 Wiki 网页应用生成内容清单（manifest.json）

用途：
    扫描 wiki/ 目录下的全部 Markdown 文件，提取标题（取自 YAML front matter）
    与分类（取自目录名），生成 wiki/manifest.json，供网页应用在
    「本地 HTTP 服务器」模式下自动加载内容。

用法：
    python app/tools/build_manifest.py [--wiki 路径] [--out 路径]

说明：
    仅依赖 Python 标准库。每次新增 / 修改 wiki 页面后重新运行即可刷新清单。
"""
import argparse
import json
import os
import re
import sys
from datetime import datetime

# 默认路径：脚本位于 app/tools/，向上一级到项目根，再定位 wiki/
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
DEFAULT_WIKI = os.path.join(ROOT, "wiki")
DEFAULT_OUT = os.path.join(DEFAULT_WIKI, "manifest.json")

FRONT_MATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.S)
TITLE_RE = re.compile(r"^title\s*:\s*(.+)$", re.M)


def read_title(path):
    """读取 Markdown 文件的标题：优先 front matter 的 title，其次首个一级标题。"""
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read(4096)  # 只读开头即可（front matter 总在最前）
    except OSError:
        return os.path.splitext(os.path.basename(path))[0]

    m = FRONT_MATTER_RE.match(text)
    if m:
        t = TITLE_RE.search(m.group(1))
        if t:
            return t.group(1).strip().strip('"').strip("'")

    h1 = re.search(r"^#\s+(.+)$", text, re.M)
    if h1:
        return h1.group(1).strip()
    return os.path.splitext(os.path.basename(path))[0]


def build(wiki_dir):
    """递归扫描 wiki 目录，返回清单 dict。"""
    files = []
    for dirpath, _dirnames, filenames in os.walk(wiki_dir):
        for name in sorted(filenames):
            if not name.lower().endswith(".md"):
                continue
            abspath = os.path.join(dirpath, name)
            relpath = os.path.relpath(abspath, wiki_dir).replace("\\", "/")
            if relpath == "manifest.json":
                continue
            files.append({
                "path": relpath,
                "title": read_title(abspath),
                "category": relpath.split("/")[0] if "/" in relpath else "首页",
                "size": os.path.getsize(abspath),
            })
    # 排序：README 置顶，其余按路径中数字前缀与名称自然排序
    files.sort(key=lambda f: (f["path"] != "README.md", f["path"]))
    return {
        "generated": datetime.now().isoformat(timespec="seconds"),
        "count": len(files),
        "files": files,
    }


def main():
    parser = argparse.ArgumentParser(description="生成 Wiki 内容清单 manifest.json")
    parser.add_argument("--wiki", default=DEFAULT_WIKI, help="wiki 目录路径")
    parser.add_argument("--out", default=DEFAULT_OUT, help="输出 manifest.json 路径")
    args = parser.parse_args()

    if not os.path.isdir(args.wiki):
        print(f"[错误] 找不到 wiki 目录：{args.wiki}", file=sys.stderr)
        sys.exit(1)

    data = build(args.wiki)
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"[完成] 共收录 {data['count']} 个页面 -> {args.out}")


if __name__ == "__main__":
    main()