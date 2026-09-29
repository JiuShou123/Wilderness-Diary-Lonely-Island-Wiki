# -*- coding: utf-8 -*-
"""
gw_data.py —— Wiki 内容生成器 · 数据层

职责：从既有的 Wiki 页面（Markdown 表格）与原始资料提取结构化数据，
供 generate_wiki.py 渲染为「树状结构的叶子节点页面 + 分类枢纽页面」。

设计原则：
    - 解析对象是项目内自产的 Markdown（表格格式统一），按「表头签名」定位表格，容错优先；
    - 所有解析失败均不中断，尽量保留部分结果并在统计中提示；
    - 全部返回纯 Python 数据结构（dict/list），不依赖第三方库。
"""
import os
import re

# 项目根与 wiki 目录
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))
WIKI = os.path.join(ROOT, "wiki")
TEMP = os.path.join(ROOT, ".temp_extract")


def read(path):
    """读取文本（utf-8）。"""
    with open(path, encoding="utf-8") as f:
        return f.read()


# ============================ Markdown 解析工具 ============================

def split_sections(md, levels=(2, 3, 4)):
    """
    将 Markdown 按标题切分。
    返回 [(level, title, body, parent_title)]：
        parent_title 为该标题的上级标题（用于确定归属分组）。
    """
    lines = md.splitlines()
    heads = []  # (index, level, title)
    in_fence = False
    for i, l in enumerate(lines):
        if re.match(r"^\s*(```+|~~~+)", l):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", l)
        if m:
            lv = len(m.group(1))
            if lv in levels:
                heads.append((i, lv, m.group(2)))
    out = []
    stack = {}  # level -> title（最近的上级标题）
    for idx, (i, lv, title) in enumerate(heads):
        end = heads[idx + 1][0] if idx + 1 < len(heads) else len(lines)
        body = "\n".join(lines[i + 1:end]).strip("\n")
        parent = ""
        for pl in range(lv - 1, 0, -1):
            if pl in stack:
                parent = stack[pl]
                break
        stack[lv] = title
        for deeper in [k for k in stack if k > lv]:
            del stack[deeper]
        out.append((lv, title, body, parent))
    return out


def raw_section(md, title, level):
    """
    提取指定标题的「完整节内容」：从该标题起，直到出现同级或更高级标题为止
    （包含其下所有子标题与小节，适合需要整段搬运的场景）。
    """
    lines = md.splitlines()
    out, capture = [], False
    for l in lines:
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", l)
        if m:
            lv, t = len(m.group(1)), m.group(2)
            if capture and lv <= level:
                break
            if (not capture) and lv == level and t == title:
                capture = True
                continue
        if capture:
            out.append(l)
    return "\n".join(out).strip("\n")


def parse_tables(md):
    """
    解析全部 GFM 表格。
    返回 [{header: [...], rows: [[...]], section: 最近的任意级标题,
           parent: 最近的二级标题, line: 行号}]
    """
    lines = md.splitlines()
    tables = []
    cur_section = ""
    cur_parent = ""
    in_fence = False
    i = 0
    while i < len(lines):
        l = lines[i]
        if re.match(r"^\s*(```+|~~~+)", l):
            in_fence = not in_fence
            i += 1
            continue
        if in_fence:
            i += 1
            continue
        m = re.match(r"^(#{1,6})\s+(.*?)\s*$", l)
        if m:
            level = len(m.group(1))
            title = m.group(2)
            if level <= 2:
                cur_parent = title
            cur_section = title
            i += 1
            continue
        if l.strip().startswith("|") and i + 1 < len(lines) and is_sep_row(lines[i + 1]):
            header = split_row(l)
            rows = []
            j = i + 2
            while j < len(lines) and lines[j].strip().startswith("|"):
                rows.append(split_row(lines[j]))
                j += 1
            tables.append({"header": header, "rows": rows, "section": cur_section,
                           "parent": cur_parent, "line": i + 1})
            i = j
            continue
        i += 1
    return tables


def is_sep_row(line):
    return bool(re.match(r"^\s*\|[\s:\-|]+\|\s*$", line)) and "-" in line


