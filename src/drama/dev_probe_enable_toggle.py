"""验证 enable_catalog_campaign 的三种情形都正确。

  情形一：开关本来是关的 -> 应当打开它，返回 True
  情形二：已经是打开的   -> 应当【不动它】，返回 False（这是最关键的一条：
                            开关多点一次就会关掉，而且不报错）
  情形三：连点两次后仍然是打开的（确认没有被误关）

跑完退出草稿，不留下设置。

用法：
    venv/bin/python3 -m src.drama.dev_probe_enable_toggle <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import (
    ensure_chinese_ui,
    CATALOG_SWITCH_CSS,
    _switch_is_on,
    enable_catalog_campaign,
)
from src.pages.campaign_page import select_native_growth_objective, start_new_campaign
from src.pages.common import exit_draft

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def read_state(page):
    loc = page.locator(CATALOG_SWITCH_CSS)
    if loc.count() == 0:
        return "找不到开关"
    return _switch_is_on(loc.first)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    advertiser_id = sys.argv[1]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            ensure_chinese_ui(page, advertiser_id)
            start_new_campaign(page, advertiser_id)
            select_native_growth_objective(page)
            page.wait_for_timeout(2000)

            L(f"初始状态: {read_state(page)}（按说明应当是 False，即默认关闭）")

            L("\n--- 情形一：本来是关的，调用一次 ---")
            changed = enable_catalog_campaign(page)
            L(f"  返回 {changed}（True = 它动手打开了）")
            L(f"  现在状态: {read_state(page)}   {'✓' if read_state(page) is True else '✗ 应当是 True'}")
            page.screenshot(path=str(LOGS_DIR / "drama_enable_1.png"))

            L("\n--- 情形二：已经是开的，再调用一次（最关键）---")
            changed2 = enable_catalog_campaign(page)
            state2 = read_state(page)
            L(f"  返回 {changed2}（应当是 False = 认出已打开、没去动它）")
            L(f"  现在状态: {state2}   "
              f"{'✓ 没有被误关' if state2 is True else '✗ 被关掉了！这正是要防的事故'}")
            page.screenshot(path=str(LOGS_DIR / "drama_enable_2.png"))

            L("\n--- 情形三：再调一次，确认幂等 ---")
            changed3 = enable_catalog_campaign(page)
            state3 = read_state(page)
            L(f"  返回 {changed3}  状态 {state3}   "
              f"{'✓ 幂等' if (changed3 is False and state3 is True) else '✗ 不幂等'}")
            page.screenshot(path=str(LOGS_DIR / "drama_enable_3.png"))

            ok = (changed is True and changed2 is False and changed3 is False
                  and state2 is True and state3 is True)
            L(f"\n{'=' * 60}")
            L("总判定: " + ("✓ 全部通过 —— 打开一次、之后不再动它"
                            if ok else "✗ 有不符合预期的地方，见上面"))
            L("=" * 60)

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_enable_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_enable_toggle.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_enable_toggle.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
