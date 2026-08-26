import openpyxl

REQUIRED_COLUMNS = [
    "Campaign Name",
    "Budget",
    "Advertiser ID",
    "Ad Group Name",
    "TT Mini ID",
    "roas_bid",
    "TT Mini URL",
    "Region",
    "Mini Game Name",
    "ads_text",
    "Identity_ID",
]

# present-if-you-have-them columns - never required, blank/missing is fine:
# - Business Center Account ID: not read for anything, kept only as a legacy label
# - optimization_event: TikTok's UI auto-picks the value type after the mini game
#   is selected, so this column's value is never actually used
# - Ad Group Name Number: how many EXTRA identical copies of this row's ad group
#   to duplicate (on top of the one built from the row itself); defaults to 0
# - CreativeFile: the exact search term to type into the creative-material
#   library's search box - only used when Creative Number > 2 (see below)
# - Creative Number: if > 2, switches this row to manually searching and
#   picking this many materials from the library instead of leaving TikTok's
#   "自动选择" (auto-select) creative behavior as-is (the long-standing
#   default for <=2 or blank) - doubles as both the on/off switch and the
#   count, so no separate toggle column is needed
# - Ad Number（同义写法都认，见下面几个）: 一个广告组里要建几个【广告】。
#   短剧专用：>1 时在同一个广告组下建多个广告，每个广告选【不同】的素材
#   （不是单纯复制内容——复制出来素材会一样）。空或 1 表示只建一个广告。
#   多写几种拼法是因为这一列由使用者手填，叫法不固定；load_rows 会把不在这个
#   名单里的列【整列丢掉】，名字对不上就等于这一列不存在，还很难发现。
# - Unique Creative（同义写法见下）: 小游戏专用的按行开关，1/是/true 表示这一行的
#   多个广告组要【各用不同素材】——复制广告组的时机提前到素材还没加之前，
#   然后沿「继续」逐个广告填。空着就跟随网页上那个全局开关。
#   只有在 Ad Group Name Number > 0 时才有意义，而且需要 Creative Number > 2
#   （否则素材是 TikTok「自动选择」的，重不重复不由我们决定）。
OPTIONAL_COLUMNS = [
    "Business Center Account ID",
    "optimization_event",
    "Ad Group Name Number",
    "CreativeFile",
    "Creative Number",
    "Ad Number",
    "Ads Number",
    "Ad Name Number",
    "ad_number",
    "广告数量",
    "Unique Creative",
    "Unique Creatives",
    "unique_creative",
    "素材不重复",
    "每组素材不同",
    # ---- 短剧端计划用到的 ----
    # 广告组层和广告层的身份是【两个不同的东西】，所以是两列，各存一个身份名字
    # （直接是名字，不是 Identity_ID，不用查身份对照表）。
    # Identity_accoount 是使用者表里的实际拼写（多了一个 o）；把正确拼写也列上，
    # 万一以后改回来了不至于整列被丢掉——load_rows 会把不在这个名单里的列
    # 【整列丢掉】，名字对不上就等于这一列不存在，而且很难发现。
    "Identity_drama",
    "Identity_accoount",
    "Identity_account",
    # 下面这些短剧端表里有、但程序不读，列在这里只是为了别被静默丢掉时让人困惑
    "TikTok Account ID",
    "App Promotion Type",
    "Catalog ID",
    "Catalog Product ID",
    "Schedule_start_time",
]


def load_rows(xlsx_path):
    wb = openpyxl.load_workbook(xlsx_path, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    header = [str(h).strip() if h is not None else "" for h in rows[0]]

    missing = [c for c in REQUIRED_COLUMNS if c not in header]
    if missing:
        raise ValueError(f"Excel缺少必要的列: {missing}")

    idx = {name: header.index(name) for name in REQUIRED_COLUMNS}
    optional_idx = {name: header.index(name) for name in OPTIONAL_COLUMNS if name in header}

    records = []
    # excel_row 是【表格里真实的行号】（表头是第 1 行，所以第一条数据是第 2 行）。
    # 用途：网页上的结果列表每条计划前面标出它来自表格第几行，报错时能直接回表格
    # 定位（使用者要求：「每条广告计划前面标个表格里的序号，我要从表格里面快速
    # 定位到是哪条计划报错的」）。用真实行号而不是从 0 数的下标，就是为了能对着
    # Excel 左边那一列直接看。
    for offset, r in enumerate(rows[1:]):
        if r is None or all(v is None for v in r):
            continue
        record = {name: r[i] for name, i in idx.items()}
        for name, i in optional_idx.items():
            record[name] = r[i]
        if record.get("Ad Group Name Number") in (None, ""):
            record["Ad Group Name Number"] = 0
        record["_excel_row"] = offset + 2
        records.append(record)
    return records


def group_by_campaign(records):
    groups = {}
    order = []
    for rec in records:
        key = (rec["Advertiser ID"], rec["Campaign Name"])
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(rec)
    return [(key, groups[key]) for key in order]