def split_row(line):
    s = line.strip()
    if s.startswith("|"):
        s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def clean(text):
    """清理单元格：去加粗、链接保留文本、压缩空白。"""
    t = text or ""
    t = re.sub(r"\*\*([^*]+)\*\*", r"\1", t)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = t.replace("<br>", " ").replace("（待考证）", "")
    return re.sub(r"\s+", " ", t).strip()


def find_table(tables, header_contains, section_contains=None, index=0):
    """按表头关键字（全部包含）与所属章节定位表格。"""
    hits = []
    for t in tables:
        h = "".join(t["header"])
        if all(k in h for k in header_contains):
            if section_contains and section_contains not in t["section"]:
                continue
            hits.append(t)
    return hits[index] if len(hits) > index else None


# ============================ 分类字典（人工校准） ============================

MELEE_WEAPONS = {
    "石斧", "匕首", "竹枪", "双刃斧", "毒竹枪", "毒刃斧", "锋利竹枪", "利刃斧",
    "改良的平底锅", "武士刀", "杰克之刃", "血匕", "石锤", "机关剑", "女巫的扫帚",
    "长枪", "驯兽鞭", "冰雪卷轴",
}
RANGED_WEAPONS = {
    "短弓", "硬竹弓", "朱莉的长弓", "硬竹弩", "重连弩", "燧发枪", "伪袖珍手枪", "机关连弩",
}
AMMO_ITEMS = {"箭矢", "毒羽箭", "寒冰箭", "弹药"}
THROW_WEAPONS = {"投掷飞刀", "竹筒炸药", "毒液炸药", "精致炸药", "小鞭炮", "雪球", "麻痹针", "吹箭"}
ARMORS = {"皮甲", "藤甲", "老贝的草裙", "某人的新衣", "旧棉衣", "棉衣", "防护服", "羽毛裙"}
TOOLS = {"火把", "基德的罗盘", "罗盘", "小哥的手电", "老贝的研磨器", "绳索", "荒野秘宝", "不明棱梭", "麻痹针"}

MONSTER_SUBCATS = [
    "狼系", "猪系", "熊系", "蛇系", "猫科", "鳄鱼与龟", "鱼类怪", "食人族",
    "鲨鱼", "崖洞与遗迹怪物", "破风口变异怪物", "机关甲人系（沉船一侧）", "其他生物与活动生物",
]
MONSTER_SUBCAT_DIR = {
    "狼系": "狼系", "猪系": "猪系", "熊系": "熊系", "蛇系": "蛇系", "猫科": "猫科",
    "鳄鱼与龟": "鳄鱼与龟", "鱼类怪": "鱼类怪", "食人族": "食人族", "鲨鱼": "鲨鱼",
    "崖洞与遗迹怪物": "崖洞与遗迹", "破风口变异怪物": "破风口变异", "机关甲人系（沉船一侧）": "机关造物",
    "其他生物与活动生物": "其他生物",
}

# 解析噪声词（用于过滤掉落文本中的非条目短语）
JUNK_RE = re.compile(r"(掉落|概率|应该|发现|大概|一般|据说|似乎|如果|只是|就是|没有|不掉)")

# ============================ 补充数据解析器 ============================

def load_themes():
    """从 挑战模式.md 提取挑战主题与主题池。"""
    md = read(os.path.join(WIKI, "02-核心机制", "挑战模式.md"))
    tables = parse_tables(md)
    themes, pools = [], []
    t = find_table(tables, ["主题", "效果"])
    if t:
        for r in t["rows"]:
            row = dict(zip(t["header"], r))
            name = clean(row.get("主题", ""))
            if not name or name == "主题":
                continue
            themes.append({
                "name": name,
                "effect": clean(row.get("效果", "")),
                "tip": clean(row.get("应对参考（玩家总结）", row.get("应对", ""))),
            })
    p = find_table(tables, ["挑战难度", "主题池"])
    if p:
        for r in p["rows"]:
            row = dict(zip(p["header"], r))
            if clean(row.get("挑战难度", "")):
                pools.append({"level": clean(row["挑战难度"]), "pool": clean(row.get("主题池构成", ""))})
    return themes, pools


