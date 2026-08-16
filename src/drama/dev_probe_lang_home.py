"""最后一条自动切语言的路：动 /i18n/home 右上角那个语言控件。

已经排除的：
  * URL 参数（lang / language / locale / hl 共 6 种）—— 全部无效
  * Ads Manager 里的账号菜单、应用切换器、帮助 —— 没有语言入口
  * 重载重试 —— 曾经有效，现在英文已经稳定（连续 4 次）

/i18n/home 右上角显示的是「中文（简体）」，也就是账户级设置本来就是中文，但
Ads Manager 渲染英文。重新选一次同一个语言，也许能把卡住的状态刷新掉。

本探针：dump 那个控件的结构 -> 点开 -> 看有哪些语言选项 -> 选中文 -> 回 Ads
Manager 验证是否变中文。

用法：
    venv/bin/python3 -m src.drama.dev_probe_lang_home <广告主ID>
"""

import sys
import traceback

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.pages.campaign_page import _ui_language

REPORT = []
HOME = "https://ads.tiktok.com/i18n/home"


def L(s=""):
    REPORT.append(s)
    print(s, flush=True)


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
            page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(5000)

            L(f"{'=' * 68}\n① 找右上角的语言控件\n{'=' * 68}")
            # 语言控件通常显示当前语言名，且位于页面右上角
            info = page.evaluate("""() => {
              const out = [];
              for (const el of document.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                if (r.y > 120) continue;              // 只看顶部
                const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
                  .map(n=>n.textContent.trim()).join('').trim();
                if (!t || t.length > 20) continue;
                out.push({t, x: Math.round(r.x), y: Math.round(r.y),
                          tag: el.tagName.toLowerCase(),
                          cls: (el.className||'').toString().slice(0,36)});
              }
              return out.slice(0, 30);
            }""")
            for it in info:
                L(f"  ({it['x']:>4},{it['y']:>3}) <{it['tag']}> {it['t']!r} cls={it['cls']!r}")

            L(f"\n{'=' * 68}\n② 点开语言控件\n{'=' * 68}")
            opened = False
            for label in ["中文（简体）", "中文(简体)", "简体中文", "中文"]:
                loc = page.get_by_text(label, exact=True)
                for i in range(min(loc.count(), 4)):
                    try:
                        if not loc.nth(i).is_visible():
                            continue
                        loc.nth(i).click(timeout=6000)
                        opened = True
                        L(f"  点了 {label!r}")
                        page.wait_for_timeout(2500)
                        break
                    except Exception as e:
                        L(f"  点 {label!r} 失败: {str(e)[:50]}")
                if opened:
                    break

            if opened:
                opts = page.evaluate("""() => {
                  const out = [];
                  for (const el of document.querySelectorAll('*')) {
                    const r = el.getBoundingClientRect();
                    if (r.width <= 0 || r.height <= 0) continue;
                    const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
                      .map(n=>n.textContent.trim()).join('').trim();
                    if (t && t.length <= 20 && r.y > 30)
                      out.push({t, x: Math.round(r.x), y: Math.round(r.y)});
                  }
                  return [...new Map(out.map(o=>[o.t,o])).values()].slice(0, 40);
                }""")
                langish = [o for o in opts if any(
                    k in o["t"] for k in ["中文", "English", "简体", "繁體", "日本", "한국"])]
                L(f"  展开后看到的语言选项: {[o['t'] for o in langish]}")
                page.screenshot(path=str(LOGS_DIR / "drama_langhome_open.png"))

                # 重新选一次中文
                for o in langish:
                    if "简体" in o["t"] or o["t"] == "中文":
                        try:
                            page.get_by_text(o["t"], exact=True).first.click(timeout=6000)
                            L(f"  重新选了 {o['t']!r}")
                            page.wait_for_timeout(4000)
                            break
                        except Exception as e:
                            L(f"  选 {o['t']!r} 失败: {str(e)[:50]}")
            else:
                L("  ⚠ 没能点开语言控件")

            L(f"\n{'=' * 68}\n③ 回 Ads Manager 验证\n{'=' * 68}")
            page.goto(f"https://ads.tiktok.com/i18n/dashboard?aadvid={adv}",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(7000)
            lang = _ui_language(page)
            L(f"  当前界面语言: {lang}   {'✓ 成功切回中文' if lang == 'zh' else '✗ 仍是英文'}")
            page.screenshot(path=str(LOGS_DIR / "drama_langhome_after.png"))

        except Exception:
            L("\n出错:")
            L(traceback.format_exc())
        finally:
            with open(str(LOGS_DIR / "drama_lang_home.txt"), "w", encoding="utf-8") as f:
                f.write("\n".join(REPORT))
            print(f"\n报告已写入 {LOGS_DIR / 'drama_lang_home.txt'}")
            context.close()


if __name__ == "__main__":
    main()
