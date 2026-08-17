"""探计划列表页：第一行计划怎么点、右上角「创建」按钮长什么样。

新流程需要：发布完回到计划列表 -> 点列表第一个计划（就是刚建的那个）->
进广告组列表 -> 点右上「创建」-> 回到广告组层级继续建下一个。

这三个定位一个都不能猜——点错行会把广告组建进【别的计划】里，而且是真发布、
真花钱。所以先 dump 真实结构。

用法：
    venv/bin/python3 -m src.drama.dev_probe_campaign_list <广告主ID>
"""

import sys

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


# 计划列表的行：把带链接/带名字的候选行连同祖先属性打出来
_ROWS_JS = """
() => {
  const out = [];
  // 表格行的常见承载：tr、role=row、或带 data-testid 的 div
  const cands = document.querySelectorAll(
    'tr, [role="row"], [data-testid*="row"], [data-testid*="Row"]');
  let i = 0;
  for (const el of cands) {
    const r = el.getBoundingClientRect();
    if (r.width < 200 || r.height < 20) continue;
    const txt = (el.innerText || '').replace(/\\s+/g, ' ').trim();
    if (!txt) continue;
    const attrs = {};
    for (const a of el.attributes || []) {
      if (/testid|role|class|id/i.test(a.name)) attrs[a.name] = (a.value || '').slice(0, 70);
    }
    out.push({
      i: i++,
      tag: el.tagName.toLowerCase(),
      y: Math.round(r.y),
      h: Math.round(r.height),
      text: txt.slice(0, 90),
      attrs: attrs,
    });
    if (i >= 14) break;
  }
  return out;
}
"""

# 名字那一格里的可点元素（链接 / span），这是真正要点的东西
_NAME_CELL_JS = """
(needle) => {
  const out = [];
  for (const el of document.querySelectorAll('a, span, div')) {
    const own = Array.from(el.childNodes).filter(n => n.nodeType === 3)
      .map(n => n.textContent.trim()).join('').trim();
    if (!own || own.length < 6) continue;
    if (needle && !own.includes(needle)) continue;
    const r = el.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    const attrs = {};
    for (const a of el.attributes || []) {
      if (/testid|href|class/i.test(a.name)) attrs[a.name] = (a.value || '').slice(0, 70);
    }
    out.push({tag: el.tagName.toLowerCase(), text: own.slice(0, 80),
              y: Math.round(r.y), attrs: attrs});
    if (out.length >= 12) break;
  }
  return out;
}
"""


def dump_buttons(page, label):
    L(f"\n--- {label}：页面上可见的按钮 ---")
    btns = page.get_by_role("button")
    n = btns.count()
    for i in range(min(n, 40)):
        b = btns.nth(i)
        try:
            if not b.is_visible():
                continue
            t = (b.inner_text() or "").replace("\n", " ").strip()
            if not t:
                continue
            box = b.bounding_box()
            L(f"  按钮 #{i} ({round(box['x']) if box else '?'},"
              f"{round(box['y']) if box else '?'}) {t[:40]!r}")
        except Exception:
            continue


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    adv = sys.argv[1]

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            url = f"https://ads.tiktok.com/i18n/manage/campaign?aadvid={adv}"
            L(f"打开计划列表: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(9000)
            page.screenshot(path=str(LOGS_DIR / "drama_campaign_list.png"))

            L(f"\n{'=' * 72}\n计划列表的行\n{'=' * 72}")
            for r in page.evaluate(_ROWS_JS):
                a = " ".join(f"{k}={v!r}" for k, v in r["attrs"].items())
                L(f"  #{r['i']} <{r['tag']}> y={r['y']} h={r['h']}")
                L(f"      文字: {r['text']!r}")
                if a:
                    L(f"      属性: {a}")

            L(f"\n{'=' * 72}\n名字格里的可点元素（找含 '-' 的计划名）\n{'=' * 72}")
            for c in page.evaluate(_NAME_CELL_JS, "-"):
                a = " ".join(f"{k}={v!r}" for k, v in c["attrs"].items())
                L(f"  <{c['tag']}> y={c['y']} {c['text']!r}")
                if a:
                    L(f"      {a}")

            dump_buttons(page, "计划列表页")

        except Exception:
            import traceback
            L("\n出错:")
            L(traceback.format_exc())
            try:
                page.screenshot(path=str(LOGS_DIR / "drama_campaign_list_ERROR.png"))
            except Exception:
                pass
        finally:
            with open(str(LOGS_DIR / "drama_campaign_list.txt"), "w",
                      encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_campaign_list.txt'}")
            context.close()


if __name__ == "__main__":
    main()
