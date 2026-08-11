import openpyxl

from src.config import PROJECT_ROOT

IDENTITY_FILE = PROJECT_ROOT / "Identity_id.xlsx"


def load_identity_map():
    wb = openpyxl.load_workbook(IDENTITY_FILE, data_only=True)
    ws = wb["Sheet1"]
    rows = list(ws.iter_rows(values_only=True))
    mapping = {}
    for name, identity_id in rows[1:]:
        if identity_id is None:
            continue
        mapping[str(identity_id).strip()] = name
    return mapping


def resolve_identity(identity_id: str):
    mapping = load_identity_map()
    return mapping.get(identity_id.strip())