def load_adventures():
    """从 奇遇系统.md 提取奇遇（归属角色 + 正文）。"""
    md = read(os.path.join(WIKI, "02-核心机制", "奇遇系统.md"))
    sections = split_sections(md, (2, 3))
    advs, overview = [], []
    for lv, title, body, parent in sections:
        if lv == 2 and ("一览" in title or "概念" in title):
            for t in parse_tables(body):
                if "奇遇" in "".join(t["header"]):
                    for r in t["rows"]:
                        if len(r) >= 2:
                            role = clean(r[0])
                            for name in re.split(r"[、,，]", clean(r[1])):
                                if name:
                                    overview.append({"name": name, "role": role})
        elif lv == 3 and parent and "的奇遇" in parent:
            role = parent.split("、")[-1].replace("的奇遇", "").strip()
            advs.append({"name": title, "role": role, "body": raw_section(md, title, 3)})
    return advs, overview


def load_characters():
    """从 角色介绍.md 提取五个基础角色。"""
    md = read(os.path.join(WIKI, "01-游戏概览", "角色介绍.md"))
    sections = split_sections(md, (2, 3))
    chars = []
    for lv, title, body, parent in sections:
        if lv != 2:
            continue
        m = re.match(r"^[一二三四五六七八九十]+、(.+?)（(.+?)）", title)
        if m:
            chars.append({"name": m.group(1), "role": m.group(2),
                          "body": raw_section(md, title, 2)})
    return chars


def load_escapes():
    """从 逃离方式.md 提取逃离方式（总览表 + 分节正文）。"""
    md = read(os.path.join(WIKI, "04-攻略指南", "逃离方式.md"))
    sections = split_sections(md, (2, 3))
    overview, escapes = [], []
    for lv, title, body, parent in sections:
        if lv == 2 and "总览" in title:
            for t in parse_tables(body):
                if "方式" in "".join(t["header"]):
                    for r in t["rows"]:
                        if len(r) >= 4:
                            overview.append({"no": clean(r[0]), "name": clean(r[1]),
                                             "type": clean(r[2]), "cond": clean(r[3])})
        elif lv == 3:
            m = re.match(r"^\d+\.\d+\s*(.+)$", title)
            if m:
                escapes.append({"name": m.group(1), "body": raw_section(md, title, 3),
                                "parent": parent})
    return overview, escapes


def load_minigames():
    """从小游戏攻略.md 提取小游戏完整分节（含子标题）。"""
    md = read(os.path.join(WIKI, "04-攻略指南", "小游戏攻略.md"))
    sections = split_sections(md, (2,))
    games = []
    for lv, title, body, parent in sections:
        m = re.match(r"^[一二三四五六七八九十]+、(.+)$", title)
        if m:
            games.append({"name": m.group(1), "body": raw_section(md, title, 2)})
    return games


def load_maps():
    """从 地图与关卡.md 提取全部地图分节（含所属区域）。"""
    md = read(os.path.join(WIKI, "02-核心机制", "地图与关卡.md"))
    sections = split_sections(md, (2, 3))
    maps, groups, other = [], {}, {}
    for lv, title, body, parent in sections:
        if lv == 2:
            key = re.sub(r"^[一二三四五六七八九十]+、", "", title)
            other[key] = body
        elif lv == 3:
            m = re.match(r"^\d+\.\d+\s*(.+)$", title)
            if not m:
                continue
            name = m.group(1)
            if name in ("地图解锁顺序", "波数与怪物顺序规则", "各资源点满值与单次产出",
                        "资源间制约关系", "资源点再生时间", "基德的罗盘",
                        "挑战模式新增野怪及出现地图"):
                continue  # 这些是机制小节，留在总览页
            mp = re.match(r"^(.+?)（共\s*(\d+)\s*/\s*(\d+)\s*波）$", name)
            if mp:
                name, waves = mp.group(1), mp.group(2) + "/" + mp.group(3)
            else:
                waves = ""
            maps.append({"name": name, "waves": waves,
                         "body": raw_section(md, title, 3), "group": parent})
    return maps, other


