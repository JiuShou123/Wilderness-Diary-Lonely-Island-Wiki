# -*- coding: utf-8 -*-
"""Repair corrupt docx (bad CRC media) and extract embedded media from big docx files."""
import os
import zipfile
import shutil

DATASET = r"d:\WorkPlace\projects\GuDao_Wiki\dataset"
OUT = r"d:\WorkPlace\projects\GuDao_Wiki\.temp_extract"
MEDIA_DIR = os.path.join(OUT, "docx_media")
os.makedirs(MEDIA_DIR, exist_ok=True)


def repair_docx(src, dst):
    """Rebuild zip skipping entries with bad CRC (usually media files)."""
    repaired = False
    with zipfile.ZipFile(src) as zin:
        with zipfile.ZipFile(dst, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                try:
                    data = zin.read(info.filename)
                except zipfile.BadZipFile:
                    repaired = True
                    print(f"   skipped corrupt entry: {info.filename}")
                    continue
                zout.writestr(info, data)
    return repaired


# 1) Repair the corrupt one
src = os.path.join(DATASET, "零氪有广速推攻略（朕将）(1).docx")
dst = os.path.join(OUT, "零氪有广速推攻略（朕将）(1).repaired.docx")
print("Repairing:", os.path.basename(src))
repair_docx(src, dst)

import docx
doc = docx.Document(dst)
lines = []
for p in doc.paragraphs:
    t = p.text.strip()
    if t:
        lines.append(t)
for ti, table in enumerate(doc.tables):
    lines.append(f"\n[表格 {ti + 1}]")
    for row in table.rows:
        cells = [c.text.replace("\n", " ").strip() for c in row.cells]
        lines.append(" | ".join(cells))
content = "\n".join(lines)
with open(os.path.join(OUT, "零氪有广速推攻略（朕将）(1).docx.txt"), "w", encoding="utf-8") as f:
    f.write(content)
print(f"   extracted {len(content)} chars")

# 2) Extract embedded media from docx files that are image-heavy
heavy = [
    "荒野日记：孤岛生存攻略总集.docx",
    "挑15全地图怪物及资源（于一）.docx",
    "荒野求生副本及剧情.docx",
]
for name in heavy:
    path = os.path.join(DATASET, name)
    sub = os.path.join(MEDIA_DIR, os.path.splitext(name)[0])
    os.makedirs(sub, exist_ok=True)
    count = 0
    with zipfile.ZipFile(path) as z:
        for info in z.infolist():
            if info.filename.startswith("word/media/"):
                try:
                    data = z.read(info.filename)
                except zipfile.BadZipFile:
                    continue
                ext = os.path.splitext(info.filename)[1]
                outname = f"img{count:02d}{ext}"
                with open(os.path.join(sub, outname), "wb") as f:
                    f.write(data)
                print(f"   {name} -> {outname} ({len(data)} bytes)")
                count += 1
    print(f"{name}: {count} media files")