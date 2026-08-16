"""挖「特定剧集」弹层的结构 —— 这个弹层的文案没翻译，全是 i18n 键名。

2026-08-16 截图确认：弹层标题是 module_common_add_series，搜索框 placeholder 是
module_dpa_pset_search_placeholder，左侧列表项是
module_creative_product_details_all_series。也就是说【弹层里没有中文可以当锚点】，
定位必须靠这些键名或者结构。

上一版只等了 3 秒，右侧还在转圈、显示「0件」。这一版：
  * 点开后轮询等列表真正加载出来（件数 > 0），最多 60 秒
  * 期间每隔几秒 dump 一次件数，看它到底是在加载还是本来就是空的
  * 加载出来后 dump 左右两栏的完整结构，重点找剧集的唯一 ID

不勾选任何剧集、不点「添加」、结束退出草稿。

用法：
    venv/bin/python3 -m src.drama.dev_probe_episode_dialog <广告主ID>
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

# 弹层里出现的 i18n 键名（截图确认），用作定位锚点
DIALOG_TITLE_KEY = "module_common_add_series"
SEARCH_PH_KEY = "module_dpa_pset_search_placeholder"


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


# dump 整个弹层：以标题键名为锚，往下把所有渲染出来的元素列出来
_DUMP_DIALOG_JS = """
([titleKey, limit]) => {
  let root = null;
  const all = document.querySelectorAll('*');
  for (const el of all) {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join('').trim();
    if (own === titleKey) {
      // 往上找这个弹层的容器
      let n = el;
      for (let k = 0; k < 8 && n; k++) {
        n = n.parentElement;
        if (n && n.getBoundingClientRect().height > 400) { root = n; break; }
      }
      break;
    }
  }
  if (!root) return {found: false};
  const items = [];
  for (const el of root.querySelectorAll('*')) {
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join(' ').trim();
    const attrs = {};
    for (const a of ['role','aria-checked','data-testid','type','placeholder',
                     'id','value','title','alt','disabled']) {
      const v = el.getAttribute && el.getAttribute(a);
      if (v !== null && v !== undefined) attrs[a] = String(v).slice(0, 70);
    }
    if (!own && !Object.keys(attrs).length) continue;
    items.push({tag: el.tagName.toLowerCase(), x: Math.round(r.x), y: Math.round(r.y),
                w: Math.round(r.width), h: Math.round(r.height),
                text: own.slice(0, 60), attrs,
                cls: (el.className && el.className.toString
                        ? el.className.toString() : '').slice(0, 40)});
  }
  items.sort((a, b) => (a.y - b.y) || (a.x - b.x));
  return {found: true, count: items.length, items: items.slice(0, limit)};
}
"""


def dump_dialog(page, tag, limit=90):
    L(f"\n{'=' * 72}\n{tag}\n{'=' * 72}")
    try:
        r = page.evaluate(_DUMP_DIALOG_JS, [DIALOG_TITLE_KEY, limit])
    except Exception as e:
        L(f"  执行出错: {e}")
        return
    if not r.get("found"):
        L(f"  ⚠ 找不到弹层（锚点 {DIALOG_TITLE_KEY!r}）")
        return
    L(f"  弹层内可见元素共 {r['count']} 个，列前 {len(r['items'])} 个：")
    for it in r["items"]:
        a = " ".join(f"{k}={v!r}" for k, v in it["attrs"].items())
        L(f"  ({it['x']:>4},{it['y']:>4}) {it['w']:>4}x{it['h']:<4} <{it['tag']}> {it['text']!r}"
          + (f"  {a}" if a else "")
          + (f"  cls={it['cls']!r}" if it["cls"] else ""))


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    advertiser_id = sys.argv[1]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            ensure_chinese_ui(page, advertiser_id)
            start_new_campaign(page, advertiser_id)
            select_native_growth_objective(page)
            enable_catalog_campaign(page)
            fill_campaign_details(page, "DRAMAPROBE-勿用", "500")
            continue_step(page)
            wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count() > 0,
                       timeout_seconds=90)
            page.wait_for_timeout(2000)
            L("已到广告组页")

            # 选商品库（按 ID 文字，只点可见的）
            for sel in ['text=请选择商品库']:
                loc = page.locator(sel)
                if loc.count():
                    loc.first.click(timeout=8000)
                    page.wait_for_timeout(2500)
            idl = page.locator('text=/ID[:：]\\s*\\d{10,}/')
            for i in range(min(idl.count(), 8)):
                if idl.nth(i).is_visible():
                    idl.nth(i).click(timeout=8000)
                    L(f"已选商品库: {idl.nth(i).inner_text().strip()!r}")
                    break
            page.wait_for_timeout(3000)

            # 点「添加」打开剧集弹层
            add_btn = page.get_by_role("button", name="添加", exact=True)
            for i in range(min(add_btn.count(), 6)):
                if add_btn.nth(i).is_visible():
                    add_btn.nth(i).click(timeout=8000)
                    L("已点「添加」")
                    break
            page.wait_for_timeout(2000)

            # 轮询等剧集列表加载出来 —— 上一版只等 3 秒，右侧还在转圈显示「0件」
            L(f"\n{'=' * 72}\n等剧集列表加载（最多 60 秒，每 3 秒看一次件数）\n{'=' * 72}")

            def count_text():
                loc = page.locator('text=/^\\d+\\s*件$/')
                for i in range(min(loc.count(), 5)):
                    try:
                        if loc.nth(i).is_visible():
                            return loc.nth(i).inner_text().strip()
                    except Exception:
                        pass
                return None

            for rnd in range(20):
                c = count_text()
                L(f"  第 {rnd * 3:>2} 秒: 件数显示 = {c!r}")
                if c and not c.startswith("0"):
                    L("  -> 列表已加载出内容")
                    break
                page.wait_for_timeout(3000)

            page.screenshot(path=str(LOGS_DIR / "drama_ep_loaded.png"))
            dump_dialog(page, "剧集弹层的完整结构")

            # 弹层里有没有 ID 形式的文字 —— 决定能否按剧集 ID 精确匹配
            L(f"\n{'=' * 72}\n弹层里形如 ID 的文字\n{'=' * 72}")
            for pat, name in [('text=/ID[:：]\\s*\\w{6,}/', "ID: xxx"),
                              ('text=/^[a-z0-9]{14,20}$/', "纯 ID 串")]:
                loc = page.locator(pat)
                L(f"  {name}: 命中 {loc.count()}")
                for i in range(min(loc.count(), 10)):
                    try:
                        L(f"    [{i}] {loc.nth(i).inner_text().strip()[:70]!r} "
                          f"可见={loc.nth(i).is_visible()}")
                    except Exception:
                        pass

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_ep_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_episode_dialog.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_episode_dialog.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
