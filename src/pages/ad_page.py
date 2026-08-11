def wait_ad_page_ready(page):
    page.get_by_text("创意素材", exact=True).wait_for(state="visible", timeout=90000)
    page.wait_for_timeout(1000)


def select_identity(page, handle_name: str):
    from src.pages.common import dismiss_popups, robust_click, wait_until

    dismiss_popups(page)

    dropdown = page.locator('[data-testid="components-IdentityListComponent-szvjSS"]')
    dropdown.scroll_into_view_if_needed(timeout=15000)
    dropdown.click(timeout=10000)
    page.wait_for_timeout(800)

    # only a handful of identities are shared to this account - no need to search,
    # just click the matching one directly from the list that's already shown.
    # The list can take a while to render, so wait (up to a minute) for a VISIBLE
    # match before concluding it's genuinely absent.
    def visible_match():
        candidates = page.get_by_text(handle_name, exact=False)
        for i in range(candidates.count()):
            c = candidates.nth(i)
            if c.is_visible():
                return c
        return None

    result = wait_until(page, visible_match, timeout_seconds=60)
    if not result:
        raise ValueError(f"身份 '{handle_name}' 不在当前广告账户可选的身份列表里")

    result.scroll_into_view_if_needed(timeout=5000)
    robust_click(page, result, timeout=5000)
    page.wait_for_timeout(500)


def fill_ad_copy(page, ads_text: str):
    from src.pages.common import wait_until

    def label_visible():
        loc = page.get_by_text("文案 (0/5)", exact=False)
        if loc.count() == 0:
            loc = page.get_by_text("文案", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    label = wait_until(page, label_visible, timeout_seconds=60)
    if not label:
        raise ValueError("一直没找到'文案'区域")
    label.first.scroll_into_view_if_needed(timeout=10000)

    def input_ready():
        loc = page.get_by_placeholder("输入文案")
        if loc.count() == 0:
            loc = page.locator(
                "xpath=//*[contains(normalize-space(text()),'文案')]/following::textarea[1]"
            )
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    input_box = wait_until(page, input_ready, timeout_seconds=60)
    if not input_box:
        raise ValueError("一直没找到文案输入框")
    input_box.first.click(timeout=10000)
    input_box.first.fill(ads_text)
    page.wait_for_timeout(500)


def fill_landing_url(page, url: str):
    from src.pages.common import wait_until

    def field_visible():
        loc = page.get_by_placeholder("https://www.tiktok.com/minis/")
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    field = wait_until(page, field_visible, timeout_seconds=60)
    if not field:
        raise ValueError("一直没找到落地页链接输入框")
    field.first.scroll_into_view_if_needed(timeout=10000)
    field.first.fill("")
    field.first.fill(url)
    page.wait_for_timeout(500)
