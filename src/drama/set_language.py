"""把短剧账号的后台界面切回中文。

为什么需要它：整套代码都靠中文文案定位元素（「创建广告」「继续」「广告组名称」…），
而 TikTok 的界面语言是【账号级的服务端设置】，不受浏览器 locale 控制，而且会变。
2026-08-16 实测：短剧账号前几轮还是中文，后来变成了英文（Create ad / Dashboard /
Campaigns），于是 get_by_role("button", name="创建广告") 直接超时。

和 src/dev_set_language.py 的区别：用短剧那个 profile，并且切换后会【验证】确实
变成中文了，而不是切完就当成功。

用法：
    venv/bin/python3 -m src.drama.set_language
"""

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

HOME_URL = "https://ads.tiktok.com/i18n/home"

# 切换成功的判据：后台出现这些中文之一
ZH_MARKERS = ["创建广告", "推广系列", "概览"]


def _is_chinese(page):
    for m in ZH_MARKERS:
        try:
            loc = page.get_by_text(m, exact=True)
            for i in range(min(loc.count(), 6)):
                if loc.nth(i).is_visible():
                    return m
        except Exception:
            pass
    return None


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(DRAMA_BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        already = _is_chinese(page)
        if already:
            print(f"界面已经是中文（检测到「{already}」），不用切换。")
            page.screenshot(path=str(LOGS_DIR / "drama_lang_already_zh.png"))
            context.close()
            return

        print("界面不是中文，尝试切换...")
        switched = False
        # 语言入口通常显示当前语言名；英文界面下就是 "English"
        for label in ["English", "语言", "Language"]:
            loc = page.get_by_text(label, exact=True)
            for i in range(min(loc.count(), 6)):
                try:
                    if not loc.nth(i).is_visible():
                        continue
                    loc.nth(i).click(timeout=5000)
                    page.wait_for_timeout(1500)
                    sel = page.locator("select")
                    if sel.count():
                        sel.first.select_option(value="zh", force=True, timeout=5000)
                        switched = True
                        print(f"  通过「{label}」入口切换了语言")
                        page.wait_for_timeout(4000)
                        break
                except Exception as e:
                    print(f"  入口「{label}」第 {i} 个失败: {e}")
            if switched:
                break

        if not switched:
            print("没找到语言切换入口。请手动在后台右上角把语言改成中文，再重跑。")

        page.wait_for_timeout(2000)
        page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        now = _is_chinese(page)
        page.screenshot(path=str(LOGS_DIR / "drama_lang_after.png"))
        if now:
            print(f"✓ 已切换成中文（检测到「{now}」）")
        else:
            print("✗ 切换后仍未检测到中文，请看截图 logs/drama_lang_after.png")

        context.close()


if __name__ == "__main__":
    main()
