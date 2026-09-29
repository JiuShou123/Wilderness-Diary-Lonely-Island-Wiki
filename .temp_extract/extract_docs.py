# -*- coding: utf-8 -*-
"""Extract text content from all dataset documents (docx/xlsx/txt/html/doc)."""
import os
import sys
import glob
import traceback

DATASET = r"d:\WorkPlace\projects\GuDao_Wiki\dataset"
OUT = r"d:\WorkPlace\projects\GuDao_Wiki\.temp_extract"

os.makedirs(OUT, exist_ok=True)


def extract_docx(path):
    import docx
    doc = docx.Document(path)
    lines = []
    # paragraphs
    for p in doc.paragraphs:
        t = p.text.strip()
        if t:
            lines.append(t)
    # tables
    for ti, table in enumerate(doc.tables):
        lines.append(f"\n[表格 {ti + 1}]")
        for row in table.rows:
            cells = [c.text.replace("\n", " ").strip() for c in row.cells]
            lines.append(" | ".join(cells))
    return "\n".join(lines)


def extract_xlsx(path):
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    lines = []
    for ws in wb.worksheets:
        lines.append(f"\n===== 工作表: {ws.title} (dims={ws.dimensions}) =====")
        for row in ws.iter_rows(values_only=True):
            vals = ["" if v is None else str(v).replace("\n", " ").strip() for v in row]
            if any(vals):
                lines.append(" | ".join(vals))
    return "\n".join(lines)


def extract_txt(path):
    for enc in ("utf-8", "gbk", "gb18030", "utf-16"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except (UnicodeDecodeError, UnicodeError):
            continue
    with open(path, "rb") as f:
        return f.read().decode("utf-8", errors="replace")


def extract_html(path):
    text = extract_txt(path)
    import re
    text = re.sub(r"<script[\s\S]*?</script>", " ", text, flags=re.I)
    text = re.sub(r"<style[\s\S]*?</style>", " ", text, flags=re.I)
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
    text = re.sub(r"</(p|div|tr|li|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    import html as htmlmod
    text = htmlmod.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return text.strip()


def extract_doc(path):
    """Old binary .doc - try several fallbacks."""
    # Fallback 1: antiword / catdoc if available
    import subprocess
    for cmd in (["antiword", path], ["catdoc", path]):
        try:
            r = subprocess.run(cmd, capture_output=True, timeout=30)
            if r.returncode == 0 and r.stdout:
                for enc in ("utf-8", "gbk"):
                    try:
                        return r.stdout.decode(enc)
                    except UnicodeDecodeError:
                        continue
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
    # Fallback 2: raw utf-16 text extraction from WordDocument stream chunks
    with open(path, "rb") as f:
        raw = f.read()
    # try to find utf-16le runs of CJK text
    import re
    chunks = []
    # crude: decode whole file as utf-16le ignoring errors, keep CJK segments
    try:
        s = raw.decode("utf-16-le", errors="ignore")
        for seg in re.findall(r"[\u4e00-\u9fff\u3000-\u303f\uff00-\uffefA-Za-z0-9\s，。、：；！？（）【】《》\-—…·%+*/=<>\[\]()\"'~]{8,}", s):
            seg = seg.strip()
            if len(seg) >= 8 and re.search(r"[\u4e00-\u9fff]", seg):
                chunks.append(seg)
    except Exception:
        pass
    return "\n".join(chunks)


files = sorted(os.listdir(DATASET))
report = []
for name in files:
    path = os.path.join(DATASET, name)
    if not os.path.isfile(path):
        continue
    ext = os.path.splitext(name)[1].lower()
    out_path = os.path.join(OUT, name + ".txt")
    try:
        if ext == ".docx":
            content = extract_docx(path)
        elif ext == ".xlsx":
            content = extract_xlsx(path)
        elif ext == ".txt":
            content = extract_txt(path)
        elif ext in (".html", ".htm"):
            content = extract_html(path)
        elif ext == ".doc":
            content = extract_doc(path)
        else:
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(content)
        report.append(f"OK   {name} -> {len(content)} chars")
    except Exception as e:
        report.append(f"FAIL {name}: {e}\n{traceback.format_exc()}")

print("\n".join(report))