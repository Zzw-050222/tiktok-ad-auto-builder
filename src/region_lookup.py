import re

import openpyxl

from src.config import PROJECT_ROOT

REGION_FILE = PROJECT_ROOT / "REGION.xlsx"

# Accept a full-width Chinese comma "，" as a separator too - easy to type by
# accident with a Chinese IME, and looks identical to "," at a glance in Excel.
_REGION_SPLIT_RE = re.compile("[,，]")


def load_region_map():
    wb = openpyxl.load_workbook(REGION_FILE, data_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))
    mapping = {}
    for region_id, country in rows[1:]:
        if region_id is None:
            continue
        mapping[str(int(region_id))] = country
    return mapping


def resolve_regions(region_ids_csv: str):
    mapping = load_region_map()
    ids = [x.strip() for x in _REGION_SPLIT_RE.split(region_ids_csv) if x.strip()]
    pairs = []
    missing = []
    for rid in ids:
        if rid in mapping:
            pairs.append((rid, mapping[rid]))
        else:
            missing.append(rid)
    return pairs, missing
