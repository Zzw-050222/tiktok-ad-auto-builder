"""点开 TikTok Mini 选择器，用差集看展开后新出现了什么。

上次对付搜索维度下拉时这招一次就找到了答案（选项是 <span>，文字带空格）。
这次不再猜 li / [role=option] / ks-option 之类。
"""
import sys, traceback
from playwright.sync_api import sync_playwright
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.adgroup_page import (_find_mini_select, add_specific_episode,
                                          fill_ad_group_name, select_product_catalog)
from src.drama.pages.campaign_page import enable_catalog_campaign, ensure_chinese_ui
from src.pages.campaign_page import (continue_step, fill_campaign_details,
                                     select_native_growth_objective, start_new_campaign)
from src.pages.common import exit_draft, wait_until

OUT = []
def L(s=""):
    OUT.append(s); print(s, flush=True)

# 递归穿透 shadow DOM 收集所有可见元素（上一个探针漏了这个，导致误判「找不到」）
SNAP = """
() => {
  const out = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
        .map(n=>n.textContent.trim()).join('').trim();
      if (!t || t.length > 40) continue;
      out.push({t, x: Math.round(r.x), y: Math.round(r.y),
                tag: el.tagName.toLowerCase(),
                cls: (el.className && el.className.toString ? el.className.toString():'').slice(0,50),
                testid: el.getAttribute ? (el.getAttribute('data-testid')||'') : ''});
    }
  };
  walk(document);
  return out;
}
"""

def main():
    adv = "7654526429006315541"
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR), headless=False,
            locale=LOCALE, extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            ensure_chinese_ui(page, adv); start_new_campaign(page, adv)
            select_native_growth_objective(page); enable_catalog_campaign(page)
            fill_campaign_details(page, "DRAMAPROBE-勿用", "500"); continue_step(page)
            wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count()>0,
                       timeout_seconds=90)
            page.wait_for_timeout(1500)
            fill_ad_group_name(page, "DRAMAPROBE-ag")
            select_product_catalog(page, catalog_id=None)
            add_specific_episode(page, series_id="TIKTOKSERIES002",
                                 series_name="The Tyrant of Silvermoon")
            L("前 9 步完成")
            page.wait_for_timeout(2000)

            sel, text_before = _find_mini_select(page)
            L(f"TikTok Mini 选择器: 找到={sel is not None} 当前文字={text_before!r}")
            if sel is None:
                raise RuntimeError("没找到选择器")

            before = {(o['t'], o['x'], o['y']) for o in page.evaluate(SNAP)}
            sel.scroll_into_view_if_needed(timeout=5000)
            sel.click(timeout=8000)
            page.wait_for_timeout(2500)
            page.screenshot(path=str(LOGS_DIR/"drama_miniopts.png"))

            after = page.evaluate(SNAP)
            new = [o for o in after if (o['t'], o['x'], o['y']) not in before]
            L(f"\n=== 点开后【新出现】的元素 {len(new)} 个 ===")
            for o in new[:30]:
                L(f"  ({o['x']:>4},{o['y']:>4}) <{o['tag']}> {o['t']!r} "
                  f"cls={o['cls']!r} testid={o['testid']!r}")
        except Exception:
            L(traceback.format_exc())
            try: page.screenshot(path=str(LOGS_DIR/"drama_miniopts_ERR.png"))
            except Exception: pass
        finally:
            with open(str(LOGS_DIR/"drama_mini_opts.txt"),"w",encoding="utf-8") as f:
                f.write("\n".join(OUT))
            try: exit_draft(page)
            except Exception: pass
            ctx.close()

main()