def load_growth():
    """从 生物图鉴.md 提取随天数成长表（按生物）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "生物图鉴.md"))
    t = find_table(parse_tables(md), ["怪物", "1–20 日"])
    growth = {}
    if t:
        for r in t["rows"]:
            if not r or not r[0]:
                continue
            row = dict(zip(t["header"], r))
            name = clean(row.get("怪物", ""))
            if name:
                growth[name] = {k: clean(v) for k, v in row.items() if k != "怪物"}
    return growth


def load_special_notes():
    """从 生物图鉴.md「五、怪物特殊机制与战斗要点」提取各小节文字。"""
    md = read(os.path.join(WIKI, "03-数据资料", "生物图鉴.md"))
    sections = split_sections(md, (2, 3))
    notes = []
    for lv, title, body, parent in sections:
        if lv == 3 and parent and "特殊机制" in parent:
            notes.append({"title": title, "body": body})
    return notes


def load_drops():
    """
    从《挑15全地图怪物及资源》提取掉落关系。
    返回 (monster_drops, item_sources, map_drops)：
        monster_drops: {怪物名: [物品名...]}
        item_sources:  {物品名: [(地图, 来源描述)...]}
        map_drops:     {地图名: 描述列表}
    """
    path = os.path.join(TEMP, "挑15全地图怪物及资源（于一）.docx.txt")
    if not os.path.exists(path):
        return {}, {}, {}
    text = read(path)
    monster_drops, item_sources, map_drops = {}, {}, {}
    cur_map = ""
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # 更新当前地图名（以「：」结尾的行，或形如「第N重（共4波）：」）
        if line.endswith("：") and "注" not in line:
            m = re.match(r"^([^（(：]+)", line)
            if m and len(m.group(1)) <= 12:
                cur_map = m.group(1).strip()
                continue
        if cur_map and cur_map not in map_drops:
            map_drops[cur_map] = []
        # 掉落：括号内为怪物列表，其后出现「掉落」
        for grp in re.findall(r"[（(]([^）)]+)[）)]", line):
            names = [re.sub(r"\d+$", "", n) for n in re.split(r"[、,，]", grp)]
            names = [n for n in names
                     if re.match(r"^[\u4e00-\u9fff]{2,6}$", n) and not JUNK_RE.search(n)]
            if not names:
                continue
            if "掉落" in line:
                drop_text = line.split("掉落", 1)[1]
                drop_text = re.sub(r"[（(].*?[）)]", "", drop_text)
                for n in names:
                    monster_drops.setdefault(n, [])
                    for d in re.split(r"[、,，]", drop_text):
                        # 仅保留中文名（去掉数量、括号、标点等）
                        d_name = "".join(re.findall(r"[\u4e00-\u9fff]+", d))
                        d_name = re.sub(r"^(?:只)?(?:大|小)?概率|^偶尔|^可能|^随机|^额外|^只", "", d_name)
                        if not d_name or len(d_name) > 6 or JUNK_RE.search(d_name):
                            continue
                        if d_name not in monster_drops[n]:
                            monster_drops[n].append(d_name)
                        item_sources.setdefault(d_name, [])
                        tag = (cur_map, f"{n}掉落")
                        if tag not in item_sources[d_name]:
                            item_sources[d_name].append(tag)
            elif re.search(r"(手|斧)\s*\d+\s*min", line):
                # 资源节点：如「乱石块（石块5）手60min」
                for n in names:
                    if re.match(r"^[\u4e00-\u9fff]{2,}$", n):
                        cnt = re.search(r"[（(]" + n + r"(\d+)[）)]", line)
                        desc = f"采集（{('x' + cnt.group(1)) if cnt else ''}）"
                        item_sources.setdefault(n, [])
                        tag = (cur_map, desc)
                        if tag not in item_sources[n]:
                            item_sources[n].append(tag)
                        if cur_map:
                            map_drops.setdefault(cur_map, []).append(f"{n}{('x' + cnt.group(1)) if cnt else ''}")
    return monster_drops, item_sources, map_drops


def load_trade():
    """从 NPC系统.md 交易价格总表提取 物品->价格。"""
    md = read(os.path.join(WIKI, "03-数据资料", "NPC系统.md"))
    tables = parse_tables(md)
    trade = {}
    for t in tables:
        if "价格" not in "".join(t["header"]):
            continue
        if "交易" not in t["section"] and "价格" not in t["section"]:
            continue
        for r in t["rows"]:
            if len(r) < 2:
                continue
            price = clean(r[0])
            items = clean(r[-1])
            for name in re.split(r"[、,，]", items):
                name = name.strip()
                if name and re.match(r"^[\u4e00-\u9fff]", name):
                    trade[name] = price
    return trade


# ============================ 核心数据解析器 ============================

def load_weapons():
    """从 装备与武器.md 提取武器/防具/工具条目（合并武器总表与满科技属性表）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "装备与武器.md"))
    tables = parse_tables(md)
    weapons = []
    for t in tables:
        h = t["header"]
        if len(h) < 5:
            continue
        # 武器总表：序号|武器|耐久|攻击|会心一击|距离/频率|暴击几率|特效
        if h[0] == "序号" and "武器" in h:
            for r in t["rows"]:
                if len(r) < 3 or not r[1]:
                    continue
                row = dict(zip(h, r))
                weapons.append({
                    "name": clean(row.get("武器", "")),
                    "durability": clean(row.get("耐久", "")),
                    "attack": clean(row.get("攻击", "")),
                    "crit": clean(row.get("暴击几率", "")),
                    "range": clean(row.get("距离/频率", "")),
                    "critdmg": clean(row.get("会心一击", "")),
                    "note": clean(row.get("特效", row.get("其他", ""))),
                    "weight": "", "speed": "", "buff": "", "source": "",
                    "craft": "", "pros": "", "cons": "",
                    "category": infer_weapon_category(clean(row.get("武器", ""))),
                })
        # 防具总表：防具|防御|耐久|温度|防寒|buff/特效|主要获取方式
        elif h[0] == "防具":
            for r in t["rows"]:
                if len(r) < 2 or not r[0]:
                    continue
                row = dict(zip(h, r))
                weapons.append({
                    "name": clean(row.get("防具", "")),
                    "durability": clean(row.get("耐久", "")),
                    "attack": clean(row.get("防御", "")),
                    "range": clean(row.get("温度", "")),
                    "crit": clean(row.get("防寒", "")),
                    "note": clean(row.get("buff/特效", "")),
                    "source": clean(row.get("主要获取方式", "")),
                    "weight": "", "speed": "", "buff": "", "craft": "",
                    "pros": "", "cons": "", "category": "防具",
                })
        # 满科技属性表：名称|重量|攻击力|耐久度|攻速|攻击距离|buff|主要获取方式|制作消耗|优势|劣势|说明/评价
        elif h[0] == "名称" and "攻击力" in h:
            for r in t["rows"]:
                if len(r) < 3 or not r[0]:
                    continue
                row = dict(zip(h, r))
                name = clean(row.get("名称", ""))
                weapons.append({
                    "name": name,
                    "weight": clean(row.get("重量", "")),
                    "attack": clean(row.get("攻击力", "")),
                    "durability": clean(row.get("耐久度", "")),
                    "speed": clean(row.get("攻速", "")),
                    "range": clean(row.get("攻击距离", row.get("攻击范围", ""))),
                    "crit": "", "critdmg": "",
                    "buff": clean(row.get("buff", "")),
                    "source": clean(row.get("主要获取方式", "")),
                    "craft": clean(row.get("制作消耗", "")),
                    "pros": clean(row.get("优势", "")),
                    "cons": clean(row.get("劣势", "")),
                    "note": clean(row.get("说明/评价", "")),
                    "category": infer_weapon_category(name),
                })
    # 合并同名条目（总表 + 满科技）
    merged = {}
    for w in weapons:
        name = w["name"]
        if not name or name in ("武器", "防具", "名称"):
            continue
        e = merged.setdefault(name, dict(w))
        for k, v in w.items():
            if v and not e.get(k):
                e[k] = v
    return list(merged.values())


