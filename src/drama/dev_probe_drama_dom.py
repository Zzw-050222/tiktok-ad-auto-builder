"""挖短剧商品库流程里三处新界面的真实 DOM，为写定位器做准备。

短剧和小游戏的推广目标同为「TikTok 即时增长」，计划层的名称/预算也一样，
差别集中在三处：
  1. 计划层多一个「设置商品库推广系列」开关，默认关闭，必须打开
  2. 广告组层用「关联的商品库」下拉取代小游戏选择器
  3. 广告组层多一个「特定剧集」，点「+ 添加」出现剧集列表

本探针只走到广告组层就停，把这三处的结构 dump 下来，最后退出草稿。
不填预算之外的任何内容、不发布、不选素材。

用法（项目根目录）：
    venv/bin/python3 -m src.drama.dev_probe_drama_dom <广告主ID>

跑完看 logs/drama_dom.txt
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import ensure_chinese_ui
from src.pages.campaign_page import (
    continue_step,
    select_native_growth_objective,
    start_new_campaign,
)
from src.pages.common import exit_draft, wait_until

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


# 以一段文字为锚点，把它附近实际渲染出来的元素全部列出来。
# 重点带上 role / aria-checked / data-testid / class —— 开关和下拉的状态就藏在这些属性里。
_DUMP_NEAR_JS = """
([anchorText, below, above]) => {
  let anchorY = null;
  const walkFind = (root) => {
    for (const el of root.querySelectorAll('*')) {
      if (el.shadowRoot) walkFind(el.shadowRoot);
      const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
        .map(n => n.textContent.trim()).join('').trim();
      if (own === anchorText) {
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
      for (const a of ['role','aria-checked','aria-expanded','aria-label','data-testid',
                       'type','placeholder','id','value','disabled']) {
        const v = el.getAttribute && el.getAttribute(a);
        if (v !== null && v !== undefined) attrs[a] = String(v).slice(0, 60);
      }
      const cls = (el.className && el.className.toString)
                    ? el.className.toString().slice(0, 50) : '';
      // 只留有信息量的：有文字、有 role/aria/testid、或是表单元素
      if (!own && !Object.keys(attrs).length && !/input|button|label|switch/i.test(el.tagName)) continue;
      items.push({
        tag: el.tagName.toLowerCase(),
        y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height),
        text: own.slice(0, 50), attrs, cls,
      });
    }
  };
  walk(document);
  items.sort((a, b) => a.y - b.y);
  return {anchorY: Math.round(anchorY), items: items.slice(0, 60)};
}
"""


def dump_near(page, anchor, tag, below=420, above=60):
    L(f"\n{'=' * 70}")
    L(f"{tag}   （锚点文字：{anchor!r}）")
    L("=" * 70)
    try:
        res = page.evaluate(_DUMP_NEAR_JS, [anchor, below, above])
    except Exception as e:
        L(f"  执行出错: {e}")
        return
    if res["anchorY"] is None:
        L(f"  ⚠ 页面上找不到可见的 {anchor!r}")
        return
    L(f"  锚点 y={res['anchorY']}，往下 {below}px / 往上 {above}px 内的元素：")
    for it in res["items"]:
        a = " ".join(f"{k}={v!r}" for k, v in it["attrs"].items())
        L(f"  y={it['y']:>5} {it['w']:>4}x{it['h']:<4} <{it['tag']}> {it['text']!r}"
          + (f"  {a}" if a else "")
          + (f"  class={it['cls']!r}" if it["cls"] else ""))


def shot(page, name):
    p = LOGS_DIR / f"drama_{name}.png"
    try:
        page.screenshot(path=str(p))
        L(f"  截图: {p.name}")
    except Exception:
        pass


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
            L(f"广告主 {advertiser_id}")
            ensure_chinese_ui(page, advertiser_id)
            start_new_campaign(page, advertiser_id)
            select_native_growth_objective(page)
            L("已选中「TikTok 即时增长」")
            page.wait_for_timeout(1500)

            # ---------- ① 商品库推广系列开关 ----------
            dump_near(page, "设置商品库推广系列", "① 商品库推广系列开关（打开之前）",
                      below=200, above=40)
            shot(page, "01_toggle_before")

            # ---------- ② 打开它，再看状态变化 ----------
            L(f"\n{'=' * 70}\n② 尝试打开开关\n{'=' * 70}")
            toggled = False
            for sel in ['[role="switch"]', 'button[aria-checked]', '.ks-switch', '[class*="switch"]']:
                loc = page.locator(sel)
                n = loc.count()
                L(f"  选择器 {sel!r}: 命中 {n} 个")
                for i in range(min(n, 6)):
                    e = loc.nth(i)
                    try:
                        vis, checked = e.is_visible(), e.get_attribute("aria-checked")
                        box = e.bounding_box()
                        L(f"    [{i}] 可见={vis} aria-checked={checked!r} "
                          f"位置={f'({int(box[chr(120)])},{int(box[chr(121)])})' if box else '-'}")
                    except Exception as ex:
                        L(f"    [{i}] 读取出错 {ex}")
                if n and not toggled:
                    try:
                        loc.first.click(timeout=5000)
                        toggled = True
                        L(f"  -> 点了 {sel!r} 的第一个")
                        page.wait_for_timeout(1500)
                    except Exception as ex:
                        L(f"  -> 点击失败 {ex}")
                if toggled:
                    break

            dump_near(page, "设置商品库推广系列", "① 商品库推广系列开关（打开之后）",
                      below=200, above=40)
            shot(page, "02_toggle_after")

            L("\n探针到此为止：后面的填名称/预算/继续需要确认开关确实打开了再做。")
            L("请看截图 drama_02_toggle_after.png 确认开关是否已打开。")

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
            shot(page, "ERROR")
        finally:
            with open(str(LOGS_DIR / "drama_dom.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_dom.txt'}")
            try:
                exit_draft(page)
            except Exception:
                pass
            context.close()


if __name__ == "__main__":
    main()
