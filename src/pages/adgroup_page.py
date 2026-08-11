def wait_adgroup_page_ready(page):
    page.get_by_text("广告组名称", exact=True).first.wait_for(state="visible", timeout=90000)
    page.wait_for_timeout(800)


def fill_ad_group_name(page, ad_group_name: str):
    name_input = page.locator('input[type="text"]:visible').first
    name_input.wait_for(state="visible", timeout=15000)
    name_input.fill("")
    name_input.fill(ad_group_name)
    page.wait_for_timeout(300)


def fill_adgroup_budget_if_present(page, daily_budget):
    """Only fills anything for the minority of accounts where budget lives at
    ad-group level instead of campaign level (see campaign_page.fill_campaign_details
    - it returns False when that account has no budget section at campaign
    level, which is the signal to call this). Confirmed live: this section uses
    the exact same placeholder ("20.00 以上") as the campaign-level one, but
    comes pre-filled with a default (e.g. 20.00) that must be overwritten, not
    left as-is. If a normal account's ad-group page has no such section, this
    is a harmless no-op.
    """
    from src.pages.common import wait_until

    def budget_input_ready():
        loc = page.get_by_placeholder("20.00 以上")
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    budget_input = wait_until(page, budget_input_ready, timeout_seconds=10)
    if not budget_input:
        return False

    budget_input.first.fill("")
    budget_input.first.fill(str(daily_budget))
    page.wait_for_timeout(500)
    return True


def select_mini_game(page, mini_game_name: str, tt_mini_id: str):
    """Matches by tt_mini_id ONLY, never by mini_game_name text - confirmed live
    that a name-only match is unsafe: the Excel naming convention often embeds
    the mini game name inside the Campaign Name too (e.g. campaign
    "JP-Puzzle Brain Twist-1-0810-zzw-1" contains mini game "Puzzle Brain
    Twist"), so a page-wide text('搞笑Puzzle Brain Twist') match can land on
    the left sidebar's campaign entry instead of an actual row in this list -
    that's exactly the wrong-click bug this was rewritten to avoid.
    """
    from src.pages.common import robust_click, wait_until

    picker = page.get_by_placeholder("选择 TikTok Mini")
    if picker.count() == 0:
        picker = page.get_by_text("选择 TikTok Mini", exact=True)
    picker.first.click(timeout=10000)
    page.wait_for_timeout(800)

    def target_match():
        c = page.locator(f"text=ID: {tt_mini_id}")
        if c.count() == 0:
            c = page.locator(f"text=ID：{tt_mini_id}")
        return c if c.count() > 0 else None

    # Some accounts have a real search that narrows this same list once typed
    # into (the picker field itself is the filter, not a separate search box).
    # Other accounts with many authorized mini games have NO search at all
    # here and typing is a silent no-op - confirmed live on one such account:
    # opening the picker shows a plain scrollable list, no search input
    # anywhere in it.
    page.keyboard.type(mini_game_name)
    match = wait_until(page, target_match, timeout_seconds=15)

    if not match:
        # No-search accounts: scroll the list to bring more rows into view.
        # Anchor the mouse on an ACTUAL VISIBLE row's position (never a
        # hardcoded page coordinate) before wheeling - confirmed live that a
        # hardcoded coordinate can miss the popup entirely and scroll the
        # whole underlying page instead, closing the picker.
        stable_rounds = 0
        prev_signature = None
        for _ in range(45):
            match = target_match()
            if match:
                break

            anchor = page.locator("text=/ID[:：]/").first
            if anchor.count() == 0:
                break
            box = anchor.bounding_box()
            if not box:
                break
            page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.mouse.wheel(0, 350)
            page.wait_for_timeout(700)

            # the visible set of "ID: xxx" rows not changing for several
            # rounds in a row means we've hit the true end of the list (or of
            # whatever's been lazy-loaded so far) - stop instead of spinning.
            signature = tuple(page.locator("text=/ID[:：]/").all_inner_texts())
            if signature == prev_signature:
                stable_rounds += 1
                if stable_rounds >= 6:
                    break
            else:
                stable_rounds = 0
            prev_signature = signature

    if not match:
        raise ValueError(
            f"小游戏 '{mini_game_name}' (ID: {tt_mini_id}) 在列表里一直没找到，滚动到底也没有"
        )

    target = match.first
    target.scroll_into_view_if_needed(timeout=5000)
    robust_click(page, target, timeout=5000)
    page.wait_for_timeout(1000)


