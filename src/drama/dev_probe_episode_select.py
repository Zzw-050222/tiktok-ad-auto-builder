"""确认「选择短剧」弹层的三个关键点，决定 add_specific_episodes 怎么写。

  ① 每行前面的选择框是【单选还是多选】——圆形看着像 radio，若真是单选，
     一个广告组只能选一部短剧，Excel 里就只填一个 ID。
  ② 「短剧名称」那个下拉能不能切成【按 Series ID 搜索】——能的话就不用翻页，
     直接搜 ID 精确定位（118 件、分页展示，靠翻页找目标既慢又容易错）。
  ③ 搜索之后列表是否真的被过滤到目标那一条。

不勾选、不点「添加」、结束退出草稿。

用法：
    venv/bin/python3 -m src.drama.dev_probe_episode_select <广告主ID> [要搜的SeriesID]
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import ensure_chinese_ui, enable_catalog_campaign
from src.pages.campaign_page import (
    continue_step,
    fill_campaign_details,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.common import exit_draft, wait_until

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def open_dialog(page, advertiser_id):
    ensure_chinese_ui(page, advertiser_id)
    start_new_campaign(page, advertiser_id)
    select_native_growth_objective(page)
    enable_catalog_campaign(page)
    fill_campaign_details(page, "DRAMAPROBE-勿用", "500")
    continue_step(page)
    wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count() > 0,
               timeout_seconds=90)
    page.wait_for_timeout(2000)

    loc = page.locator("text=请选择商品库")
    if loc.count():
        loc.first.click(timeout=8000)
        page.wait_for_timeout(2500)
    idl = page.locator(r'text=/ID[:：]\s*\d{10,}/')
    for i in range(min(idl.count(), 8)):
        if idl.nth(i).is_visible():
            idl.nth(i).click(timeout=8000)
            break
    page.wait_for_timeout(3000)

    add_btn = page.get_by_role("button", name="添加", exact=True)
    for i in range(min(add_btn.count(), 6)):
        if add_btn.nth(i).is_visible():
            add_btn.nth(i).click(timeout=8000)
            break
    # 等剧集真正加载出来：以「Series ID:」出现为准，别以键名/件数为准
    ok = wait_until(page, lambda: page.locator("text=/Series ID/").count() > 0,
                    timeout_seconds=60)
    page.wait_for_timeout(1500)
    return bool(ok)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    advertiser_id = sys.argv[1]
    target_id = sys.argv[2] if len(sys.argv) > 2 else "TIKTOKSERIES096"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            L(f"打开「选择短剧」弹层: {open_dialog(page, advertiser_id)}")
            page.screenshot(path=str(LOGS_DIR / "drama_sel_00_open.png"))

            # ---------- ① 单选还是多选 ----------
            L(f"\n{'=' * 72}\n① 每行的选择框是 radio 还是 checkbox\n{'=' * 72}")
            for role in ("radio", "checkbox"):
                loc = page.get_by_role(role)
                vis = sum(1 for i in range(min(loc.count(), 40))
                          if loc.nth(i).is_visible())
                L(f"  role={role!r}: 命中 {loc.count()} 个，其中可见 {vis} 个")
            info = page.evaluate("""() => {
              const out = [];
              for (const el of document.querySelectorAll('input[type=radio], input[type=checkbox], [role=radio], [role=checkbox]')) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                out.push({tag: el.tagName.toLowerCase(), type: el.getAttribute('type'),
                          role: el.getAttribute('role'),
                          cls: (el.className||'').toString().slice(0,40),
                          x: Math.round(r.x), y: Math.round(r.y)});
              }
              return out.slice(0, 12);
            }""")
            for it in info:
                L(f"    <{it['tag']}> type={it['type']!r} role={it['role']!r} "
                  f"位置=({it['x']},{it['y']}) cls={it['cls']!r}")

            # ---------- ② 搜索维度下拉有哪些选项 ----------
            L(f"\n{'=' * 72}\n② 「短剧名称」下拉能否切成按 Series ID 搜索\n{'=' * 72}")
            dd = page.get_by_text("短剧名称", exact=True)
            clicked = False
            for i in range(min(dd.count(), 6)):
                if dd.nth(i).is_visible():
                    dd.nth(i).click(timeout=8000)
                    clicked = True
                    L("  已点开下拉")
                    page.wait_for_timeout(1800)
                    break
            if clicked:
                opts = page.evaluate("""() => {
                  const out = [];
                  for (const el of document.querySelectorAll('*')) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    const own = Array.from(el.childNodes).filter(n=>n.nodeType===3)
                      .map(n=>n.textContent.trim()).join('').trim();
                    if (own && own.length <= 16 && r.height < 60)
                      out.push({t: own, x: Math.round(r.x), y: Math.round(r.y)});
                  }
                  return out.filter(o => o.x > 800 && o.y > 150 && o.y < 400).slice(0, 25);
                }""")
                L("  下拉附近的候选项：")
                for o in opts:
                    L(f"    ({o['x']},{o['y']}) {o['t']!r}")
                page.screenshot(path=str(LOGS_DIR / "drama_sel_01_dropdown.png"))
                page.keyboard.press("Escape")
                page.wait_for_timeout(800)

            # ---------- ③ 直接把 Series ID 打进搜索框，看能不能过滤到 ----------
            L(f"\n{'=' * 72}\n③ 搜索框直接输入 {target_id!r} 看是否能过滤\n{'=' * 72}")
            before = page.locator("text=/Series ID/").count()
            L(f"  搜索前，页面上 Series ID 行数 = {before}")
            sb = page.get_by_placeholder("搜索")
            typed = False
            for i in range(min(sb.count(), 6)):
                if sb.nth(i).is_visible():
                    sb.nth(i).click(timeout=5000)
                    sb.nth(i).fill(target_id)
                    page.keyboard.press("Enter")
                    typed = True
                    L(f"  已在第 {i} 个可见搜索框里输入并回车")
                    break
            if typed:
                page.wait_for_timeout(4000)
                after = page.locator("text=/Series ID/").count()
                L(f"  搜索后，Series ID 行数 = {after}")
                hits = page.locator(f"text=/Series ID[:：]\\s*{target_id}/")
                L(f"  目标 {target_id!r} 命中 {hits.count()} 个，"
                  f"可见 {sum(1 for i in range(min(hits.count(),5)) if hits.nth(i).is_visible())} 个")
                for i in range(min(page.locator('text=/Series ID/').count(), 6)):
                    try:
                        L(f"    剩余行 [{i}]: "
                          f"{page.locator('text=/Series ID/').nth(i).inner_text().strip()[:50]!r}")
                    except Exception:
                        pass
                page.screenshot(path=str(LOGS_DIR / "drama_sel_02_searched.png"))
            else:
                L("  ⚠ 没找到可见的搜索框")

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_sel_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_episode_select.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_episode_select.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