def infer_weapon_category(name):
    base = re.sub(r"[（(](普|毒|冰)[)）]", "", name)
    if base in MELEE_WEAPONS:
        return "近战武器"
    if base in RANGED_WEAPONS:
        return "远程武器"
    if base in AMMO_ITEMS:
        return "远程武器"
    if base in THROW_WEAPONS:
        return "投掷武器"
    if base in ARMORS:
        return "防具"
    if base in TOOLS:
        return "工具"
    return "近战武器"


def load_monsters():
    """从 生物图鉴.md 提取生物（普通模式总表 + 挑战模式基础属性表）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "生物图鉴.md"))
    sections = split_sections(md, (2, 3))
    monsters, seen = [], set()
    for lv, title, body, parent in sections:
        if lv == 3 and title in MONSTER_SUBCATS:
            for t in parse_tables(body):
                h = t["header"]
                if not h or h[0] not in ("名称", "怪物"):
                    continue
                for r in t["rows"]:
                    if len(r) < 2 or not r[0]:
                        continue
                    row = dict(zip(h, r))
                    name = clean(row.get("名称", row.get("怪物", "")))
                    if not name or name in ("名称", "怪物", "其他"):
                        continue
                    key = name + "|" + title
                    if key in seen:
                        continue
                    seen.add(key)
                    hp = clean(row.get("HP-甲", row.get("HP", "")))
                    hp2 = clean(row.get("HP-乙", ""))
                    monsters.append({
                        "name": name,
                        "hp": hp + (f" / {hp2}" if hp2 and hp2 != hp else ""),
                        "attack": "", "hit": "", "dodge": "", "speed": "", "special": "",
                        "location": clean(row.get("出现地点", "")),
                        "category": MONSTER_SUBCAT_DIR.get(title, "其他生物"),
                        "challenge": False,
                        "source_section": title,
                    })
    for t in parse_tables(md):
        h = t["header"]
        if len(h) < 4 or h[0] != "物种":
            continue
        for r in t["rows"]:
            if len(r) < 4 or not r[0]:
                continue
            row = dict(zip(h, r))
            name = clean(row.get("物种", ""))
            if not name or name == "物种":
                continue
            key = name + "|挑战"
            if key in seen:
                continue
            seen.add(key)
            monsters.append({
                "name": name,
                "hp": clean(row.get("血量", "")),
                "attack": clean(row.get("攻击", "")),
                "hit": clean(row.get("命中", "")),
                "dodge": clean(row.get("闪避", "")),
                "speed": clean(row.get("移速", "")),
                "special": clean(row.get("特性", "")),
                "location": "", "category": "其他生物",
                "challenge": True, "source_section": "挑战模式生物属性表",
            })
    return monsters


def load_fish():
    """从 钓鱼系统.md 提取鱼类（条件总表 + 效果总表合并）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "钓鱼系统.md"))
    tables = parse_tables(md)
    merged = {}
    for t in tables:
        h = t["header"]
        if not h or h[0] not in ("名称", "序号"):
            continue
        sec = t["section"]
        if "钓鱼条件" not in sec and "效果" not in sec:
            continue
        for r in t["rows"]:
            if len(r) < 2:
                continue
            row = dict(zip(h, r))
            name = clean(row.get("名称", ""))
            if not name or name == "名称":
                continue
            e = merged.setdefault(name, {
                "name": name, "prob": "", "temp": "", "time": "", "season": "",
                "bait": "", "days": "", "weight": "", "price": "", "hunger": "",
                "recover": "", "buff": "", "duration": "", "note": "",
            })
            for src, dst in [("概率", "prob"), ("温度", "temp"), ("时间（点）", "time"),
                             ("季节", "season"), ("鱼饵", "bait"), ("天数／其他", "days"),
                             ("重量", "weight"), ("价格", "price"), ("饥饿度", "hunger"),
                             ("状态恢复", "recover"), ("buff／道具", "buff"),
                             ("持续时间", "duration"), ("说明", "note")]:
                v = clean(row.get(src, ""))
                if v and not e[dst]:
                    e[dst] = v
    return list(merged.values())


