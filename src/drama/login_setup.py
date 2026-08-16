"""短剧账号的首次登录 —— 存进独立的 browser_profile_drama/，不影响小游戏那份。

用法（项目根目录）：
    venv/bin/python3 -m src.drama.login_setup

会打开一个浏览器窗口，像平时一样登录【短剧】账号（扫码或密码）。检测到后台
真正加载出来就算成功，窗口自动关闭；之后短剧这套脚本都不用再登。

和 src/login_setup.py 有两点不同：
  * profile 目录不同 —— 短剧广告主属于另一个 Business Center，共用一个 profile
    会互相顶掉登录态。
  * 登录检测方式不同 —— 不能靠「URL 里有没有 /i18n/dashboard」来判断。2026-08-16
    实测：未登录时 TikTok【不跳转】，就在 /i18n/dashboard 这个地址上渲染一个空壳
    （标题和正文都是空的）。而脚本第一步就是 goto 到这个地址，于是那个判断在用户
    还没开始登录时就已经成立，脚本立刻认为「已登录」并关掉窗口——表现就是窗口一闪
    就没了。改成等后台里真实存在的元素出现。
"""

import time

from playwright.sync_api import sync_playwright

from src.config import ACCEPT_LANGUAGE, ADS_MANAGER_LOGIN_URL, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR

# 只有真正进了后台才会同时出现的东西，用它们判断登录成功
LOGGED_IN_MARKERS = ["创建广告", "推广系列"]


def _looks_logged_in(page):
    for marker in LOGGED_IN_MARKERS:
        try:
            loc = page.get_by_text(marker, exact=True)
            for i in range(min(loc.count(), 6)):
                if loc.nth(i).is_visible():
                    return marker
        except Exception:
            pass
    try:
        btn = page.get_by_role("button", name="创建广告")
        if btn.count() > 0 and btn.first.is_visible():
            return "创建广告按钮"
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
        page.goto(ADS_MANAGER_LOGIN_URL, wait_until="domcontentloaded", timeout=60000)

        print("=" * 60, flush=True)
        print("请在打开的浏览器窗口里登录【短剧】账号（扫码或密码都行）。", flush=True)
        print(f"登录态会存到 {DRAMA_BROWSER_PROFILE_DIR.name}/，与小游戏那份互不影响。", flush=True)
        print("登录成功后窗口会自动关闭，最多等 10 分钟。", flush=True)
        print("=" * 60, flush=True)

        deadline = time.time() + 600
        found = None
        last_report = 0
        while time.time() < deadline:
            found = _looks_logged_in(page)
            if found:
                break
            waited = int(time.time() - (deadline - 600))
            if waited - last_report >= 30:
                last_report = waited
                print(f"  ...已等待 {waited} 秒，仍在等你登录（当前地址 {page.url[:70]}）",
                      flush=True)
            time.sleep(2)

        page.wait_for_timeout(1500)
        screenshot_path = LOGS_DIR / "drama_login_check.png"
        try:
            page.screenshot(path=str(screenshot_path))
        except Exception:
            pass

        if found:
            print(f"\n✓ 登录成功（检测到「{found}」），当前地址: {page.url}", flush=True)
            print("短剧的登录态已保存，接下来的短剧脚本不用再登。", flush=True)
        else:
            print("\n✗ 等了 10 分钟仍未检测到登录成功。", flush=True)
            print(f"  请看截图确认卡在哪一步: {screenshot_path}", flush=True)

        context.close()


if __name__ == "__main__":
    main()
