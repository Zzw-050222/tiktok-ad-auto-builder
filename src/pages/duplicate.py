def _open_duplicate_modal(page, ad_group_name: str, count: int):
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    row = page.locator('[data-testid="creation_1nn_sidebar_adgroup_node"]').filter(
        has_text=ad_group_name
    )
    row.first.scroll_into_view_if_needed(timeout=10000)

    dup_icon = row.first.locator("ks-icon-copy-content")
    count_input = page.locator(
        "xpath=//*[normalize-space(text())='副本数量']/following::input[1]"
    )

    for attempt in range(3):
        row.first.hover(timeout=10000)
        page.wait_for_timeout(400)
        try:
            dup_icon.click(timeout=5000, force=True)
        except Exception:
            pass
        try:
            count_input.wait_for(state="visible", timeout=5000)
            break
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)

    count_input.fill("")
    count_input.fill(str(count))
    page.wait_for_timeout(800)


def duplicate_ad_group(page, ad_group_name: str, new_names: list):
    """Given the CURRENT (source) ad group's name as shown in the left sidebar,
    hover its row, click the duplicate icon, set copy count + custom names in the
    modal, and confirm. Use this when the copies need specific names. After this,
    each new ad group inherits all of the source's settings - caller is responsible
    for opening each copy and overwriting the row-specific fields if they should
    differ from the source.
    """
    count = len(new_names)
    _open_duplicate_modal(page, ad_group_name, count)

    name_inputs = page.locator(
        "xpath=//*[normalize-space(text())='广告组名称：']/following::input"
    )
    n = name_inputs.count()
    for i in range(min(n, count)):
        name_inputs.nth(i).fill("")
        name_inputs.nth(i).fill(new_names[i])
        page.wait_for_timeout(200)

    page.get_by_role("button", name="复制", exact=True).click(timeout=10000)
    page.wait_for_timeout(2500)


def duplicate_ad_group_n_times(page, ad_group_name: str, count: int):
    """Same as duplicate_ad_group, but leaves the modal's default '...的副本 N'
    naming untouched. Use this for identical repeats of one row's own ad group
    (Excel 'Ad Group Name Number' column) - these are meant to be exact copies,
    not distinct rows, so there's no need to open and re-fill each one afterward.
    """
    _open_duplicate_modal(page, ad_group_name, count)
    page.get_by_role("button", name="复制", exact=True).click(timeout=10000)
    page.wait_for_timeout(2500)


def duplicate_ad_n_times(page, count: int):
    """For the minority account type that has no '复制广告组' at all (same
    accounts that have no budget section at campaign level - see
    campaign_page.fill_campaign_details's return value) - duplicates the
    CURRENTLY OPEN ad itself, `count` extra times, within the same ad group.
    Unlike duplicate_ad_group*, this modal has no per-copy name fields at all
    (ad names aren't a customer-facing concept here), just a copy-count stepper.
    """
    from src.pages.common import dismiss_popups, robust_click

    dismiss_popups(page)

    # TikTok's internal term for "ad" here is "creative" (matches the ad-level
    # URL path .../create/spc-creative too) - confirmed live, NOT
    # "..._ad_node" (that guess matched zero elements)
    row = page.locator('[data-testid="creation_1nn_sidebar_creative_node"]')
    row.first.scroll_into_view_if_needed(timeout=10000)

    dup_icon = row.first.locator("ks-icon-copy-content")
    modal_marker = page.get_by_text("副本数量", exact=True)

    for attempt in range(3):
        row.first.hover(timeout=10000)
        page.wait_for_timeout(400)
        try:
            robust_click(page, dup_icon, timeout=5000)
        except Exception:
            pass
        try:
            modal_marker.first.wait_for(state="visible", timeout=5000)
            break
        except Exception:
            if attempt == 2:
                raise
            page.wait_for_timeout(500)

    # avoid xpath's `following::` axis here - it doesn't cross shadow DOM
    # boundaries, which some accounts' components use for this exact modal.
    # A plain CSS/text-based Playwright locator does pierce shadow DOM, so
    # just grab whichever visible number-ish input is showing "1" (the
    # copy-count default) right now.
    count_input = page.locator('input[type="text"]:visible, input[type="number"]:visible')
    target_input = None
    for i in range(count_input.count()):
        try:
            if count_input.nth(i).input_value(timeout=500) == "1":
                target_input = count_input.nth(i)
                break
        except Exception:
            continue
    if target_input is None:
        target_input = count_input.first

    target_input.fill("")
    target_input.fill(str(count))
    page.wait_for_timeout(800)

    page.get_by_role("button", name="复制", exact=True).click(timeout=10000)
    page.wait_for_timeout(2500)


def open_ad_group_by_name(page, ad_group_name: str):
    """Click a specific ad group's row in the left sidebar to open/edit it."""
    row = page.locator('[data-testid="creation_1nn_sidebar_adgroup_node"]').filter(
        has_text=ad_group_name
    )
    row.first.scroll_into_view_if_needed(timeout=10000)
    row.first.click(timeout=10000)
