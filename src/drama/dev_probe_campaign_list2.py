"""再探计划列表：改用 Playwright 定位器（能穿透 shadow DOM）+ 检查 iframe。

第一版探针用 document.querySelectorAll 扫，结果行和按钮几乎都没扫到——这个后台
大量内容在 shadow DOM 里，原生 API 看不见。这是本项目反复踩的同一个坑：
【找元素一律用 Playwright 定位器】。

用法：
    venv/bin/python3 -m src.drama.dev_probe_campaign_list2 <广告主ID> [计划名前缀]
"""

import sys

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

REPORT = []


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    adv = sys.argv[1]
    needle = sys.argv[2] if len(sys.argv) > 2 else "The Alpha"

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
            L(f"打开: {url}")
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(12000)
            page.screenshot(path=str(LOGS_DIR / "drama_list2.png"))
            L(f"当前地址: {page.url[:120]}")

            L(f"\n--- iframe ---")
            for i, fr in enumerate(page.frames):
                L(f"  frame#{i} name={fr.name!r} url={fr.url[:90]!r}")

            L(f"\n--- 含 {needle!r} 的可见元素（定位器，穿透 shadow DOM）---")
            loc = page.get_by_text(needle, exact=False)
            L(f"  命中 {loc.count()} 个")
            for i in range(min(loc.count(), 10)):
                el = loc.nth(i)
                try:
                    if not el.is_visible():
                        continue
                    box = el.bounding_box()
                    t = (el.inner_text() or "").replace("\n", " ")
                    info = el.evaluate("""e => {
                      const a = {};
                      for (const x of e.attributes || []) a[x.name] = (x.value||"").slice(0,60);
                      return {tag: e.tagName.toLowerCase(), attrs: a};
                    }""")
                    L(f"  #{i} <{info['tag']}> y={round(box['y']) if box else '?'} {t.strip()[:70]!r}")
                    L(f"       {info['attrs']}")
                except Exception as e:
                    L(f"  #{i} 读取出错: {str(e)[:60]}")

            L(f"\n--- 「创建」按钮 ---")
            for name in ("创建", "Create"):
                b = page.get_by_role("button", name=name, exact=True)
                L(f"  role=button name={name!r}: {b.count()} 个")
                for i in range(min(b.count(), 5)):
                    try:
                        if b.nth(i).is_visible():
                            box = b.nth(i).bounding_box()
                            L(f"     #{i} 可见 at ({round(box['x'])},{round(box['y'])})")
                    except Exception:
                        pass
                t = page.get_by_text(name, exact=True)
                L(f"  文字 {name!r}: {t.count()} 个")

            L(f"\n--- 表格行候选（定位器）---")
            for css in ('[data-testid*="table"] tr', 'tr', '[role="row"]',
                        '[class*="tableRow"]', '[class*="table-row"]'):
                c = page.locator(css)
                vis = 0
                for i in range(min(c.count(), 30)):
                    try:
                        if c.nth(i).is_visible():
                            vis += 1
                    except Exception:
                        pass
                L(f"  {css!r}: 共 {c.count()} 个，可见 {vis} 个")

        except Exception:
            import traceback
            L("出错:")
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR / "drama_list2.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_list2.txt'}")
            context.close()


if __name__ == "__main__":
    main()