def load_npcs():
    """从 NPC系统.md 提取 NPC（一级小节正文）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "NPC系统.md"))
    sections = split_sections(md, (2, 3))
    wanted = {"白狼": "宠物", "骆驼": "坐骑", "野蛮人（土著）": "商人 / 剧情",
              "金雕": "宠物（账号级）", "神秘人": "抽奖（账号级）", "机关甲人": "资源点（账号级）"}
    npcs = []
    for lv, title, body, parent in sections:
        if lv != 2:
            continue
        # 标题形如「一、白狼」，先剥离序号
        m = re.match(r"^[一二三四五六七八九十]+、(.+)$", title)
        name_only = (m.group(1) if m else title).strip()
        if name_only in wanted:
            name = name_only.replace("（土著）", "")
            npcs.append({"name": name, "subcat": wanted[name_only],
                         "body": raw_section(md, title, 2)})
    return npcs


def load_recipes():
    """从 建筑与制造.md 提取全部配方（产物 + 素材 + 制作台）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "建筑与制造.md"))
    recipes = []
    for t in parse_tables(md):
        h = t["header"]
        if not h or h[0] != "产物":
            continue
        for r in t["rows"]:
            if len(r) < 3 or not r[0]:
                continue
            row = dict(zip(h, r))
            recipes.append({
                "name": clean(row.get("产物", "")),
                "condition": clean(row.get("制作条件", "")),
                "level": clean(row.get("等级", "")),
                "materials": clean(row.get("素材", "")),
                "time": clean(row.get("时间", "")),
                "pass_time": clean(row.get("经过时间", "")),
                "section": t["section"],
            })
    return recipes


