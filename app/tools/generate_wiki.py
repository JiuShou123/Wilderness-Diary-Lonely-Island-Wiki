# -*- coding: utf-8 -*-
"""
generate_wiki.py —— Wiki 内容生成器（树状结构重构）

目标：把原先「单页罗列同类物品」的平铺内容，重构为 Terraria Wiki 式的树状结构：
    - 叶子节点：每一个物品 / 生物 / 地图 / 天赋 / 主题 / 奇遇 / 角色 / NPC / 建筑 /
      逃离方式 / 小游戏，各占一个独立页面，含信息框（infobox）与分节正文；
    - 枢纽节点（分类页）：只负责罗列与链接下级页面，不承载条目详情；
    - 首页 README.md：门户式首页（英雄区 + 分类导航卡片 + 统计）。

同时：
    - 移动保留的机制/攻略/收集类文章到新目录，并全量重映射页面内链接；
    - 删除被树状结构取代的旧「图鉴」集中页。

用法：python app/tools/generate_wiki.py
"""
import os
import re
import json
import posixpath
import shutil
from collections import defaultdict, OrderedDict

import gw_data as G
from gw_data import (
    read, split_sections, parse_tables, find_table, clean,
    MELEE_WEAPONS, RANGED_WEAPONS, AMMO_ITEMS, THROW_WEAPONS, ARMORS, TOOLS,
    MONSTER_SUBCAT_DIR, MONSTER_SUBCATS,
)

WIKI = G.WIKI
TODAY = "2026-09-29"

# ============================ 目录规划 ============================

D_GUIDE = "01-游戏概览"
D_CORE = "02-核心机制"
D_ITEM = "03-物品"
D_MON = "04-生物"
D_MAP = "05-地图"
D_STRAT = "06-攻略"
D_COLL = "07-收集"
D_APP = "08-附录"

# 保留文章的迁移映射（旧路径 -> 新路径）
MOVES = {
    "01-游戏概览/游戏简介.md": "01-游戏概览/游戏简介.md",
    "01-游戏概览/背景故事.md": "01-游戏概览/背景故事.md",
    "02-核心机制/生存系统.md": "02-核心机制/生存系统.md",
    "02-核心机制/战斗系统.md": "02-核心机制/战斗系统.md",
    "02-核心机制/科技系统.md": "02-核心机制/科技系统.md",
    "02-核心机制/挑战模式.md": "02-核心机制/挑战模式.md",
    "03-数据资料/建筑与制造.md": "02-核心机制/建筑与制造.md",
    "03-数据资料/钓鱼系统.md": "02-核心机制/钓鱼系统.md",
    "03-数据资料/陷阱系统.md": "02-核心机制/陷阱系统.md",
    "03-数据资料/沉船系统.md": "05-地图/沉船/沉船.md",
    "02-核心机制/进阶技巧.md": "06-攻略/进阶技巧.md",
    "04-攻略指南/新手指南.md": "06-攻略/新手指南.md",
    "04-攻略指南/挑战攻略.md": "06-攻略/挑战攻略.md",
    "05-收集要素/成就系统.md": "07-收集/成就系统.md",
    "05-收集要素/剧情图鉴与收集.md": "07-收集/剧情图鉴与收集.md",
    "05-收集要素/账号资源系统.md": "07-收集/账号资源系统.md",
    "附录/资料来源.md": "08-附录/资料来源.md",
}

# 被树状结构取代的旧集中页（生成后删除；注意：README.md 为重新生成的首页，不在此列）
DELETE_OLD = [
    "01-游戏概览/角色介绍.md",
    "02-核心机制/地图与关卡.md",
    "02-核心机制/天赋系统.md",
    "02-核心机制/奇遇系统.md",
    "03-数据资料/物品图鉴.md",
    "03-数据资料/装备与武器.md",
    "03-数据资料/生物图鉴.md",
    "03-数据资料/NPC系统.md",
    "04-攻略指南/逃离方式.md",
    "04-攻略指南/小游戏攻略.md",
]

# 链接重映射表（旧 wiki 相对路径 -> 新 wiki 相对路径）
LINK_MAP = dict(MOVES)
LINK_MAP.update({
    "01-游戏概览/角色介绍.md": "01-游戏概览/角色/角色一览.md",
    "02-核心机制/地图与关卡.md": "05-地图/地图总览.md",
    "02-核心机制/天赋系统.md": "02-核心机制/天赋/天赋一览.md",
    "02-核心机制/奇遇系统.md": "01-游戏概览/奇遇/奇遇一览.md",
    "03-数据资料/物品图鉴.md": "03-物品/物品总览.md",
    "03-数据资料/装备与武器.md": "03-物品/物品总览.md",
    "03-数据资料/生物图鉴.md": "04-生物/生物总览.md",
    "03-数据资料/NPC系统.md": "01-游戏概览/NPC/NPC一览.md",
    "04-攻略指南/逃离方式.md": "01-游戏概览/逃离方式/逃离方式一览.md",
    "04-攻略指南/小游戏攻略.md": "02-核心机制/小游戏/小游戏一览.md",
})

# 嵌入既有正文时的「原文出处」（用于把正文内的旧链接重映射到新路径）
SRC_CHARS = "01-游戏概览/角色介绍.md"
SRC_ADV = "02-核心机制/奇遇系统.md"
SRC_NPC = "03-数据资料/NPC系统.md"
SRC_ESC = "04-攻略指南/逃离方式.md"
SRC_MG = "04-攻略指南/小游戏攻略.md"
SRC_MAP = "02-核心机制/地图与关卡.md"
SRC_MON = "03-数据资料/生物图鉴.md"

# ============================ 输出工具 ============================

generated_pages = []   # 全部生成的 wiki 相对路径（posix）


def wpath(*parts):
    """wiki 相对路径（posix 风格）。"""
    return "/".join(parts)


def abspath(rel):
    return os.path.join(WIKI, rel.replace("/", os.sep))


def rel_link(from_rel, to_rel):
    """计算从 from_rel 页到 to_rel 页的相对链接。"""
    return posixpath.relpath(to_rel, posixpath.dirname(from_rel))


def embed(body, src_rel, new_rel):
    """把既有页面的正文嵌入新页面时，将其中的站内链接重映射到新路径体系。"""
    return remap_content(body, src_rel, new_rel)


