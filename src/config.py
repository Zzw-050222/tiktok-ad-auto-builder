from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
BROWSER_PROFILE_DIR = PROJECT_ROOT / "browser_profile"
DATA_DIR = PROJECT_ROOT / "data"
LOGS_DIR = PROJECT_ROOT / "logs"
UPLOADS_DIR = PROJECT_ROOT / "uploads"

REGION_MAP_PATH = DATA_DIR / "region_map.json"
IDENTITY_MAP_PATH = DATA_DIR / "identity_map.json"

ADS_MANAGER_DASHBOARD_URL = "https://ads.tiktok.com/i18n/dashboard"
ADS_MANAGER_LOGIN_URL = "https://ads.tiktok.com/i18n/login"

LOCALE = "zh-CN"
ACCEPT_LANGUAGE = "zh-CN,zh;q=0.9"

for d in (BROWSER_PROFILE_DIR, DATA_DIR, LOGS_DIR, UPLOADS_DIR):
    d.mkdir(parents=True, exist_ok=True)
