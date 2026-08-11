import time

from playwright.sync_api import sync_playwright

from src.config import (
    ACCEPT_LANGUAGE,
    ADS_MANAGER_DASHBOARD_URL,
    BROWSER_PROFILE_DIR,
    LOCALE,
    LOGS_DIR,
)


def main():
    with sync_playwright() as p:
        context = p.chromium.launch_persistent_context(
            user_data_dir=str(BROWSER_PROFILE_DIR),
            headless=False,
            locale=LOCALE,
            extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
            viewport={"width": 1600, "height": 1000},
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto(ADS_MANAGER_DASHBOARD_URL)

        print("请在打开的浏览器窗口中登录 Business Center...", flush=True)

        deadline = time.time() + 600
        logged_in = False
        while time.time() < deadline:
            url = page.url
            if "/i18n/dashboard" in url:
                logged_in = True
                break
            time.sleep(2)

        screenshot_path = LOGS_DIR / "login_check.png"
        page.wait_for_timeout(1000)
        page.screenshot(path=str(screenshot_path))

        if logged_in:
            print(f"检测到已登录，当前地址: {page.url}")
        else:
            print("等待超时，仍未检测到登录成功，请检查截图。")
        print(f"截图已保存到: {screenshot_path}")

        context.close()


if __name__ == "__main__":
    main()
