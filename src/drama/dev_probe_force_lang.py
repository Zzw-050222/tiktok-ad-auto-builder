"""找一个能把 Ads Manager 强制切成中文的办法。

背景：这个账号的 Ads Manager 现在【稳定】渲染英文（连续 4 次都是），重载重试已经
无效。而账户设置里语言显示的是「中文（简体）」，去那里改没用。

依次试两条路：
  ① URL 参数强制（最省事，若可行就直接用）
  ② 右上角账号菜单 / 左上角应用切换器里有没有语言入口，dump 出来看

用法：
    venv/bin/python3 -m src.drama.dev_probe_force_lang <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import _ui_language

REPORT = []

# 试这些 URL 参数，看哪个能让界面变中文
LANG_PARAMS = [
    "lang=zh",
    "lang=zh-Hans",
    "lang=zh-CN",
    "language=zh",
    "locale=zh-CN",
    "hl=zh-CN",
]


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    adv = sys.argv[1]
    base = f"https://ads.tiktok.com/i18n/dashboard?aadvid={adv}"

    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()

        try:
            L(f"{'=' * 68}\n① 试 URL 参数强制语言\n{'=' * 68}")
            L(f"  基准（不带参数）:")
            page.goto(base, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(6000)
            L(f"    -> {_ui_language(page)}")

            winner = None
            for param in LANG_PARAMS:
                url = f"{base}&{param}"
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=60000)
                    page.wait_for_timeout(6000)
                    lang = _ui_language(page)
                    L(f"  {param:<16} -> {lang}")
                    if lang == "zh" and not winner:
                        winner = param
                        L(f"    ★ 这个参数有效")
                except Exception as e:
                    L(f"  {param:<16} -> 出错 {str(e)[:50]}")

            if winner:
                L(f"\n  结论：加上 &{winner} 就能强制中文，直接用它。")
                page.screenshot(path=str(LOGS_DIR / "drama_lang_forced.png"))
            else:
                L("\n  结论：URL 参数都没用，看看菜单里有没有语言入口。")

                L(f"\n{'=' * 68}\n② dump 右上角账号菜单 / 左上角应用切换器\n{'=' * 68}")
                page.goto(base, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(5000)

                for desc, sel in [
                    ("右上角账号名下拉", '[class*="account"], [data-testid*="account"]'),
                    ("左上角应用切换器", '[class*="app-switch"], [class*="grid"]'),
                    ("帮助/问号", '[class*="help"]'),
                ]:
                    loc = page.locator(sel)
                    L(f"\n  {desc}: 命中 {loc.count()}")
                    for i in range(min(loc.count(), 3)):
                        try:
                            if not loc.nth(i).is_visible():
                                continue
                            loc.nth(i).click(timeout=5000)
                            page.wait_for_timeout(2000)
                            items = page.evaluate("""() => {
                              const out = [];
                              for (const el of document.querySelectorAll('*')) {
                                const r = el.getBoundingClientRect();
                                if (r.width <= 0 || r.height <= 0) continue;
                                const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
                                  .map(n=>n.textContent.trim()).join('').trim();
                                if (t && t.length < 24) out.push(t);
                              }
                              return [...new Set(out)].slice(0, 60);
                            }""")
                            langish = [t for t in items if any(
                                k in t.lower() for k in
                                ["lang", "语言", "中文", "english", "简体", "chinese"])]
                            L(f"    [{i}] 点开后，含语言字样的项: {langish}")
                            if langish:
                                page.screenshot(
                                    path=str(LOGS_DIR / f"drama_lang_menu_{i}.png"))
                            page.keyboard.press("Escape")
                            page.wait_for_timeout(800)
                        except Exception as e:
                            L(f"    [{i}] 出错 {str(e)[:60]}")

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR / "drama_force_lang.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_force_lang.txt'}")
            context.close()


if __name__ == "__main__":
    main()