def set_target_roas(page, roas_value):
    from src.pages.common import robust_click, wait_until

    other_labels = ["最高价值", "成本上限", "最高转化量", "最低成本"]

    def roas_input_ready():
        loc = page.get_by_placeholder("请输入一个值")
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    def find_visible_label():
        for label in other_labels:
            loc = page.get_by_text(label, exact=True)
            if loc.count() > 0 and loc.first.is_visible():
                return label
        return None

    # up to a full minute for EITHER the Target-ROAS input (already selected) or
    # one of the other known bid-strategy labels to show up - this section can be
    # slow to render, especially right after picking the mini game on a freshly
    # added blank ad group. The platform can genuinely lag close to a minute.
    roas_input = wait_until(page, roas_input_ready, timeout_seconds=60)
    matched_label = None if roas_input else wait_until(page, find_visible_label, timeout_seconds=60)

    if not roas_input:
        if matched_label is None:
            raise ValueError(
                "竞价策略区域一直没能加载出来（既没看到'目标ROAS'输入框，也没看到其他出价策略选项）"
            )

        robust_click(page, page.get_by_text(matched_label, exact=True).first, timeout=10000)
        page.wait_for_timeout(500)

        def target_roas_visible():
            loc = page.get_by_text("目标ROAS", exact=True)
            return loc if (loc.count() > 0 and loc.first.is_visible()) else None

        target_roas_option = wait_until(page, target_roas_visible, timeout_seconds=60)
        if not target_roas_option:
            raise ValueError("点开竞价策略下拉框后没有找到'目标ROAS'这个选项")

        robust_click(page, target_roas_option.first, timeout=10000)
        page.wait_for_timeout(1000)
        roas_input = wait_until(page, roas_input_ready, timeout_seconds=60)

    if not roas_input:
        raise ValueError("选了'目标ROAS'之后，输入框还是一直没出现")

    roas_input.first.fill(str(roas_value))
    page.wait_for_timeout(500)


def set_regions(page, region_id_name_pairs):
    """region_id_name_pairs: list of (region_id: str, country_name: str).
    Matches results by data-testid=lego-search-result-content-{region_id}, which
    encodes TikTok's exact location id - avoids fuzzy-text mis-clicks (e.g. a
    "巴西" search also surfacing "巴西兰迪亚, ..." rows with the same substring).
    """
    from src.pages.common import dismiss_popups, robust_click

    dismiss_popups(page)

    def locate_region_field():
        f = page.get_by_placeholder("搜索或选择地域")
        if f.count() == 0:
            f = page.get_by_text("搜索或选择地域", exact=True)
        return f

    field = locate_region_field()
    for _ in range(15):
        if field.count() > 0:
            break
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)
        field = locate_region_field()
    field.first.wait_for(state="visible", timeout=10000)
    field.first.scroll_into_view_if_needed(timeout=5000)

    search_input = page.locator('[data-testid="lego-antd-select-popover-content-input"]')
    failed = []

    for region_id, name in region_id_name_pairs:
        if search_input.count() == 0 or not search_input.first.is_visible():
            field = locate_region_field()
            field.first.click(timeout=10000)
            page.wait_for_timeout(800)
            search_input.wait_for(state="visible", timeout=10000)

        search_input.first.fill("")
        search_input.first.fill(name)
        page.wait_for_timeout(1200)

        option = page.locator(f'[data-testid="lego-search-result-content-{region_id}"]')
        if option.count() == 0:
            page.wait_for_timeout(1500)
            search_input.first.fill("")
            search_input.first.fill(name)
            page.wait_for_timeout(1800)

        if option.count() == 0:
            failed.append((region_id, name))
            continue

        option.scroll_into_view_if_needed(timeout=5000)
        robust_click(page, option, timeout=5000)
        page.wait_for_timeout(600)

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return failed


def _locate_region_field(page):
    f = page.get_by_placeholder("搜索或选择地域")
    if f.count() == 0:
        f = page.get_by_text("搜索或选择地域", exact=True)
    return f


def _select_all_available_regions_once(page):
    from src.pages.common import robust_click

    field = _locate_region_field(page)
    for _ in range(15):
        if field.count() > 0:
            break
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)
        field = _locate_region_field(page)
    field.first.wait_for(state="visible", timeout=10000)
    field.first.scroll_into_view_if_needed(timeout=5000)
    field.first.click(timeout=10000)
    page.wait_for_timeout(1000)

    # the list needs a moment to refresh to the newly-selected mini game's actual
    # authorized regions - "阿根廷"(Argentina) showing up is a reliable tell that
    # it's still showing stale/default data (this account never runs ads there),
    # so wait it out before reading/checking anything. Also wait for at least one
    # checkbox row to exist at all - the whole list can still be loading. Give it
    # up to a full minute; this platform can genuinely lag that long.
    from src.pages.common import wait_until

    def list_ready():
        has_rows = page.locator('span.ant-tree-checkbox').count() > 0
        has_argentina = page.get_by_text("阿根廷", exact=True).count() > 0
        return has_rows and not has_argentina

    wait_until(page, list_ready, timeout_seconds=60)

    unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')
    checked_count = 0
    stale_rounds = 0
    for _ in range(200):
        count = unchecked.count()
        if count == 0:
            if stale_rounds >= 2:
                break
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(400)
            stale_rounds += 1
            unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')
            continue
        stale_rounds = 0
        box = unchecked.first
        box.scroll_into_view_if_needed(timeout=5000)
        robust_click(page, box, timeout=5000)
        checked_count += 1
        page.wait_for_timeout(250)
        unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return checked_count


