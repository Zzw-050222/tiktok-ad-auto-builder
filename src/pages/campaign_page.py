def start_new_campaign(page, advertiser_id: str):
    page.goto(
        f"https://ads.tiktok.com/i18n/dashboard?aadvid={advertiser_id}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    create_btn = page.get_by_role("button", name="创建广告")
    create_btn.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(500)
    create_btn.click(timeout=10000)
    # some accounts have a hover-preview panel that duplicates this label, same
    # issue as the "TikTok 即时增长" objective text - .first avoids strict mode
    page.get_by_text("推广目标", exact=True).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(500)


def select_native_growth_objective(page):
    from src.pages.common import wait_until

    radio_text = page.get_by_text("TikTok 即时增长", exact=True).first
    radio_text.wait_for(state="visible", timeout=15000)

    def details_visible():
        loc = page.get_by_text("推广系列详情", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    for attempt in range(5):
        radio_text.click(timeout=10000)
        if wait_until(page, details_visible, timeout_seconds=12):
            break
        if attempt == 4:
            raise TimeoutError("选完'TikTok 即时增长'后一直没看到'推广系列详情'")
    page.wait_for_timeout(500)


def _input_after_label(page, label_text: str):
    return page.locator(
        f"xpath=//*[normalize-space(text())='{label_text}']/following::input[1]"
    )


def fill_campaign_details(page, campaign_name: str, daily_budget):
    """Fills campaign name always. Budget is only set here if this account's
    campaign-creation flow actually has a budget section at this level - a
    significant minority of accounts move budget down to the ad-group level
    instead (confirmed live: no 预算策略/推算系列预算 section here at all, just
    name + split-test toggle + PO number). Returns True if budget was set here,
    False if this account needs it filled at the ad-group level instead
    (see adgroup_page.fill_adgroup_budget_if_present).
    """
    from src.pages.common import wait_until

    name_input = _input_after_label(page, "推广系列名称")
    name_input.wait_for(state="visible", timeout=15000)
    name_input.fill("")
    name_input.fill(campaign_name)

    # don't wait the full 60s here - if it's genuinely absent for this account
    # type, waiting longer never helps; ~10s (per live-confirmed behavior) is
    # enough to tell "still loading" apart from "just isn't here"
    def budget_radio_visible():
        loc = page.get_by_text("推广系列预算", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    budget_radio = wait_until(page, budget_radio_visible, timeout_seconds=10)
    if not budget_radio:
        page.wait_for_timeout(500)
        return False

    budget_radio.first.click(timeout=10000)
    page.wait_for_timeout(300)

    budget_input = page.get_by_placeholder("20.00 以上")
    budget_input.wait_for(state="visible", timeout=15000)
    budget_input.fill(str(daily_budget))
    page.wait_for_timeout(500)
    return True


def add_new_ad_group(page, campaign_name: str):
    """Click the campaign row's '+' icon in the left sidebar to add a fresh, blank
    ad group to the campaign (distinct from duplicating an existing one - use this
    when a new row has genuinely different data, not a repeat of the last row's).
    """
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    row = page.locator('[data-testid="creation_1nn_sidebar_campaign_node"]').filter(
        has_text=campaign_name
    )
    row.first.scroll_into_view_if_needed(timeout=10000)

    plus_icon = row.first.locator("ks-icon-plus-small")
    for attempt in range(3):
        row.first.hover(timeout=10000)
        page.wait_for_timeout(400)
        try:
            plus_icon.click(timeout=5000, force=True)
        except Exception:
            pass
        page.wait_for_timeout(800)
        # a new ad group node should now exist in the sidebar; give it a moment
        break
    page.wait_for_timeout(1000)


def continue_step(page):
    btn = page.get_by_role("button", name="继续", exact=True)
    btn.wait_for(state="visible", timeout=15000)
    btn.click(timeout=10000)
    page.wait_for_timeout(3000)