def load_talents():
    """从 天赋系统.md 提取天赋（类别 + 各星级效果）。"""
    md = read(os.path.join(WIKI, "02-核心机制", "天赋系统.md"))
    tables = parse_tables(md)
    cat_map = {"二、战斗天赋": "战斗天赋", "三、生存天赋": "生存天赋", "四、探索天赋": "探索天赋"}
    talents = []
    for t in tables:
        h = t["header"]
        if len(h) < 2 or h[0] != "天赋":
            continue
        for r in t["rows"]:
            if len(r) < 2 or not r[0]:
                continue
            row = dict(zip(h, r))
            talents.append({
                "name": clean(row.get("天赋", "")),
                "cat": cat_map.get(t["section"], "天赋"),
                "effect": clean(list(row.values())[1]),
            })
    return talents


# 掉落补充说明（人工校准：来自《挑15全地图怪物及资源》与《攻略总集》文字描述）
DROP_NOTES = {
    "默认": "大地图怪物大多会掉落生肉",
    "毒蛇": "大概率掉落毒液",
    "毒蝎": "大概率掉落毒液",
    "食人鱼": "概率掉落生肉（暗流食人鱼不掉珍珠）",
    "猛虎": "大概率掉落兽皮",
    "熊王": "掉落兽皮、兽筋、兽血",
    "受伤的熊王": "掉落兽皮、兽筋、兽血",
    "野猪王": "掉落兽筋、兽血",
    "眼镜王蛇": "掉落兽筋、兽血",
    "虎王": "掉落兽皮",
    "河马": "概率掉落兽筋",
    "剑吻鲨": "概率掉落生肉",
    "大白鲨": "概率掉落生肉",
    "绵羊": "掉落羊毛",
    "雪狼": "概率掉落兽筋",
    "白熊": "概率掉落兽皮、兽筋",
    "灰熊": "概率掉落兽皮",
    "暴躁的灰熊": "概率掉落兽皮",
    "食人族战士": "概率掉落毒羽箭、宠物口粮",
    "食人族队长": "概率掉落毒羽箭、宠物口粮",
    "食人族首领": "概率掉落毒羽箭、宠物口粮",
    "食人族守卫": "概率掉落毒羽箭",
    "沼泽湿地怪物": "本地图怪物均大概率掉落兽筋",
    "戈壁遗迹怪物": "本地图狼与蜥蜴不掉落生肉",
    "变异研究员": "掉落研究资料",
    "变异小白鼠": "掉落瘤块",
    "变异猎狗": "掉落瘤块（属狼类）",
    "变异野猪": "掉落瘤块",
    "机关甲人": "掉落石块、木材、藤条、铁矿等",
    "机关甲兵": "掉落石块、木材等",
    "机关猛兽": "掉落石块、木材等",
    "遗迹石像": "掉落石块（部分）",
    "暴躁狐猴": "掉落赤芝、地衣",
    "蝙蝠": "掉落木耳",
}