def _select_all_available_regions_except_once(page, excluded_ids):
    from src.pages.common import robust_click, wait_until
    from src.region_lookup import load_region_map

    region_map = load_region_map()
    missing_ids = [rid for rid in excluded_ids if str(rid) not in region_map]
    excluded_names = {rid: region_map[str(rid)] for rid in excluded_ids if str(rid) in region_map}

    field = _locate_region_field(page)
    for _ in range(15):
        if field.count() > 0:
            break
        page.mouse.wheel(0, 600)
        page.wait_for_timeout(400)
        field = _locate_region_field(page)
    field.first.wait_for(state="visible", timeout=10000)
    field.first.scroll_into_view_if_needed(timeout=5000)
    field.first.click(timeout=10000)
    page.wait_for_timeout(1000)

    def list_ready():
        has_rows = page.locator("span.ant-tree-checkbox").count() > 0
        has_argentina = page.get_by_text("阿根廷", exact=True).count() > 0
        return has_rows and not has_argentina

    wait_until(page, list_ready, timeout_seconds=60)

    unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')
    checked_count = 0
    stale_rounds = 0
    for _ in range(200):
        count = unchecked.count()
        if count == 0:
            if stale_rounds >= 2:
                break
            page.mouse.wheel(0, 300)
            page.wait_for_timeout(400)
            stale_rounds += 1
            unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')
            continue
        stale_rounds = 0
        box = unchecked.first
        box.scroll_into_view_if_needed(timeout=5000)
        robust_click(page, box, timeout=5000)
        checked_count += 1
        page.wait_for_timeout(250)
        unchecked = page.locator('span.ant-tree-checkbox[aria-checked="false"]')

    # Uncheck each excluded region WHILE THE PICKER IS STILL OPEN from the
    # select-all pass above - confirmed live that closing and reopening the
    # field afterward doesn't work, because the field's placeholder text
    # ("搜索或选择地域", what _locate_region_field matches on) disappears once
    # anything is selected, leaving nothing to click to reopen it. Also
    # confirmed live that data-testid=lego-search-result-content-{id} (used by
    # set_regions for exact-id targeting) only exists for filtered SEARCH
    # results, not this unsearched full-tree view - so match by the tree row's
    # own visible text instead via the stable antd class ".ant-tree-treenode".
    failed_regions = []
    for region_id, name in excluded_names.items():
        row = page.locator(".ant-tree-treenode").filter(has_text=name)
        if row.count() == 0:
            failed_regions.append((region_id, name))
            continue
        checkbox = row.first.locator(".ant-tree-checkbox")
        if checkbox.count() == 0:
            failed_regions.append((region_id, name))
            continue
        checkbox.first.scroll_into_view_if_needed(timeout=5000)
        robust_click(page, checkbox.first, timeout=5000)
        checked_count -= 1
        page.wait_for_timeout(300)

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return checked_count, missing_ids, failed_regions


def select_all_available_regions_except(page, excluded_ids):
    """Same end result as select_all_available_regions, but leaves the given
    region ids unchecked (e.g. Region cell 'ex6252001' -> every available
    region except the US).
    Returns (checked_count, missing_ids, failed_regions):
    - missing_ids: excluded ids not found in REGION.xlsx at all
    - failed_regions: (id, name) pairs that were in REGION.xlsx but never
      appeared as a row in the tree (so could not be unchecked)
    """
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    missing_ids, failed_regions = [], []
    for attempt in range(3):
        checked_count, missing_ids, failed_regions = _select_all_available_regions_except_once(
            page, excluded_ids
        )
        if checked_count > 0:
            return checked_count, missing_ids, failed_regions
        page.wait_for_timeout(1500)

    return 0, missing_ids, failed_regions


def select_all_available_regions(page):
    """Open the region picker WITHOUT typing a search query - TikTok already scopes
    the default (unsearched) list to whatever regions this mini game is authorized
    for - and check every box that isn't already checked. Simpler and more accurate
    than matching specific ids from the Excel Region column, since that column was
    only ever a subset the old API-based tool could express.

    Retries the whole open-and-check sequence a few times if it ends up checking
    zero boxes - that almost always means the list was still loading rather than
    a mini game genuinely having zero authorized regions.
    """
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    for attempt in range(3):
        checked_count = _select_all_available_regions_once(page)
        if checked_count > 0:
            return checked_count
        page.wait_for_timeout(1500)

    return 0