def write_page(rel, content):
    path = abspath(rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    generated_pages.append(rel)


def fm(title, category, page_type, tags=None):
    """生成 YAML front matter。"""
    t = "、".join(tags) if tags else category
    return (f"---\ntitle: {title}\n分类: {category}\n页面类型: {page_type}\n"
            f"标签: [{t}]\n更新日期: {TODAY}\n---\n\n")


def infobox(rows):
    """信息框块（由前端渲染为右侧资料卡）。"""
    lines = [f"{k} :: {v}" for k, v in rows if v not in (None, "", "—")]
    return "```wiki-infobox\n" + "\n".join(lines) + "\n```\n"


def cards(entries):
    """卡片网格块（由前端渲染为跳转卡片）。entries: [(标题, 说明, 链接)]"""
    lines = [f"{t} :: {d} :: {href}" for t, d, href in entries]
    return "```wiki-cards\n" + "\n".join(lines) + "\n```\n"


def see_also(links):
    body = "\n".join(f"- [{label}]({href})" for label, href in links)
    return f"## 参见\n\n{body}\n"


def one_liner(text, cap=46):
    t = re.sub(r"\s+", " ", text or "").strip("。；; ")
    return (t[:cap] + "…") if len(t) > cap else (t or "详见条目页")


# ============================ 数据装载 ============================

print("== 装载数据 ==")
ITEM_TABLES = {}     # 供物品解析
_raw_items = []
_weapons = []
_monsters = []
_fish = []
_npcs = []
_recipes = []
_talents = []
_themes, _pools = [], []
_adventures, _adv_overview = [], []
_characters = []
_esc_overview, _escapes = [], []
_minigames = []
_maps, _map_meta = [], {}
_growth = {}
_notes = []
_monster_drops, _item_sources, _map_drops = {}, {}, {}
_trade = {}


def load_all():
    global _raw_items, _weapons, _monsters, _fish, _recipes, _talents, _growth, _trade
    global _themes, _pools, _adventures, _adv_overview, _characters, _esc_overview
    global _escapes, _minigames, _maps, _map_meta, _notes, _monster_drops, _item_sources, _map_drops
    global _npcs

    _raw_items = parse_item_catalog()
    _weapons = G.load_weapons()
    _monsters = G.load_monsters()
    _fish = G.load_fish()
    _recipes = G.load_recipes()
    _talents = G.load_talents()
    _growth = G.load_growth()
    _trade = G.load_trade()
    _themes, _pools = G.load_themes()
    _adventures, _adv_overview = G.load_adventures()
    _characters = G.load_characters()
    _esc_overview, _escapes = G.load_escapes()
    _minigames = G.load_minigames()
    _maps, _map_meta = G.load_maps()
    _notes = G.load_special_notes()
    _monster_drops, _item_sources, _map_drops = G.load_drops()
    _npcs = G.load_npcs()
    print(f"  条目：{len(_raw_items)}，武器 {len(_weapons)}，生物 {len(_monsters)}，"
          f"鱼类 {len(_fish)}，配方 {len(_recipes)}，天赋 {len(_talents)}，"
          f"主题 {len(_themes)}，奇遇 {len(_adventures)}，地图 {len(_maps)}，"
          f"NPC {len(_npcs)}，掉落记录 {sum(len(v) for v in _monster_drops.values())}")


def parse_item_catalog():
    """解析 物品图鉴.md -> 物品条目列表（含分类归属）。"""
    md = read(os.path.join(WIKI, "03-数据资料", "物品图鉴.md"))
    tables = parse_tables(md)
    items = []
    for t in tables:
        h = t["header"]
        if not h or h[0] != "名称":
            continue
        sec = t["section"]
        if "鱼类图鉴" in sec or "贝壳购买" in sec:
            continue
        for r in t["rows"]:
            if len(r) < 2 or not r[0]:
                continue
            row = dict(zip(h, r))
            name = clean(row.get("名称", ""))
            if not name or name in ("名称",):
                continue
            subcat = classify_subcat(name, sec, t.get("parent", ""))
            if not subcat:
                continue
            items.append({
                "name": name,
                "subcat": subcat,
                "weight": clean(row.get("重量", "")),
                "price": clean(row.get("价格", "")),
                "source": clean(row.get("入手方法", row.get("获取时间（活动）", ""))),
                "effect": clean(row.get("说明/效果", row.get("效果/说明", row.get("备注", "")))),
                "origin_section": sec,
            })
    return items


def classify_subcat(name, section, parent=""):
    """根据名称与所属小节（含上级小节）判断物品分类。"""
    base = re.sub(r"[（(].*?[)）]", "", name)
    ctx = (parent or "") + "|" + (section or "")
    if name == "其他" or name.startswith("（未出现"):
        return None
    if "基础材料" in ctx:
        return "材料"
    if "食物" in ctx:
        return "食物"
    if "药品" in ctx:
        return "药品"
    if "工具与武器" in ctx or "防具" in ctx:
        if base in MELEE_WEAPONS:
            return "近战武器"
        if base in RANGED_WEAPONS or base in AMMO_ITEMS:
            return "远程武器"
        if base in THROW_WEAPONS:
            return "投掷武器"
        if base in ARMORS:
            return "防具"
        if base in TOOLS or name in ("火把", "罗盘", "小哥的手电"):
            return "工具"
        if "近战" in ctx:
            return "近战武器"
        if "远程" in ctx:
            return "远程武器"
        if "防具" in ctx:
            return "防具"
        return "特殊道具"
    if "特殊道具" in ctx or "剧情" in ctx:
        return "特殊道具"
    if "活动物品" in ctx:
        return "活动物品"
    return None


def build_registry():
    """合并全部来源，构建统一物品注册表。"""
    reg = OrderedDict()

    def ensure(name, subcat=None):
        if name not in reg:
            reg[name] = {
                "name": name, "subcat": subcat or "特殊道具", "weight": "", "price": "",
                "source": "", "effect": "", "stats": {}, "variants": [],
                "recipes_in": [], "recipes_out": None, "drops": [], "locations": [],
                "trade": "", "fish": None, "is_weapon": False,
            }
        if subcat and reg[name]["subcat"] in ("特殊道具", ""):
            reg[name]["subcat"] = subcat
        return reg[name]

    # 1) 图鉴条目
    for it in _raw_items:
        e = ensure(it["name"], it["subcat"])
        for k in ("weight", "price", "source", "effect"):
            if not e[k] and it[k]:
                e[k] = it[k]
    # 2) 武器 / 防具（含满科技）
    for w in _weapons:
        base = re.sub(r"[（(](普|毒|冰)[)）]", "", w["name"])
        e = ensure(base, w["category"])
        e["is_weapon"] = True
        for k in ("attack", "durability", "speed", "range", "crit", "buff",
                  "craft", "pros", "cons", "note"):
            if w.get(k) and not e["stats"].get(k):
                e["stats"][k] = w[k]
        if w["source"] and not e["source"]:
            e["source"] = w["source"]
        if w["weight"] and not e["weight"]:
            e["weight"] = w["weight"]
        if w["name"] != base:
            e["variants"].append((w["name"], w.get("attack", ""), w.get("note", "")))
    # 3) 鱼类（过滤掉怪物/箱子等非鱼类条目）
    monster_names = {m["name"] for m in _monsters}
    for f in _fish:
        n = f["name"]
        if n in monster_names or n in ("空钓", "箱子") or re.search(r"(水蟒|食人鱼|鳄鱼|鲨鱼|吸血鬼鱼)", n):
            continue
        e = ensure(n, "鱼类")
        e["fish"] = f
        if f["weight"] and not e["weight"]:
            e["weight"] = f["weight"]
        if f["price"] and not e["price"]:
            e["price"] = f["price"]
    # 4) 配方反向索引
    for rc in _recipes:
        out_raw = rc["name"]
        m = re.match(r"^(.+?)(?:x|\*|×)(\d+)$", out_raw)
        out_name, out_cnt = (m.group(1), m.group(2)) if m else (out_raw, "1")
        out_name = out_name.strip()
        e = ensure(out_name)
        if e["recipes_out"] is None:
            e["recipes_out"] = dict(rc, out_name=out_name, out_count=out_cnt)
        for part in re.split(r"[、,，]", rc["materials"]):
            pm = re.match(r"^([^\dx×*]+)(?:x|\*|×)?(\d+)?$", part.strip())
            if not pm:
                continue
            mat = pm.group(1).strip()
            cnt = pm.group(2) or "1"
            if not mat or len(mat) > 12:
                continue
            me = ensure(mat)
            me["recipes_in"].append((out_name, cnt, rc["section"]))
    # 5) 掉落 / 产地
    for monster, drops in _monster_drops.items():
        for d in drops:
            ensure(d)["drops"].append(monster)
    for item, locs in _item_sources.items():
        e = ensure(item)
        for mp, desc in locs[:6]:
            if (mp, desc) not in e["locations"]:
                e["locations"].append((mp, desc))
    # 6) 交易价格
    for item, price in _trade.items():
        if item in reg:
            reg[item]["trade"] = price
    # 7) 地图产地（按地图正文出现匹配）
    for mp in _maps:
        body = mp["body"]
        for name, e in reg.items():
            if len(name) >= 2 and name in body and mp["name"] != name:
                tag = (mp["name"], "地图资源/怪物")
                if tag not in e["locations"] and len(e["locations"]) < 10:
                    e["locations"].append(tag)
    # 过滤掉解析噪声条目（如「概率掉落兽筋」之类的短语）
    JUNK = re.compile(r"(掉落|概率|应该|发现|大概|据说|似乎|不掉)")
    return {k: v for k, v in reg.items() if not JUNK.search(k)}


# ============================ 生成：物品 ============================

SUBCAT_DIR = {
    "材料": "材料", "食物": "食物", "药品": "药品", "近战武器": "近战武器",
    "远程武器": "远程武器", "投掷武器": "投掷武器", "防具": "防具", "工具": "工具",
    "鱼类": "鱼类", "特殊道具": "特殊道具", "活动物品": "活动物品",
}
WEAPON_STAT_LABELS = [
    ("attack", "攻击"), ("durability", "耐久"), ("speed", "攻速"),
    ("range", "攻击距离/频率"), ("crit", "暴击"), ("buff", "增益（buff）"),
]
SUBCAT_DESC = {
    "材料": "建造与制造所需的基础资源，主要来自地图采集与怪物掉落。",
    "食物": "恢复饥饿度与状态的食材与料理，部分附带增益效果。",
    "药品": "恢复外伤、内伤、失眠等状态的药品。",
    "近战武器": "近距离作战武器与采集斧类，攻击距离通常为 1～3。",
    "远程武器": "弓、弩、枪类远程武器及弹药，攻击距离通常为 6～10。",
    "投掷武器": "开场投掷使用的炸药与飞刀类武器，基础命中 100%。",
    "防具": "提供防御与保暖效果的装备。",
    "工具": "探索、照明与辅助类道具。",
    "鱼类": "钓鱼系统获得的鱼类，食用可恢复状态或获得增益。",
    "特殊道具": "任务、剧情与系统类特殊物品。",
    "活动物品": "各节日活动期间限时获取的物品。",
}


def gen_items(reg):
    print("== 生成：物品（叶子 + 分类枢纽）==")
    by_sub = defaultdict(list)
    for e in reg.values():
        if e["subcat"] in SUBCAT_DIR:
            by_sub[e["subcat"]].append(e)

    # 物品总览
    entries = []
    for sub, dirname in SUBCAT_DIR.items():
        count = len(by_sub.get(sub, []))
        entries.append((f"{sub}（{count}）", SUBCAT_DESC[sub], f"{sub}/{sub}一览.md"))
    write_page(wpath(D_ITEM, "物品总览.md"),
               fm("物品总览", "物品", "枢纽", ["物品", "目录"]) +
               "# 物品总览\n\n> 《荒野日记：孤岛》全部物品的分类目录。本页仅作导航，具体数据见各条目页。\n\n" +
               "## 物品分类\n\n" + cards(entries) +
               "\n## 按获取途径浏览\n\n"
               "- 采集与资源点：[地图总览](../05-地图/地图总览.md) 中查看各区域循环资源点\n"
               "- 怪物掉落：见 [生物总览](../04-生物/生物总览.md) 各生物条目页\n"
               "- 合成制造：[建筑与制造](../02-核心机制/建筑与制造.md) 与各物品条目页的「用途」小节\n"
               "- 商人与活动：见 [NPC 一览](../01-游戏概览/NPC/NPC一览.md) 与 [账号资源系统](../07-收集/账号资源系统.md)\n")

    # 各子分类
    for sub, dirname in SUBCAT_DIR.items():
        items = sorted(by_sub.get(sub, []), key=lambda x: -len([1 for _ in x["recipes_in"]]))
        hub_rel = wpath(D_ITEM, dirname, f"{sub}一览.md")
        leaf_dir = wpath(D_ITEM, dirname)
        entries = []
        for e in items:
            desc = e["effect"] or e["source"] or (e["fish"]["prob"] + " 概率" if e["fish"] and e["fish"]["prob"] else "")
            entries.append((e["name"], one_liner(desc, 40), f"{e['name']}.md"))
        write_page(hub_rel,
                   fm(f"{sub}一览", f"物品 · {sub}", "枢纽", ["物品", sub, "目录"]) +
                   f"# {sub}一览\n\n> {SUBCAT_DESC[sub]}\n\n"
                   f"本分类共收录 **{len(items)}** 个条目，点击卡片进入条目页。\n\n" +
                   "## 全部条目\n\n" + (cards(entries) if entries else "（暂无条目）\n"))
        for e in items:
            gen_item_leaf(e, sub, dirname, hub_rel, reg)


def gen_item_leaf(e, sub, dirname, hub_rel, reg):
    """生成单个物品条目页。"""
    leaf_rel = wpath(D_ITEM, dirname, f"{e['name']}.md")
    out = [fm(e["name"], f"物品 · {sub}", "条目", ["物品", sub]), f"# {e['name']}\n\n"]

    # ---- 信息框 ----
    ib = [("类型", sub)]
    if e["weight"]:
        ib.append(("重量", e["weight"]))
    if e["price"]:
        ib.append(("价格", e["price"]))
    if e["trade"]:
        ib.append(("野蛮人交易价", e["trade"]))
    if e["fish"]:
        if e["fish"]["prob"]:
            ib.append(("获取概率", e["fish"]["prob"]))
        if e["fish"]["bait"]:
            ib.append(("鱼饵", e["fish"]["bait"]))
    for key, label in WEAPON_STAT_LABELS:
        if e["stats"].get(key):
            ib.append((label, e["stats"][key]))
    if e["recipes_out"]:
        ib.append(("制作台", e["recipes_out"]["section"]))
    if e["source"]:
        ib.append(("获取途径", e["source"]))
    out.append(infobox(ib))

    # ---- 简介 ----
    intro = e["effect"] or ""
    if e["is_weapon"]:
        intro = intro or f"{e['name']} 是《荒野日记：孤岛》中的一件{sub}。"
    elif e["fish"]:
        intro = intro or f"{e['name']} 是钓鱼系统可获得的鱼类之一。"
    else:
        intro = intro or f"{e['name']} 是《荒野日记：孤岛》中的{sub}。"
    out.append(intro + "\n\n")

    # ---- 获取方式 ----
    rows = []
    if e["source"]:
        rows.append(("图鉴记载", e["source"]))
    for mp, desc in e["locations"]:
        link = map_link_from(leaf_rel, mp)
        rows.append(("采集/出现", (f"[{mp}]({link})：" if link else f"{mp}：") + desc))
    if e["drops"]:
        drops = "、".join(link_monster(leaf_rel, m) for m in e["drops"][:8])
        rows.append(("怪物掉落", drops))
    if e["recipes_out"]:
        rc = e["recipes_out"]
        cond = f"（{rc['condition']}）" if rc["condition"] else ""
        rows.append(("合成制造", f"于 {rc['section']} 制作{cond}：{rc['materials']}"))
    if e["trade"]:
        npc_link = rel_link(leaf_rel, wpath(D_GUIDE, "NPC", "野蛮人.md"))
        rows.append(("商人交易", f"可在 [野蛮人]({npc_link}) 处交易（价格 {e['trade']}）"))
    out.append("## 获取方式\n\n")
    if rows:
        out.append("| 途径 | 详情 |\n|---|---|\n")
        out.append("".join(f"| {k} | {v} |\n" for k, v in rows))
    else:
        out.append("> 资料未收录具体获取方式，可通过 [物品总览](../物品总览.md) 检索同类物品。\n")
    out.append("\n")

    # ---- 数值数据 ----
    out.append("## 数值数据\n\n")
    if e["fish"]:
        f = e["fish"]
        out.append("| 项目 | 数值 |\n|---|---|\n")
        for k, v in [("重量", e["weight"]), ("价格", e["price"]), ("获取概率", f["prob"]),
                     ("温度", f["temp"]), ("时间（点）", f["time"]), ("季节", f["season"]),
                     ("鱼饵", f["bait"]), ("天数/其他", f["days"]), ("饥饿度", f["hunger"]),
                     ("状态恢复", f["recover"]), ("buff／道具", f["buff"]), ("持续时间", f["duration"])]:
            if v:
                out.append(f"| {k} | {v} |\n")
    elif e["is_weapon"]:
        out.append("| 项目 | 数值 |\n|---|---|\n")
        for key, label in WEAPON_STAT_LABELS + [("craft", "制作消耗"), ("note", "特效/备注")]:
            if e["stats"].get(key):
                out.append(f"| {label} | {e['stats'][key]} |\n")
        if e["weight"]:
            out.append(f"| 重量 | {e['weight']} |\n")
        if e["price"]:
            out.append(f"| 价格 | {e['price']} |\n")
        if e["variants"]:
            out.append("\n**变体**\n\n| 变体 | 攻击 | 备注 |\n|---|---|---|\n")
            for v, atk, note in e["variants"]:
                out.append(f"| {v} | {atk or '—'} | {note or '—'} |\n")
    else:
        out.append("| 项目 | 数值 |\n|---|---|\n")
        for k, v in [("重量", e["weight"]), ("价格", e["price"])]:
            if v:
                out.append(f"| {k} | {v} |\n")
        if not e["weight"] and not e["price"]:
            out.append("| — | 资料未收录 |\n")
    out.append("\n")

    # ---- 用途 ----
    out.append("## 用途\n\n")
    used = False
    if e["recipes_in"]:
        seen = set()
        out.append("**作为合成材料：**\n\n| 产物 | 需要数量 | 制作台 |\n|---|---|---|\n")
        for out_name, cnt, sec in e["recipes_in"]:
            if out_name in seen:
                continue
            seen.add(out_name)
            link = item_link(leaf_rel, out_name, reg)
            out.append(f"| {link} | {cnt} | {sec} |\n")
        used = True
    if e["is_weapon"]:
        out.append("\n**战斗使用：**作为%s使用，具体命中与伤害机制参见 [战斗系统](%s)。\n"
                   % (sub, rel_link(leaf_rel, wpath(D_CORE, "战斗系统.md"))))
        used = True
    if e["fish"]:
        out.append("\n**食用与增益：**钓获后可直接食用恢复状态，或用于成就收集；详见 [钓鱼系统](%s)。\n"
                   % rel_link(leaf_rel, wpath(D_CORE, "钓鱼系统.md")))
        used = True
    if e["effect"] and not used:
        out.append(e["effect"] + "\n")
    if not used and not e["effect"]:
        out.append("> 资料未收录该物品的具体用途。\n")
    out.append("\n")

    # ---- 参见 ----
    links = [("上级分类", rel_link(leaf_rel, hub_rel))]
    if e["drops"]:
        first = e["drops"][0]
        links.append((f"掉落来源：{first}", rel_link(leaf_rel, wpath(D_MON, monster_dir(first), f"{first}.md"))))
    for mp, _d in e["locations"][:3]:
        l = map_link_from(leaf_rel, mp)
        if l:
            links.append((f"相关地图：{mp}", l))
    links.append(("物品总览", rel_link(leaf_rel, wpath(D_ITEM, "物品总览.md"))))
    out.append(see_also(links))
    write_page(leaf_rel, "".join(out))


def item_link(from_rel, name, reg):
    """物品名 -> 相对链接（若不在注册表则返回纯文本）。"""
    e = reg.get(name)
    if not e or e["subcat"] not in SUBCAT_DIR:
        return name
    return f"[{name}]({rel_link(from_rel, wpath(D_ITEM, SUBCAT_DIR[e['subcat']], f'{name}.md'))})"


def monster_dir(name):
    for m in _monsters:
        if m["name"] == name:
            return MONSTER_SUBCAT_DIR.get(m.get("source_section", ""), "其他生物")
    return "其他生物"


def link_monster(from_rel, name):
    return f"[{name}]({rel_link(from_rel, wpath(D_MON, monster_dir(name), f'{name}.md'))})"


def map_link_from(from_rel, map_name):
    """地图名 -> 相对链接（精确匹配生成的地图页）。"""
    for mp in _maps:
        if mp["name"] == map_name:
            return rel_link(from_rel, wpath(D_MAP, MAP_GROUP_DIR.get(mp.get("group", ""), "特殊地图"), f"{map_name}.md"))
    for extra in ("圣果树", "海盗营地", "古代遗迹", "至高之地"):
        if map_name == extra:
            return rel_link(from_rel, wpath(D_MAP, "专属地图", f"{extra}.md"))
    return None


MAP_GROUP_DIR = {
    "二、大地图各关卡": "大地图",
    "三、破风口": "破风口",
    "四、沉船与沉船一侧（桅船）": "沉船",
    "五、专属地图": "专属地图",
    "八、特殊地图：崖洞与神秘遗迹": "特殊地图",
}


# ============================ 生成：生物 ============================

def gen_monsters():
    print("== 生成：生物（叶子 + 分类枢纽）==")
    # 合并：普通表 + 挑战表 + 成长表 + 掉落 + 特殊说明
    merged = OrderedDict()
    for m in _monsters:
        name = m["name"]
        if name not in merged:
            merged[name] = {
                "name": name, "subcat": m["category"], "normal_hp": "", "location": "",
                "ch": {}, "growth": _growth.get(name, {}), "drops": _monster_drops.get(name, []),
                "notes": [], "challenge_only": False,
            }
        e = merged[name]
        if m["challenge"]:
            e["ch"]["hp"] = m["hp"]
            e["ch"]["attack"] = m["attack"]
            e["ch"]["hit"] = m["hit"]
            e["ch"]["dodge"] = m["dodge"]
            e["ch"]["speed"] = m["speed"]
            e["ch"]["special"] = m["special"]
            if not e["subcat"] or e["subcat"] == "其他生物":
                e["subcat"] = m["category"]
        else:
            e["normal_hp"] = m["hp"]
            e["location"] = m["location"] or e["location"]
            if m["category"]:
                e["subcat"] = m["category"]
    # 仅存在于挑战数据表的生物
    for name, e in merged.items():
        if e["normal_hp"] == "" and e["ch"]:
            e["challenge_only"] = True
    # 过滤解析噪声（伪怪物名）
    JUNK = re.compile(r"(掉落|概率|应该|发现|大概|据说|似乎|不掉)")
    for junk in [k for k in merged if JUNK.search(k)]:
        del merged[junk]
    # 特殊说明匹配
    for note in _notes:
        for name, e in merged.items():
            if name in note["title"] or name in note["body"][:300]:
                e["notes"].append(note["body"])
                break

    by_sub = defaultdict(list)
    for e in merged.values():
        by_sub[e["subcat"]].append(e)

    # 总览页
    entries = []
    for sub in MONSTER_SUBCAT_DIR.values():
        items = by_sub.get(sub, [])
        if items:
            entries.append((f"{sub}（{len(items)}）", f"共 {len(items)} 种生物", f"{sub}/{sub}一览.md"))
    write_page(wpath(D_MON, "生物总览.md"),
               fm("生物总览", "生物", "枢纽", ["生物", "目录"]) +
               "# 生物总览\n\n> 《荒野日记：孤岛》全部生物的分类目录；" 
               "普通模式与挑战模式数据均在各自条目页标注。\n\n## 生物分类\n\n" + cards(entries) +
               "\n## 说明\n\n"
               "- 怪物属性随生存天数与挑战难度成长，完整公式见 [挑战模式](../02-核心机制/挑战模式.md)\n"
               "- 战斗命中、闪避等机制见 [战斗系统](../02-核心机制/战斗系统.md)\n")

    for sub in sorted(set(MONSTER_SUBCAT_DIR.values())):
        items = sorted(by_sub.get(sub, []), key=lambda x: x["name"])
        hub_rel = wpath(D_MON, sub, f"{sub}一览.md")
        entries = []
        for e in items:
            desc = ("挑战模式专属" if e["challenge_only"] else (e["location"] or "出现于多处地图"))
            entries.append((e["name"], one_liner(desc, 36), f"{e['name']}.md"))
        write_page(hub_rel,
                   fm(f"{sub}一览", f"生物 · {sub}", "枢纽", ["生物", sub]) +
                   f"# {sub}一览\n\n> 本分类共 {len(items)} 种生物。\n\n" + cards(entries))
        for e in items:
            gen_monster_leaf(e, sub, hub_rel)


def gen_monster_leaf(e, sub, hub_rel):
    leaf_rel = wpath(D_MON, sub, f"{e['name']}.md")
    out = [fm(e["name"], f"生物 · {sub}", "条目", ["生物", sub]), f"# {e['name']}\n\n"]
    ib = [("类别", sub)]
    if e["challenge_only"]:
        ib.append(("登场", "挑战模式专属"))
    if e["normal_hp"]:
        ib.append(("生命值（普通）", e["normal_hp"]))
    if e["ch"].get("hp"):
        ib.append(("生命值（挑战基础）", e["ch"]["hp"]))
    if e["ch"].get("attack"):
        ib.append(("攻击（挑战基础）", e["ch"]["attack"]))
    if e["ch"].get("special"):
        ib.append(("特性", e["ch"]["special"]))
    if e["location"]:
        ib.append(("出现地点", e["location"]))
    out.append(infobox(ib))
    out.append(f"{e['name']} 是《荒野日记：孤岛》中的一种生物"
               + ("，仅在挑战模式登场。" if e["challenge_only"] else "。") + "\n\n")

    out.append("## 属性数据\n\n")
    if e["normal_hp"]:
        out.append(f"- **生命值（普通模式）**：{e['normal_hp']}\n")
    if e["ch"]:
        out.append("\n**挑战模式基础属性**\n\n| 项目 | 数值 |\n|---|---|\n")
        for k, label in [("hp", "血量"), ("attack", "攻击"), ("hit", "命中"),
                         ("dodge", "闪避"), ("speed", "移速"), ("special", "特性")]:
            if e["ch"].get(k):
                out.append(f"| {label} | {e['ch'][k]} |\n")
        out.append("\n> 实际数值 = 基础数值 × 天数系数 × 沉船系数 × 难度系数，详见 [挑战模式](%s)。\n"
                   % rel_link(leaf_rel, wpath(D_CORE, "挑战模式.md")))
    if e["growth"]:
        out.append("\n**随生存天数成长**\n\n| 天数区间 | 攻击/血量 |\n|---|---|\n")
        for k, v in e["growth"].items():
            if v and v != "—":
                out.append(f"| {k} | {v} |\n")
    out.append("\n")

    out.append("## 出现地图\n\n")
    locs = [x.strip() for x in re.split(r"[、,，/]", e["location"]) if x.strip()]
    listed = False
    for loc in locs:
        l = map_link_from(leaf_rel, loc)
        if l:
            out.append(f"- [{loc}]({l})\n")
            listed = True
    if not listed:
        out.append("- 详见 [地图总览](%s)\n" % rel_link(leaf_rel, wpath(D_MAP, "地图总览.md")))
    out.append("\n")

    out.append("## 掉落物品\n\n")
    if e["drops"]:
        out.append("、".join(e["drops"]) + "\n\n")
    out.append("> " + (G.DROP_NOTES.get(e["name"], G.DROP_NOTES["默认"])) + "\n\n")

    if e["notes"]:
        notes_md = "\n\n".join(embed(note, SRC_MON, leaf_rel) for note in e["notes"])
        out.append("## 战斗提示\n\n" + notes_md + "\n\n")

    out.append(see_also([
        ("上级分类", rel_link(leaf_rel, hub_rel)),
        ("生物总览", rel_link(leaf_rel, wpath(D_MON, "生物总览.md"))),
        ("战斗系统", rel_link(leaf_rel, wpath(D_CORE, "战斗系统.md"))),
    ]))
    write_page(leaf_rel, "".join(out))


# ============================ 生成：地图 ============================

def gen_maps():
    print("== 生成：地图（叶子 + 分类枢纽）==")
    by_group = defaultdict(list)
    for mp in _maps:
        by_group[MAP_GROUP_DIR.get(mp.get("group", ""), "特殊地图")].append(mp)

    # 专属地图补充（无独立小节，来自逃离方式资料）
    if not by_group.get("专属地图"):
        for name, role in [("圣果树", "罗兰"), ("海盗营地", "朱莉 / 老贝"),
                           ("古代遗迹", "小哥"), ("至高之地", "基德")]:
            by_group["专属地图"].append({"name": name, "waves": "", "body":
                f"专属地图：{role} 的专属逃离地点。具体打法与材料需求详见「逃离方式一览」中对应角色的条目页。",
                "group": "五、专属地图"})

    # 总览页（含机制小节）
    hub = [fm("地图总览", "地图", "枢纽", ["地图", "目录"]),
           "# 地图总览\n\n> 《荒野日记：孤岛》全部地图与区域说明。\n\n"]
    hub.append("## 区域划分\n\n")
    entries = []
    for g, d in [("大地图", "主线推进区域，从乱石林到黑暗囚室"),
                 ("破风口", "溶洞后解锁的地下研究区"),
                 ("沉船", "沉船与沉船一侧（桅船）"),
                 ("专属地图", "各角色的专属逃离地点"),
                 ("特殊地图", "崖洞与神秘遗迹（存档点）")]:
        items = by_group.get(g, [])
        entries.append((f"{g}（{len(items)}）", d, f"{slug_dir(g)}/{g}一览.md"))
    hub.append(cards(entries) + "\n")
    for key in ["地图总览", "循环资源点机制", "隐藏关卡机制", "挑战模式地图差异", "关卡威胁度标注说明"]:
        body = embed(_map_meta.get(key, ""), SRC_MAP, wpath(D_MAP, "地图总览.md"))
        if body:
            title = key if key != "地图总览" else "解锁顺序与规则"
            hub.append(f"## {title}\n\n{body}\n\n")
    write_page(wpath(D_MAP, "地图总览.md"), "".join(hub))

    for group, items in by_group.items():
        dirname = slug_dir(group)
        hub_rel = wpath(D_MAP, dirname, f"{group}一览.md")
        entries = [(mp["name"], (f"普通/挑战 共 {mp['waves']} 波" if mp["waves"] else "专属地点"),
                    f"{mp['name']}.md") for mp in items]
        intro = f"# {group}一览\n\n> 本区域共 {len(items)} 张地图。\n\n"
        extra = embed(_map_meta.get(group, ""), SRC_MAP, hub_rel) if group == "专属地图" else ""
        write_page(hub_rel,
                   fm(f"{group}一览", f"地图 · {group}", "枢纽", ["地图", group]) +
                   intro + (extra + "\n\n" if extra else "") + cards(entries))
        for mp in items:
            gen_map_leaf(mp, group, dirname, hub_rel)


def slug_dir(name):
    return name


def gen_map_leaf(mp, group, dirname, hub_rel):
    leaf_rel = wpath(D_MAP, dirname, f"{mp['name']}.md")
    body = embed(mp["body"], SRC_MAP, leaf_rel)
    # 提取元数据
    meta_cycle = re.findall(r"循环资源点[：:]\s*([^\n]+)", body)
    meta_hidden = re.findall(r"隐藏关卡[：:]\s*([^\n]+)", body)
    meta_trap = re.findall(r"陷阱[：:]\s*([^\n]+)", body)
    out = [fm(mp["name"], f"地图 · {group}", "条目", ["地图", group]), f"# {mp['name']}\n\n"]
    ib = [("所属区域", group)]
    if mp["waves"]:
        ib.append(("波数（普通/挑战）", mp["waves"]))
    if meta_cycle:
        ib.append(("循环资源点", meta_cycle[0][:60]))
    if meta_hidden:
        ib.append(("隐藏关卡", meta_hidden[0][:60]))
    if meta_trap:
        ib.append(("陷阱", meta_trap[0][:60]))
    out.append(infobox(ib))
    out.append(body + "\n\n")
    out.append(see_also([
        ("上级分类", rel_link(leaf_rel, hub_rel)),
        ("地图总览", rel_link(leaf_rel, wpath(D_MAP, "地图总览.md"))),
        ("战斗系统", rel_link(leaf_rel, wpath(D_CORE, "战斗系统.md"))),
        ("逃离方式一览", rel_link(leaf_rel, wpath(D_GUIDE, "逃离方式", "逃离方式一览.md"))),
    ]))
    write_page(leaf_rel, "".join(out))


# ============================ 生成：天赋 / 主题 / 小游戏 ============================

def gen_talents():
    print("== 生成：天赋 ==")
    by_cat = defaultdict(list)
    for t in _talents:
        by_cat[t["cat"]].append(t)
    hub = [fm("天赋一览", "核心机制 · 天赋", "枢纽", ["天赋", "目录"]),
           "# 天赋一览\n\n> 天赋分战斗、生存、探索三类，每局可在开局 / 第 20 天 / 第 40 天各装备 1 个。\n\n",
           "## 天赋分类\n\n"]
    entries = [(f"{cat}（{len(by_cat.get(cat, []))}）", f"{cat}条目一览", f"{cat}.md")
               for cat in ("战斗天赋", "生存天赋", "探索天赋")]
    hub.append(cards(entries) + "\n")
    hub.append("## 升星规则\n\n- 零星 → 一星：20 天赋原石\n- 一星 → 二星：40 原石 + 5 结晶\n"
               "- 二星 → 三星：100 原石 + 20 结晶\n- 天赋石来自挑战任务（挑 10+ 产出结晶）\n\n")
    hub.append(see_also([("天赋机制全文", rel_link(wpath(D_CORE, "天赋", "天赋一览.md"), wpath(D_CORE, "挑战模式.md")))]))
    write_page(wpath(D_CORE, "天赋", "天赋一览.md"), "".join(hub))

    for cat in ("战斗天赋", "生存天赋", "探索天赋"):
        items = by_cat.get(cat, [])
        hub_rel = wpath(D_CORE, "天赋", f"{cat}.md")
        entries = [(t["name"], one_liner(t["effect"], 44), f"{t['name']}.md") for t in items]
        write_page(hub_rel,
                   fm(cat, f"核心机制 · 天赋", "枢纽", ["天赋", cat]) +
                   f"# {cat}\n\n> 共 {len(items)} 项。\n\n" + cards(entries))
        for t in items:
            gen_talent_leaf(t, cat, hub_rel)


def gen_talent_leaf(t, cat, hub_rel):
    leaf_rel = wpath(D_CORE, "天赋", f"{t['name']}.md")
    stars = [s.strip() for s in re.split(r"→", t["effect"])]
    out = [fm(t["name"], f"天赋 · {cat}", "条目", ["天赋", cat]), f"# {t['name']}\n\n",
           infobox([("类别", cat), ("星级", "零星 / 一星 / 二星 / 三星")])]
    out.append("## 效果数据\n\n| 星级 | 效果 |\n|---|---|\n")
    names = ["零星", "一星", "二星", "三星"]
    for i, s in enumerate(stars[:4]):
        out.append(f"| {names[i]} | {s} |\n")
    out.append("\n## 获取与升星\n\n- 获取：商店购买 / 神秘人抽奖 / 限时天赋包（见 [天赋一览](天赋一览.md)）\n"
               "- 升星消耗见 [天赋一览](天赋一览.md) 的升星规则\n\n")
    out.append(see_also([("天赋一览", rel_link(leaf_rel, wpath(D_CORE, "天赋", "天赋一览.md"))),
                         ("天赋机制（挑战模式页）", rel_link(leaf_rel, wpath(D_CORE, "挑战模式.md")))]))
    write_page(leaf_rel, "".join(out))


def gen_themes():
    print("== 生成：挑战主题 ==")
    hub_rel = wpath(D_CORE, "挑战主题", "挑战主题一览.md")
    out = [fm("挑战主题一览", "核心机制 · 挑战", "枢纽", ["挑战主题", "目录"]),
           "# 挑战主题一览\n\n> 挑战主题每晚 0 点重新随机，数量随难度增加。\n\n"]
    if _pools:
        out.append("## 主题池（按难度）\n\n| 难度 | 主题池构成 |\n|---|---|\n")
        for p in _pools:
            out.append(f"| {p['level']} | {p['pool']} |\n")
        out.append("\n")
    out.append("## 全部主题\n\n")
    out.append(cards([(t["name"], one_liner(t["effect"], 44), f"{t['name']}.md") for t in _themes]))
    write_page(hub_rel, "".join(out))
    for t in _themes:
        leaf_rel = wpath(D_CORE, "挑战主题", f"{t['name']}.md")
        body = [fm(t["name"], "挑战主题", "条目", ["挑战主题"]), f"# {t['name']}\n\n",
                infobox([("类型", "挑战主题")])]
        body.append("## 效果\n\n" + (t["effect"] or "资料未收录") + "\n\n")
        body.append("## 应对参考\n\n" + (t["tip"] or "资料未收录") + "\n\n")
        body.append(see_also([("挑战主题一览", rel_link(leaf_rel, hub_rel)),
                              ("挑战模式", rel_link(leaf_rel, wpath(D_CORE, "挑战模式.md")))]))
        write_page(leaf_rel, "".join(body))


def gen_minigames():
    print("== 生成：小游戏 ==")
    hub_rel = wpath(D_CORE, "小游戏", "小游戏一览.md")
    write_page(hub_rel,
               fm("小游戏一览", "核心机制 · 小游戏", "枢纽", ["小游戏", "目录"]) +
               "# 小游戏一览\n\n> 推图与剧情节点中的小游戏玩法。\n\n" +
               cards([(g["name"], one_liner(g["body"], 44), f"{g['name']}.md") for g in _minigames]))
    for g in _minigames:
        leaf_rel = wpath(D_CORE, "小游戏", f"{g['name']}.md")
        body = [fm(g["name"], "小游戏", "条目", ["小游戏"]), f"# {g['name']}\n\n", embed(g["body"], SRC_MG, leaf_rel) + "\n\n",
                see_also([("小游戏一览", rel_link(leaf_rel, hub_rel)),
                          ("新手指南", rel_link(leaf_rel, wpath(D_STRAT, "新手指南.md")))])]
        write_page(leaf_rel, "".join(body))


# ============================ 生成：建筑 ============================

def gen_buildings():
    print("== 生成：建筑 ==")
    md = read(os.path.join(WIKI, "03-数据资料", "建筑与制造.md"))
    tables = parse_tables(md)
    bt = find_table(tables, ["建筑", "建造材料"])
    buildings = []
    if bt:
        for r in bt["rows"]:
            row = dict(zip(bt["header"], r))
            name = clean(row.get("建筑", ""))
            if not name or name == "建筑":
                continue
            buildings.append({
                "name": name,
                "materials": clean(row.get("建造材料", "")),
                "unlock": clean(row.get("解锁条件", "")),
                "use": clean(row.get("作用", "")),
                "level": clean(row.get("等级关系", "")),
            })
    hub_rel = wpath(D_CORE, "建筑", "建筑一览.md")
    write_page(hub_rel,
               fm("建筑一览", "核心机制 · 建筑", "枢纽", ["建筑", "目录"]) +
               "# 建筑一览\n\n> 营地建筑决定可制作范围与状态恢复能力；部分建筑分支只能二选一。\n\n" +
               cards([(b["name"], one_liner(b["use"] or b["unlock"], 40), f"{b['name']}.md") for b in buildings]) +
               "\n完整配方表见 [建筑与制造](../建筑与制造.md)。\n")
    recipe_station = defaultdict(list)
    for rc in _recipes:
        recipe_station[rc["section"]].append(rc)
    for b in buildings:
        leaf_rel = wpath(D_CORE, "建筑", f"{b['name']}.md")
        out = [fm(b["name"], "建筑", "条目", ["建筑"]), f"# {b['name']}\n\n",
               infobox([("建造材料", b["materials"] or "资料未收录"),
                        ("解锁条件", b["unlock"] or "—"),
                        ("主要作用", b["use"] or "—"),
                        ("等级关系", b["level"] or "—")])]
        out.append("## 建造材料\n\n" + (b["materials"] or "资料未收录") + "\n\n")
        made = []
        for station, rcs in recipe_station.items():
            if b["name"] in station or station in b["name"]:
                made = rcs
                break
        if made:
            out.append("## 可制作产物\n\n| 产物 | 条件 | 素材 | 时间 |\n|---|---|---|---|\n")
            for rc in made:
                out.append(f"| {rc['name']} | {rc['condition'] or '—'} | {rc['materials']} | {rc['time']} |\n")
            out.append("\n")
        out.append(see_also([("建筑一览", rel_link(leaf_rel, hub_rel)),
                             ("建筑与制造（配方总表）", rel_link(leaf_rel, wpath(D_CORE, "建筑与制造.md")))]))
        write_page(leaf_rel, "".join(out))


# ============================ 生成：角色 / 奇遇 / NPC / 逃离 ============================

def gen_characters():
    print("== 生成：角色与奇遇 ==")
    hub_rel = wpath(D_GUIDE, "角色", "角色一览.md")
    write_page(hub_rel,
               fm("角色一览", "游戏概览 · 角色", "枢纽", ["角色", "目录"]) +
               "# 角色一览\n\n> 五位基础角色与各自的奇遇（付费强化皮肤）。\n\n" +
               cards([(c["name"], c["role"], f"{c['name']}.md") for c in _characters]) +
               "\n奇遇总目录见 [奇遇一览](../奇遇/奇遇一览.md)。\n")
    adv_by_role = defaultdict(list)
    for a in _adventures:
        adv_by_role[a["role"]].append(a)
    for c in _characters:
        leaf_rel = wpath(D_GUIDE, "角色", f"{c['name']}.md")
        out = [fm(c["name"], "角色", "条目", ["角色", c["role"]]), f"# {c['name']}\n\n",
               embed(c["body"], SRC_CHARS, leaf_rel) + "\n\n"]
        advs = adv_by_role.get(c["name"], [])
        if advs:
            out.append("## 奇遇\n\n" + cards([(a["name"], "点击查看技能数据", f"../奇遇/{a['name']}.md") for a in advs]))
        out.append(see_also([("角色一览", rel_link(leaf_rel, hub_rel)),
                             ("奇遇一览", rel_link(leaf_rel, wpath(D_GUIDE, "奇遇", "奇遇一览.md")))]))
        write_page(leaf_rel, "".join(out))

    hub_rel = wpath(D_GUIDE, "奇遇", "奇遇一览.md")
    out = [fm("奇遇一览", "游戏概览 · 奇遇", "枢纽", ["奇遇", "目录"]),
           "# 奇遇一览\n\n> 奇遇是在基础角色上进一步强化的「皮肤」角色，拥有独立技能与专属剧情。\n\n"]
    by_role = OrderedDict((c["name"], []) for c in _characters)
    for a in _adventures:
        by_role.setdefault(a["role"], []).append(a)
    for role, advs in by_role.items():
        if not advs:
            continue
        out.append(f"## {role}的奇遇\n\n")
        out.append(cards([(a["name"], one_liner(a["body"].split("\n")[0], 40), f"{a['name']}.md") for a in advs]))
        out.append("\n")
    write_page(hub_rel, "".join(out))
    for a in _adventures:
        leaf_rel = wpath(D_GUIDE, "奇遇", f"{a['name']}.md")
        body = [fm(a["name"], f"奇遇 · {a['role']}", "条目", ["奇遇", a["role"]]),
                f"# {a['name']}\n\n", infobox([("归属角色", a["role"]), ("类型", "奇遇")]),
                embed(a["body"], SRC_ADV, leaf_rel) + "\n\n",
                see_also([("奇遇一览", rel_link(leaf_rel, hub_rel)),
                          (f"角色：{a['role']}", rel_link(leaf_rel, wpath(D_GUIDE, "角色", f"{a['role']}.md")))])]
        write_page(leaf_rel, "".join(body))


def gen_npcs():
    print("== 生成：NPC ==")
    hub_rel = wpath(D_GUIDE, "NPC", "NPC一览.md")
    write_page(hub_rel,
               fm("NPC一览", "游戏概览 · NPC", "枢纽", ["NPC", "目录"]) +
               "# NPC一览\n\n> 荒岛上的非玩家角色：宠物、坐骑、商人与账号级玩法。\n\n" +
               cards([(n["name"], n["subcat"], f"{n['name']}.md") for n in _npcs]))
    for n in _npcs:
        leaf_rel = wpath(D_GUIDE, "NPC", f"{n['name']}.md")
        body = [fm(n["name"], "NPC", "条目", ["NPC", n["subcat"]]), f"# {n['name']}\n\n",
                infobox([("类型", n["subcat"])]), embed(n["body"], SRC_NPC, leaf_rel) + "\n\n",
                see_also([("NPC一览", rel_link(leaf_rel, hub_rel)),
                          ("新手指南", rel_link(leaf_rel, wpath(D_STRAT, "新手指南.md")))])]
        write_page(leaf_rel, "".join(body))


def gen_escapes():
    print("== 生成：逃离方式 ==")
    hub_rel = wpath(D_GUIDE, "逃离方式", "逃离方式一览.md")
    out = [fm("逃离方式一览", "游戏概览 · 逃离", "枢纽", ["逃离方式", "目录"]),
           "# 逃离方式一览\n\n> 逃离荒岛是唯一的胜利方式，共 11 种途径。\n\n"]
    if _esc_overview:
        out.append("## 总览\n\n| 编号 | 方式 | 类型 | 关键前置 |\n|---|---|---|---|\n")
        for o in _esc_overview:
            leaf = f"{o['name']}.md" if any(e["name"] == o["name"] for e in _escapes) else None
            name = f"[{o['name']}]({leaf})" if leaf else o["name"]
            out.append(f"| {o['no']} | {name} | {o['type']} | {o['cond']} |\n")
        out.append("\n")
    out.append("## 分条目\n\n")
    out.append(cards([(e["name"], one_liner(e["body"], 42), f"{e['name']}.md") for e in _escapes]))
    write_page(hub_rel, "".join(out))
    for e in _escapes:
        leaf_rel = wpath(D_GUIDE, "逃离方式", f"{e['name']}.md")
        body = [fm(e["name"], "逃离方式", "条目", ["逃离方式"]), f"# {e['name']}\n\n",
                infobox([("类型", e["parent"] or "逃离方式")]), embed(e["body"], SRC_ESC, leaf_rel) + "\n\n",
                see_also([("逃离方式一览", rel_link(leaf_rel, hub_rel)),
                          ("挑战攻略", rel_link(leaf_rel, wpath(D_STRAT, "挑战攻略.md")))])]
        write_page(leaf_rel, "".join(body))


# ============================ 生成：首页 ============================

def gen_home(reg):
    print("== 生成：首页 ==")
    n_items = len([e for e in reg.values() if e["subcat"] in SUBCAT_DIR])
    n_mon = len({m["name"] for m in _monsters})   # 去重后的生物种类数
    n_maps = len(_maps) + 4
    n_chars = len(_characters)
    n_adv = len(_adventures)
    n_pages = len(generated_pages) + 1
    hero = ("```wiki-hero\n"
            "标题 :: 荒野日记：孤岛 Wiki\n"
            "副标题 :: 大航海时代的荒岛生存百科 —— 基于玩家社区资料系统化整理\n"
            f"统计 :: {n_pages} 个条目页 · {n_items} 件物品 · {n_mon} 种生物 · {n_maps} 张地图 · "
            f"{n_chars} 位角色 · {n_adv} 个奇遇\n"
            "```\n")
    content = [fm("首页", "首页", "首页", ["导航"]),
               "# 荒野日记：孤岛 Wiki\n\n", hero, "\n"]
    content.append("## 关于本 Wiki\n\n"
                   "《荒野日记：孤岛》是一款文字类荒岛生存游戏：玩家扮演因海难流落荒岛的角色，"
                   "在采集、建造、战斗与探索中生存下来，并最终寻找逃离荒岛的方法。\n\n"
                   "本 Wiki 以 **树状结构** 组织全部内容：每个物品、生物、地图、天赋等元素都有独立的条目页，"
                   "分类页仅用于罗列与导航。内容整理自玩家社区资料（见 [资料来源](08-附录/资料来源.md)），"
                   "非官方资料，数据请以游戏内实际为准。\n\n")
    content.append("## 快速导航\n\n")
    content.append(cards([
        ("物品图鉴", "材料 / 食物 / 药品 / 武器 / 防具 / 鱼类 / 活动道具", "03-物品/物品总览.md"),
        ("生物图鉴", "普通与挑战模式全部怪物属性与掉落", "04-生物/生物总览.md"),
        ("地图图鉴", "大地图 / 破风口 / 沉船 / 专属地图 / 特殊地图", "05-地图/地图总览.md"),
        ("角色与奇遇", "五位主角与全部奇遇技能数据", "01-游戏概览/角色/角色一览.md"),
        ("系统机制", "生存 / 战斗 / 天赋 / 科技 / 挑战主题", "02-核心机制/生存系统.md"),
        ("攻略指南", "新手指南 / 挑战攻略 / 进阶技巧", "06-攻略/新手指南.md"),
    ]))
    content.append("\n## 游戏内容\n\n")
    content.append(cards([
        ("材料", "建造与制造的基础资源", "03-物品/材料/材料一览.md"),
        ("食物", "恢复饥饿与状态", "03-物品/食物/食物一览.md"),
        ("药品", "外伤 / 内伤 / 失眠恢复", "03-物品/药品/药品一览.md"),
        ("近战武器", "竹枪 / 斧类 / 刀类", "03-物品/近战武器/近战武器一览.md"),
        ("远程武器", "弓 / 弩 / 枪与弹药", "03-物品/远程武器/远程武器一览.md"),
        ("投掷武器", "炸药 / 飞刀 / 麻痹针", "03-物品/投掷武器/投掷武器一览.md"),
        ("防具", "皮甲 / 藤甲 / 专属服饰", "03-物品/防具/防具一览.md"),
        ("工具", "火把 / 手电 / 罗盘等", "03-物品/工具/工具一览.md"),
        ("鱼类", "钓鱼系统全部鱼类", "03-物品/鱼类/鱼类一览.md"),
        ("特殊道具", "七色圆球 / 秘宝 / 任务物品", "03-物品/特殊道具/特殊道具一览.md"),
        ("活动物品", "各节日限时道具", "03-物品/活动物品/活动物品一览.md"),
        ("NPC", "白狼 / 骆驼 / 野蛮人 / 金雕", "01-游戏概览/NPC/NPC一览.md"),
    ]))
    content.append("\n## 系统机制\n\n")
    content.append(cards([
        ("生存系统", "六项状态与温度", "02-核心机制/生存系统.md"),
        ("战斗系统", "命中 / 伤害 / 状态机制", "02-核心机制/战斗系统.md"),
        ("天赋系统", "天赋一览与升星", "02-核心机制/天赋/天赋一览.md"),
        ("科技系统", "书页与科技升级", "02-核心机制/科技系统.md"),
        ("挑战模式", "难度与挑战主题", "02-核心机制/挑战模式.md"),
        ("挑战主题", "每晚随机的负面主题", "02-核心机制/挑战主题/挑战主题一览.md"),
        ("建筑", "营地建筑一览", "02-核心机制/建筑/建筑一览.md"),
        ("小游戏", "明暗盘 / 智斗 / 迷路", "02-核心机制/小游戏/小游戏一览.md"),
    ]))
    content.append("\n## 剧情与收集\n\n")
    content.append(cards([
        ("游戏简介", "官方信息与版本说明", "01-游戏概览/游戏简介.md"),
        ("背景故事", "世界观与角色剧情", "01-游戏概览/背景故事.md"),
        ("逃离方式", "11 种逃离途径", "01-游戏概览/逃离方式/逃离方式一览.md"),
        ("成就系统", "全部成就与奖励", "07-收集/成就系统.md"),
        ("剧情图鉴与收集", "CG图鉴 / 遗物 / 排行榜", "07-收集/剧情图鉴与收集.md"),
        ("资料来源", "原始资料与作者致谢", "08-附录/资料来源.md"),
    ]))
    write_page("README.md", "".join(content))


# ============================ 迁移与链接重映射 ============================

def migrate_kept_pages():
    """移动保留文章到新目录，并重映射其内部链接。"""
    print("== 迁移既有文章并重映射链接 ==")
    moved = 0
    for old_rel, new_rel in MOVES.items():
        src = abspath(old_rel)
        if not os.path.exists(src):
            print(f"  [警告] 缺失：{old_rel}")
            continue
        text = read(src)
        text = remap_content(text, old_rel, new_rel)
        dst = abspath(new_rel)
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        with open(dst, "w", encoding="utf-8") as f:
            f.write(text)
        if old_rel != new_rel:
            os.remove(src)
        moved += 1
        generated_pages.append(new_rel)
    print(f"  迁移完成 {moved} 篇")


def remap_content(text, old_rel, new_rel):
    """把内容中的站内链接从旧路径体系映射到新路径体系。"""
    base_old = posixpath.dirname(old_rel)
    base_new = posixpath.dirname(new_rel)

    def repl(m):
        label, target = m.group(1), m.group(2)
        if re.match(r"^(https?:|mailto:|#|javascript:)", target):
            return m.group(0)
        anchor = ""
        t = target
        if "#" in t:
            t, anchor = t.split("#", 1)
            anchor = "#" + anchor
        if not t.lower().endswith(".md"):
            return m.group(0)
        resolved_old = posixpath.normpath(posixpath.join(base_old, t))
        resolved_new = LINK_MAP.get(resolved_old, resolved_old)
        rel = posixpath.relpath(resolved_new, base_new)
        return f"[{label}]({rel}{anchor})"

    return re.sub(r"\[([^\]]+)\]\(([^)\s]+)\)", repl, text)


def delete_old_pages():
    print("== 删除被取代的旧集中页 ==")
    for rel in DELETE_OLD:
        p = abspath(rel)
        if os.path.exists(p):
            os.remove(p)
    # 清理空目录
    for root, dirs, files in os.walk(WIKI, topdown=False):
        rel = os.path.relpath(root, WIKI)
        if rel in (".", "legacy"):
            continue
        if not os.listdir(root) and rel.split(os.sep)[0] in ("03-数据资料", "04-攻略指南", "05-收集要素", "附录", "01-游戏概览", "02-核心机制"):
            try:
                os.rmdir(root)
            except OSError:
                pass


# ============================ 主流程 ============================

def main():
    load_all()
    reg = build_registry()
    print(f"  注册表条目：{len(reg)}")

    gen_items(reg)
    gen_monsters()
    gen_maps()
    gen_talents()
    gen_themes()
    gen_minigames()
    gen_buildings()
    gen_characters()
    gen_npcs()
    gen_escapes()
    gen_home(reg)
    migrate_kept_pages()
    delete_old_pages()

    print(f"== 完成：共生成 {len(generated_pages)} 个页面 ==")


if __name__ == "__main__":
    main()