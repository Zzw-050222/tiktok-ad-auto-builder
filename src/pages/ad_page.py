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


def select_creative_materials(page, search_term: str, count: int, skip: int = 0):
    """Manually pick `count` materials from the account's creative-material
    library (instead of leaving TikTok's default "自动选择"/auto-select
    behavior in place), searching by `search_term`. `skip` lets multiple
    campaigns targeting the same mini game on the same account pick different
    materials instead of all reusing the same first N results - caller is
    responsible for tracking how many have already been used per
    (advertiser_id, tt_mini_id) within a run.
    Returns how many were actually selected - may be less than `count` if the
    search runs out of results even after scrolling to the end (that's fine,
    not an error - caller should just proceed with however many got picked).
    """
    from src.pages.common import dismiss_popups, robust_click, wait_until

    dismiss_popups(page)

    # the "自动选择" box can take a while to finish generating
    def not_loading():
        loc = page.get_by_text("正在加载中", exact=False)
        return True if loc.count() == 0 else None

    wait_until(page, not_loading, timeout_seconds=60)
    page.wait_for_timeout(500)

    auto_select_box = page.get_by_text("自动选择", exact=True)
    auto_select_box.first.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, auto_select_box.first, timeout=5000)
    page.wait_for_timeout(1500)

    # the TOP-LEVEL "+ 添加创意素材" button - NOT the nested "+ 添加内容"
    # under "你的自有内容" (that path was confirmed inconsistent across
    # accounts, this one is not)
    top_add_btn = page.get_by_role("button", name="添加创意素材", exact=True)
    top_add_btn.first.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, top_add_btn.first, timeout=5000)
    page.wait_for_timeout(1200)

    # switch to the "创意素材库" tab - a plain text match is ambiguous (an
    # info banner sentence also contains this exact substring and can
    # trigger a spurious "退出此页面" dialog instead of switching tabs), so
    # match the actual tab element via its stable class name instead
    lib_tab = page.locator(".tab-item-text", has_text="创意素材库")
    robust_click(page, lib_tab.first, timeout=5000)
    page.wait_for_timeout(1000)

    search_box = page.get_by_placeholder("按名称或ID搜索")
    search_box.first.click(timeout=5000)
    page.keyboard.type(search_term)

    # scope everything below to this tab's own container (derived from the
    # search box's own ancestor, not a page-wide `.first` on the container's
    # selector - its data-testid has a random suffix that can shift which
    # element `.first` resolves to after searching). The hidden "TikTok 帖子"
    # tab's DOM otherwise pollutes page-wide text/role matches for tiles and
    # checkboxes (confirmed live: nearly doubled tile counts, matched an
    # unrelated "已选择 2 个 TikTok 账号" filter instead of the real counter).
    lib_pane = search_box.first.locator(
        "xpath=ancestor::div[starts-with(@data-testid, 'tab-library-')][1]"
    )
    tiles = lib_pane.locator(r"text=/^\d{2}:\d{2}$/")

    # results flicker while settling (appear, clear, reload) - require the
    # SAME non-zero count across 3 consecutive checks, not just "count > 0
    # once", or a transient empty/partial state gets mistaken for "ready"
    stable_hits, last_count = 0, -1
    for _ in range(120):  # up to ~60s
        c = tiles.count()
        if c > 0 and c == last_count:
            stable_hits += 1
            if stable_hits >= 3:
                break
        else:
            stable_hits = 0
        last_count = c
        page.wait_for_timeout(500)

    # the real checkbox is a `role="checkbox"` <label> wrapping a visually
    # hidden native <input> - matching the native input directly finds
    # nothing, since it's never Playwright-"visible"
    checkboxes = lib_pane.get_by_role("checkbox")

    selected = 0
    target_end = skip + count
    idx = skip
    stable_rounds = 0
    for _ in range(200):
        cur_total = checkboxes.count()
        while idx < min(cur_total, target_end):
            checkboxes.nth(idx).scroll_into_view_if_needed(timeout=5000)
            robust_click(page, checkboxes.nth(idx), timeout=5000)
            page.wait_for_timeout(250)
            idx += 1
            selected += 1
        if selected >= count:
            break

        # need more than what's loaded - scroll down anchored on a real
        # visible tile (never a hardcoded coordinate - a hardcoded position
        # can miss the panel entirely and scroll the underlying page instead)
        anchor = tiles.last
        box = anchor.bounding_box()
        if not box:
            break
        page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        page.mouse.wheel(0, 400)
        page.wait_for_timeout(700)

        new_total = checkboxes.count()
        if new_total == cur_total:
            stable_rounds += 1
            if stable_rounds >= 4:
                break  # reached the true end - genuinely not enough material
        else:
            stable_rounds = 0

    confirm_btn = page.get_by_role("button", name="添加创意素材", exact=True)
    robust_click(page, confirm_btn.first, timeout=10000)
    page.wait_for_timeout(1500)

    save_btn = page.get_by_role("button", name="保存", exact=True)
    robust_click(page, save_btn.first, timeout=10000)
    page.wait_for_timeout(2000)

    return selected


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
