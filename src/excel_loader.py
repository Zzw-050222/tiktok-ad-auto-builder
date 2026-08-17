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
    for r in rows[1:]:
        if r is None or all(v is None for v in r):
            continue
        record = {name: r[i] for name, i in idx.items()}
        for name, i in optional_idx.items():
            record[name] = r[i]
        if record.get("Ad Group Name Number") in (None, ""):
            record["Ad Group Name Number"] = 0
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
