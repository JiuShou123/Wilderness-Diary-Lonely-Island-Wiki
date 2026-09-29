# -*- coding: utf-8 -*-
"""Direct XML-level extraction from the corrupt docx + media extraction from heavy docx."""
import os
import zipfile
import re
import xml.etree.ElementTree as ET

DATASET = r"d:\WorkPlace\projects\GuDao_Wiki\dataset"
OUT = r"d:\WorkPlace\projects\GuDao_Wiki\.temp_extract"
MEDIA_DIR = os.path.join(OUT, "docx_media")
os.makedirs(MEDIA_DIR, exist_ok=True)

NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}


def docx_xml_text(path):
    """Extract all text from word/document.xml directly, tolerating broken media."""
    with zipfile.ZipFile(path) as z:
        xml = z.read("word/document.xml")
    root = ET.fromstring(xml)
    paras = []
    for p in root.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}p"):
        texts = [t.text or "" for t in p.iter("{http://schemas.openxmlformats.org/wordprocessingml/2006/main}t")]
        line = "".join(texts).strip()
        if line:
            paras.append(line)
    return "\n".join(paras)


src = os.path.join(DATASET, "零氪有广速推攻略（朕将）(1).docx")
content = docx_xml_text(src)
with open(os.path.join(OUT, "零氪有广速推攻略（朕将）(1).docx.txt"), "w", encoding="utf-8") as f:
    f.write(content)
print(f"零氪有广速推攻略: {len(content)} chars")

# table rows may be flattened; check t count of table cells too
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
                count += 1
    print(f"{name}: {count} media files extracted")