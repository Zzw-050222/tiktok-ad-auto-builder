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

    def details_visible():
        loc = page.get_by_text("推广系列详情", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    def visible_radio():
        # 沿用 exact=True 的字符串匹配——它是实测能命中的，不要换成正则。
        # 唯一的改动是【不再盲取 .first】：本函数原有的注释就写了「有账号存在悬浮
        # 预览面板复制了这个标签」，一旦 .first 恰好是那个隐藏副本，就会死等到超时，
        # 而页面上明明有一个可见的。遍历所有匹配挑出真正可见的那一个。
        loc = page.get_by_text("TikTok 即时增长", exact=True)
        for i in range(min(loc.count(), 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    # 15 秒 -> 60 秒：这个平台会卡到接近一分钟（见 common.wait_until 的注释），
    # 项目里别处早就统一成 60 秒了，这里是漏网的一处。
    #
    # 注意这里【刻意不调用 dismiss_popups】：它会点击任何可见的「关闭」按钮，而在
    # 推广目标这一页上「关闭」是关掉整个创建面板的，一点就把要选的内容关没了
    # （2026-08-14 亲手踩过）。也刻意用普通 .click() 而不是 robust_click：单选项要的
    # 是真实点击，robust_click 会升级到 JS 直接派发，对单选项不如真实点击可靠。
    for attempt in range(5):
        radio = wait_until(page, visible_radio,
                           timeout_seconds=60 if attempt == 0 else 20)
        if not radio:
            raise TimeoutError("等了 60 秒还没看到可见的「TikTok 即时增长」推广目标")
        radio.click(timeout=10000)
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

    # 15 秒 -> 60 秒：与项目里其它地方统一（见 common.wait_until 的注释，这个平台
    # 会卡到接近一分钟）。注意下面 budget_radio_visible 的 10 秒是【刻意】的短超时，
    # 用来区分「这个账号类型压根没有预算区」和「还在加载」，别跟着一起改。
    name_input = _input_after_label(page, "推广系列名称")
    name_input.wait_for(state="visible", timeout=60000)
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
    budget_input.wait_for(state="visible", timeout=60000)
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
    # 15 秒 -> 60 秒：同上，与项目里其它地方统一
    btn = page.get_by_role("button", name="继续", exact=True)
    btn.wait_for(state="visible", timeout=60000)
    btn.click(timeout=10000)
    page.wait_for_timeout(3000)
