"""挖广告组层两处新界面的结构：「关联的商品库」下拉 和「特定剧集」。

走完整的前半段（选目标 -> 打开商品库开关 -> 填计划名和预算 -> 继续），到广告组
页后 dump：
  1. 「关联的商品库」下拉：收起态的结构、点开后列表项的结构（重点找商品库 ID
     在 DOM 里以什么形式存在——截图上看得到「ID: 7665919003159774992」）
  2. 「特定剧集」的「+ 添加」按钮，点开后剧集列表的结构

不选任何东西、不发布，结束退出草稿。

用法：
    venv/bin/python3 -m src.drama.dev_probe_adgroup_dom <广告主ID> [计划名] [预算]
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


# 以一段文字为锚点，dump 附近所有实际渲染的元素（含属性），用来找可靠的定位方式
_DUMP_NEAR_JS = """
([anchorText, below, above, limit]) => {
  let anchorY = null;
  const walkFind = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walkFind(el.shadowRoot);
      const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
        .map(n => n.textContent.trim()).join('').trim();
      // 锚点既可以是文字节点，也可以是 placeholder —— 「搜索商品库 ID 或名称」
      // 就是 placeholder 属性而不是文字，上一版只找文字节点所以报「找不到」，
      // 而实际上下拉是成功展开了的。
      const ph = el.getAttribute ? (el.getAttribute('placeholder') || '') : '';
      if (own === anchorText || ph === anchorText) {
        const r = el.getBoundingClientRect();
        if (r.width > 0 && r.height > 0 && (anchorY === null || r.y < anchorY)) anchorY = r.y;
      }
    }
  };
  walkFind(document);
  if (anchorY === null) return {anchorY: null, items: []};
  const items = [];
  const walk = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walk(el.shadowRoot);
      const r = el.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) continue;
      if (r.y < anchorY - above || r.y > anchorY + below) continue;
      const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
        .map(n => n.textContent.trim()).join(' ').trim();
      const attrs = {};
      for (const a of ['role','aria-checked','aria-expanded','data-testid','type',
                       'placeholder','id','value','title']) {
        const v = el.getAttribute && el.getAttribute(a);
        if (v !== null && v !== undefined) attrs[a] = String(v).slice(0, 70);
      }
      const cls = (el.className && el.className.toString)
                    ? el.className.toString().slice(0, 44) : '';
      if (!own && !Object.keys(attrs).length) continue;
      items.push({tag: el.tagName.toLowerCase(), x: Math.round(r.x), y: Math.round(r.y),
                  w: Math.round(r.width), h: Math.round(r.height),
                  text: own.slice(0, 60), attrs, cls});
    }
  };
  walk(document);
  items.sort((a, b) => a.y - b.y);
  return {anchorY: Math.round(anchorY), items: items.slice(0, limit)};
}
"""


def dump_near(page, anchor, tag, below=400, above=50, limit=45):
    L(f"\n{'=' * 72}")
    L(f"{tag}   （锚点：{anchor!r}）")
    L("=" * 72)
    try:
        res = page.evaluate(_DUMP_NEAR_JS, [anchor, below, above, limit])
    except Exception as e:
        L(f"  执行出错: {e}")
        return False
    if res["anchorY"] is None:
        L(f"  ⚠ 页面上找不到可见的 {anchor!r}")
        return False
    L(f"  锚点 y={res['anchorY']}")
    for it in res["items"]:
        a = " ".join(f"{k}={v!r}" for k, v in it["attrs"].items())
        L(f"  ({it['x']:>4},{it['y']:>4}) {it['w']:>4}x{it['h']:<4} <{it['tag']}> {it['text']!r}"
          + (f"  {a}" if a else "")
          + (f"  cls={it['cls']!r}" if it["cls"] else ""))
    return True


def shot(page, name):
    try:
        page.screenshot(path=str(LOGS_DIR / f"drama_ag_{name}.png"))
        L(f"  截图: drama_ag_{name}.png")
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    advertiser_id = sys.argv[1]
    campaign_name = sys.argv[2] if len(sys.argv) > 2 else "DRAMAPROBE-勿用"
    budget = sys.argv[3] if len(sys.argv) > 3 else "500"

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
            L("已选「TikTok 即时增长」")

            changed = enable_catalog_campaign(page)
            L(f"商品库开关: {'已打开' if changed else '本来就是开的'}")

            budget_at_campaign = fill_campaign_details(page, campaign_name, budget)
            L(f"计划名和预算已填（预算在计划层={budget_at_campaign}）")
            continue_step(page)

            ok = wait_until(page, lambda: page.get_by_text("广告组名称", exact=True).count() > 0,
                            timeout_seconds=90)
            L(f"进入广告组页: {bool(ok)}")
            page.wait_for_timeout(2000)
            shot(page, "00_adgroup")

            # ---------- ① 关联的商品库（收起态） ----------
            dump_near(page, "关联的商品库", "① 关联的商品库（收起）", below=220, above=60)
            shot(page, "01_catalog_closed")

            # ---------- ② 点开下拉，看列表项 ----------
            L(f"\n{'=' * 72}\n② 点开「关联的商品库」下拉\n{'=' * 72}")
            opened = False
            for sel in ['[placeholder*="选择商品库"]', 'text=请选择商品库',
                        '[class*="catalog"] [role="combobox"]']:
                loc = page.locator(sel)
                L(f"  尝试 {sel!r}: 命中 {loc.count()}")
                if loc.count():
                    try:
                        loc.first.scroll_into_view_if_needed(timeout=5000)
                        loc.first.click(timeout=8000)
                        opened = True
                        L("  -> 已点击")
                        page.wait_for_timeout(2500)
                        break
                    except Exception as e:
                        L(f"  -> 点击失败 {e}")
            if opened:
                dump_near(page, "搜索商品库 ID 或名称", "③ 下拉展开后的列表",
                          below=340, above=40, limit=55)
                shot(page, "02_catalog_open")
            else:
                L("  ⚠ 没能点开下拉，后面跳过")
                raise RuntimeError("下拉没打开")

            # ---------- ④ 按 ID 选中商品库 ----------
            # 列表项里「ID: 7665919003159774992」是【文字】，可以精确匹配——和小游戏
            # 用「ID: <小游戏ID>」定位是同一个套路，避免按名称匹配点错。
            L(f"\n{'=' * 72}\n④ 按 ID 文字选中商品库\n{'=' * 72}")
            id_loc = page.locator('text=/ID[:：]\\s*\\d{10,}/')
            n = id_loc.count()
            L(f"  形如「ID: 数字」的元素命中 {n} 个")
            picked_id = None
            for i in range(min(n, 8)):
                try:
                    t = id_loc.nth(i).inner_text().strip()
                    vis = id_loc.nth(i).is_visible()
                    L(f"    [{i}] {t!r} 可见={vis}")
                    if vis and picked_id is None:
                        picked_id = t
                        id_loc.nth(i).scroll_into_view_if_needed(timeout=5000)
                        id_loc.nth(i).click(timeout=8000)
                        L(f"    -> 点了它")
                        page.wait_for_timeout(3000)
                except Exception as e:
                    L(f"    [{i}] 读取/点击出错 {e}")
            shot(page, "03_catalog_picked")

            # ---------- ⑤ 选完之后出现了什么 ----------
            for anchor, tag in [
                ("特定剧集", "⑤ 特定剧集区域"),
                ("短剧", "⑤b 「短剧」字段"),
                ("选择 TikTok Mini", "⑤c 「选择 TikTok Mini」选择器"),
            ]:
                dump_near(page, anchor, tag, below=280, above=50, limit=35)

            # ---------- ⑥ 点「添加」，看剧集列表 ----------
            L(f"\n{'=' * 72}\n⑥ 点「特定剧集」的「添加」按钮\n{'=' * 72}")
            add_btn = page.get_by_role("button", name="添加", exact=True)
            n_add = add_btn.count()
            L(f"  文字恰好是「添加」的按钮命中 {n_add} 个（注意区别于「添加商品库」）")
            clicked = False
            for i in range(min(n_add, 6)):
                try:
                    b = add_btn.nth(i)
                    if not b.is_visible():
                        L(f"    [{i}] 不可见，跳过")
                        continue
                    box = b.bounding_box()
                    L(f"    [{i}] 可见 位置=({int(box['x'])},{int(box['y'])})" if box else f"    [{i}] 可见")
                    if not clicked:
                        b.scroll_into_view_if_needed(timeout=5000)
                        b.click(timeout=8000)
                        clicked = True
                        L("    -> 点了它")
                        page.wait_for_timeout(3000)
                except Exception as e:
                    L(f"    [{i}] 出错 {e}")
            shot(page, "04_episodes_dialog")

            if clicked:
                for anchor, tag in [
                    ("特定剧集", "⑦ 点开后：特定剧集附近"),
                    ("搜索", "⑦b 可能的搜索框"),
                ]:
                    dump_near(page, anchor, tag, below=460, above=80, limit=60)
                # 剧集有没有 ID 形式的文字——这是能不能按 ID 精确匹配的关键
                L(f"\n{'=' * 72}\n⑧ 弹层里形如「ID: 数字」的文字（决定能否按 ID 匹配）\n{'=' * 72}")
                idl = page.locator('text=/ID[:：]\\s*\\w{6,}/')
                L(f"  命中 {idl.count()} 个")
                for i in range(min(idl.count(), 12)):
                    try:
                        L(f"    [{i}] {idl.nth(i).inner_text().strip()[:70]!r} 可见={idl.nth(i).is_visible()}")
                    except Exception as e:
                        L(f"    [{i}] 读取出错 {e}")

            L("\n探针到此为止。")

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            shot(page, "ERROR")
        finally:
            with open(str(LOGS_DIR / "drama_adgroup_dom.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_adgroup_dom.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
