"""短剧账号的首次登录 —— 存进独立的 browser_profile_drama/，不影响小游戏那份。

用法（项目根目录）：
    venv/bin/python3 -m src.drama.login_setup

会打开一个浏览器窗口，像平时一样登录【你自己的 BC 账号】（扫码或密码）。检测到
后台真正加载出来就算成功，窗口自动关闭；之后短剧这套脚本都不用再登。

网页版里也有同样的功能（【登录 / 换账号】按钮），不想开终端的话用那个。

换账号：先 `POST /account/logout`（网页上的「退出登录」），或者手动把
browser_profile_drama/ 挪走，再跑这个脚本。直接在浏览器里切账号不可靠——
残留 cookie 经常会把人自动登回旧账号。

和 src/login_setup.py 的区别：profile 目录不同。短剧广告主通常属于另一个
Business Center，和小游戏共用一个 profile 会互相顶掉登录态。

登录判定放在 src/account.py 的 wait_for_login 里（中英文都认）。那里记着一个坑：
不能靠「URL 里有没有 /i18n/dashboard」判断登录——2026-08-16 实测未登录时 TikTok
【不跳转】，就在那个地址上渲染一个空壳，于是判断在人还没开始登录时就成立了，
表现是窗口一闪就没。
"""

from playwright.sync_api import sync_playwright

from src.account import wait_for_login
from src.config import ACCEPT_LANGUAGE, LOCALE, LOGS_DIR
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR


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

        print("=" * 60, flush=True)
        print("请在打开的浏览器窗口里登录你自己的 BC 账号（扫码或密码都行）。", flush=True)
        print(f"登录态会存到 {DRAMA_BROWSER_PROFILE_DIR.name}/，与小游戏那份互不影响。", flush=True)
        print("登录成功后窗口会自动关闭，最多等 10 分钟。", flush=True)
        print("=" * 60, flush=True)

        # 判断标志挪到 src/account.py 了，那边中英文都认 ——
        # 这里原来只认「创建广告」「推广系列」，别人的账号一上来是英文界面就永远等不到。
        found = wait_for_login(
            page,
            timeout_seconds=600,
            on_progress=lambda waited, url: print(
                f"  ...已等待 {waited} 秒，仍在等你登录（当前地址 {url[:70]}）", flush=True
            ),
        )

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
