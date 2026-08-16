"""把账户界面语言切成中文。

整套代码都靠中文文案定位元素，界面一变英文，几十处匹配同时失效，所以这是短剧
流程能不能跑的前提。

定位方式来自实测：/i18n/home 右上角有一个语言按钮
    <div class="ac-lang-avater__lang-btn">English</div>
它显示的是【当前语言】，所以不能按文字找（中文时写「中文（简体）」、英文时写
"English"），要按 class 找。这是上一版失败的原因——那版只找「中文（简体）」，而
那时按钮已经变成 "English" 了。

已经排除的其他办法（都无效，别再浪费时间试）：
  * URL 参数 lang / language / locale / hl 共 6 种
  * Ads Manager 里的账号菜单、应用切换器、帮助入口
  * 重载重试（英文稳定之后就不管用了）

用法：
    venv/bin/python3 -m src.drama.set_language [广告主ID]
"""

import sys

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

HOME = "https://ads.tiktok.com/i18n/home"
LANG_BTN_CSS = ".ac-lang-avater__lang-btn"

# 中文选项在下拉里可能的写法
ZH_LABELS = ["中文（简体）", "中文(简体)", "简体中文", "中文", "Chinese (Simplified)"]


def _lang_button_text(page):
    loc = page.locator(LANG_BTN_CSS)
    for i in range(min(loc.count(), 4)):
        try:
            if loc.nth(i).is_visible():
                return loc.nth(i).inner_text().strip()
        except Exception:
            continue
    return None


def switch_to_chinese(page, verbose=True):
    """把语言切成中文。已经是中文则不动。返回 True 表示最终是中文。"""
    def say(s):
        if verbose:
            print(s, flush=True)

    page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(4000)

    cur = _lang_button_text(page)
    say(f"当前语言按钮显示: {cur!r}")
    if cur and any(z in cur for z in ("中文", "简体")):
        say("已经是中文，不用切。")
        return True

    btn = None
    loc = page.locator(LANG_BTN_CSS)
    for i in range(min(loc.count(), 4)):
        try:
            if loc.nth(i).is_visible():
                btn = loc.nth(i)
                break
        except Exception:
            continue
    if not btn:
        say(f"没找到语言按钮（{LANG_BTN_CSS}）。请手动在页面右上角切换。")
        return False

    btn.click(timeout=8000)
    page.wait_for_timeout(2500)
    page.screenshot(path=str(LOGS_DIR / "drama_lang_dropdown.png"))

    # 下拉里挑中文
    for label in ZH_LABELS:
        opt = page.get_by_text(label, exact=True)
        for i in range(min(opt.count(), 6)):
            try:
                if not opt.nth(i).is_visible():
                    continue
                opt.nth(i).click(timeout=6000)
                say(f"点了 {label!r}")
                page.wait_for_timeout(5000)
                page.goto(HOME, wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(4000)
                now = _lang_button_text(page)
                say(f"切换后语言按钮显示: {now!r}")
                ok = bool(now and any(z in now for z in ("中文", "简体")))
                page.screenshot(path=str(LOGS_DIR / "drama_lang_result.png"))
                return ok
            except Exception as e:
                say(f"点 {label!r} 失败: {str(e)[:60]}")

    # 没匹配到就把下拉里有什么打出来，方便补 ZH_LABELS
    items = page.evaluate("""() => {
      const out = [];
      for (const el of document.querySelectorAll('*')) {
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        const t = Array.from(el.childNodes).filter(n=>n.nodeType===3)
          .map(n=>n.textContent.trim()).join('').trim();
        if (t && t.length <= 24) out.push(t);
      }
      return [...new Set(out)].slice(0, 50);
    }""")
    say(f"下拉展开后看到的文字（没匹配到中文选项）: {items}")
    return False


def main():
    adv = sys.argv[1] if len(sys.argv) > 1 else None
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False, locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        try:
            ok = switch_to_chinese(page)
            print(("✓ 语言已是中文" if ok else "✗ 没能切成中文，请看截图手动处理"),
                  flush=True)

            if ok and adv:
                from src.drama.pages.campaign_page import _ui_language
                page.goto(f"https://ads.tiktok.com/i18n/dashboard?aadvid={adv}",
                          wait_until="domcontentloaded", timeout=60000)
                page.wait_for_timeout(7000)
                lang = _ui_language(page)
                print(f"Ads Manager 界面语言: {lang}  "
                      + ("✓ 可以跑了" if lang == "zh" else "✗ 仍是英文"), flush=True)
                page.screenshot(path=str(LOGS_DIR / "drama_lang_adsmanager.png"))
        finally:
            context.close()


if __name__ == "__main__":
    main()
