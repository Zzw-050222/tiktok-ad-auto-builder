import re


def wait_adgroup_page_ready(page):
    page.get_by_text("广告组名称", exact=True).first.wait_for(state="visible", timeout=90000)
    page.wait_for_timeout(800)


def fill_ad_group_name(page, ad_group_name: str):
    # 15 秒 -> 60 秒：同上，与项目里其它地方统一
    name_input = page.locator('input[type="text"]:visible').first
    name_input.wait_for(state="visible", timeout=60000)
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

    # A SINGLE force click, nothing else. Tried several other ways first, all
    # confirmed worse live:
    # - a plain (non-forced) click can report a Playwright timeout (an
    #   overlay briefly intercepts) while the dropdown still ends up open
    #   anyway from a partial pointer event during Playwright's retries - a
    #   second, escalated click then lands on that ALREADY-open toggle and
    #   closes it right back. On at least one account, a plain click also
    #   sometimes just genuinely had no effect at all (dropdown never opened).
    # - detecting "is it already open" via ambient page text (any "ID:"
    #   match, even requiring >=2 of them) is NOT reliable on every account -
    #   confirmed live: false positives from unrelated "ID:" text elsewhere
    #   on the page caused a retry-until-open loop to skip clicking entirely.
    # A single force click (skips the actionability/interception checks a
    # plain click waits on, so no misleading timeout) is the one variant
    # that reliably opened it in live testing. If it still doesn't open
    # anything for some account, the ID-based scroll search below simply
    # finds nothing and raises a clear error - an honest failure, not a
    # silent wrong click.
    try:
        picker.first.click(timeout=10000, force=True)
    except Exception:
        pass
    page.wait_for_timeout(800)

    def target_match():
        c = page.locator(f"text=ID: {tt_mini_id}")
        if c.count() == 0:
            c = page.locator(f"text=ID：{tt_mini_id}")
        return c if c.count() > 0 else None

    # NEVER type mini_game_name to search - confirmed live this can silently
    # land in whatever field had focus before (e.g. ad-group-name) when the
    # picker didn't actually open, with no reliable way to tell in advance
    # that it's safe to type. The ID-based scroll search below is the sole
    # mechanism now - slower on search-capable accounts, but never corrupts
    # an unrelated field.
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


# TikTok 在这个输入框上做文案灰度：同一个账号、同一个位置的同一个框，不同次
# 页面加载会随机拿到不同的 placeholder。2026-08-14 实测同一轮跑 3 个计划，抓到
# 两种并存：
#   '请输入一个值'                          <- 老文案
#   '请您输入广告花费回报（ROAS）下限值'      <- 新文案
# 只匹配其中一种就会随机失败（表现为「竞价策略区域一直没能加载出来」，因为这时
# 那 4 个备选策略标签也不可见——目标ROAS 本来就已经是选中状态了）。用正则同时
# 兼容两种，将来再改文案只要还带 ROAS 字样就仍然命中。
_ROAS_PLACEHOLDER_RE = re.compile(r"请输入一个值|ROAS")

# 页面上实际渲染的是「目标 ROAS」——中间有一个空格，而原来的 exact=True 匹配的是
# 「目标ROAS」，实测 命中=0 vs 命中=5。这条兜底路径因此一直是死代码，只是以前
# placeholder 能命中所以没暴露出来。用 \s* 兼容有无空格；必须锚定首尾，否则会误
# 中「修改目标 ROAS」和「…所有广告组的目标 ROAS必须保持一致。」这类长句。
_TARGET_ROAS_TEXT_RE = re.compile(r"^\s*目标\s*ROAS\s*$")


def set_target_roas(page, roas_value):
    from src.pages.common import robust_click, wait_until

    other_labels = ["最高价值", "成本上限", "最高转化量", "最低成本"]

    def roas_input_ready():
        loc = page.get_by_placeholder(_ROAS_PLACEHOLDER_RE)
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
            loc = page.get_by_text(_TARGET_ROAS_TEXT_RE)
            if loc.count() == 0:
                return None
            # 多个元素文本都恰好是「目标 ROAS」（span / div / ks-text 各一份），
            # 其中大部分尺寸为 0（藏在收起的下拉里），只有真正显示的那个能点。
            for i in range(min(loc.count(), 12)):
                if loc.nth(i).is_visible():
                    return loc.nth(i)
            return None

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
    from src.pages.common import click_to_open, dismiss_popups, robust_click, wait_until

    dismiss_popups(page)

    field = _wait_for_region_field(page)
    if not field:
        raise ValueError("地域选择框等了 60 秒还没出现（地域区块可能一直没渲染出来）")
    field.scroll_into_view_if_needed(timeout=5000)

    search_input = page.locator('[data-testid="lego-antd-select-popover-content-input"]')
    failed = []

    for region_id, name in region_id_name_pairs:
        if search_input.count() == 0 or not search_input.first.is_visible():
            field = _wait_for_region_field(page)
            if not field:
                print(f"          [地域] {name}: 找不到地域选择框", flush=True)
                failed.append((region_id, name))
                continue
            click_to_open(field, timeout=10000)
            page.wait_for_timeout(800)
            try:
                search_input.wait_for(state="visible", timeout=30000)
            except Exception:
                print(f"          [地域] {name}: 点开地域框后，搜索输入框 30 秒没出现"
                      "（多半是下拉根本没展开）", flush=True)
                failed.append((region_id, name))
                continue

        search_input.first.fill("")
        search_input.first.fill(name)

        # 原来是「填完等 1.2 秒，没结果就重填一次再等 1.8 秒」——最多约 4.5 秒。
        # 2026-08-14 实测这不够：同一个「日本」搜索，一次搜不出来（本函数返回
        # [('1861060','日本')] 导致上层报「没有任何地区被选中」），另一次同样的
        # 输入却正常。这个平台会卡到接近一分钟（见 common.wait_until 的注释），
        # 固定 sleep 是碰运气。改成 60 秒轮询等结果出现，中途重填一次搜索词。
        option = page.locator(f'[data-testid="lego-search-result-content-{region_id}"]')
        rounds = {"n": 0, "refilled": False}

        def option_ready():
            if option.count() > 0:
                return option
            rounds["n"] += 1
            # 约 10 秒还没出结果，重填一次搜索词（有时输入没被组件接住）
            if rounds["n"] == 20 and not rounds["refilled"]:
                rounds["refilled"] = True
                try:
                    search_input.first.fill("")
                    search_input.first.fill(name)
                except Exception:
                    pass
            return None

        if not wait_until(page, option_ready, timeout_seconds=60):
            # 把实际搜出来的结果打出来：是「搜不到」还是「搜到了但 ID 对不上」，
            # 这两种要区分，否则只能靠猜。
            try:
                res = page.locator('[data-testid^="lego-search-result-content-"]')
                got = []
                for k in range(min(res.count(), 8)):
                    try:
                        tid = res.nth(k).get_attribute("data-testid")
                        got.append(f"{tid}={res.nth(k).inner_text().strip()[:20]!r}")
                    except Exception:
                        continue
                typed = ""
                try:
                    typed = search_input.first.input_value(timeout=2000)
                except Exception:
                    pass
                print(f"          [地域] {name}: 搜了 60 秒没等到 "
                      f"lego-search-result-content-{region_id}。"
                      f"搜索框里是 {typed!r}，当前结果: {got or '（空）'}", flush=True)
            except Exception:
                pass
            failed.append((region_id, name))
            continue

        option.scroll_into_view_if_needed(timeout=5000)
        robust_click(page, option, timeout=5000)
        page.wait_for_timeout(600)

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)
    return failed


# 地域框的占位文案。TikTok 2026-08-14 当天把它从「搜索或选择地域」换成了
# 「请搜索或选择定向区域。」（多了「请」、「地域」变「定向区域」、末尾还多个句号），
# 同时在下面新增了「批量上传」按钮。旧文案当天已从页面上彻底消失。
# 只留一个正则做兜底，主路径改用结构定位（见 _locate_region_field）。
_REGION_PLACEHOLDER_RE = re.compile(r"^\s*请?搜索或选择(地域|定向区域)。?\s*$")

# 地域框的结构定位。2026-08-14 抓到的真实层级：
#   <div class="particleLocations-SLs03s">            ← 地域专属容器
#     <div data-testid="lego-antd-select">            ← 真正可点击的下拉容器
#       <ks-text-*>请搜索或选择定向区域。</ks-text-*>   ← 只是里面的文字
#       <ks-icon-chevron-down>                        ← 箭头
# 六次快照里 particleLocations-SLs03s 完全一致，data-testid 也一致，只有
# <ks-text-*> 这类自定义元素的标签名是每次随机的。所以按容器定位最稳。
# 注意 [class*="particleLocations-"] 不会误中同区块的
# particleLocationsRelated-gI2MSJ（后者没有紧跟的连字符），这点是刻意的。
_REGION_SELECT_CSS = '[class*="particleLocations-"] [data-testid="lego-antd-select"]'


def _locate_region_field(page):
    """收起状态下可点击的地域下拉容器，按可靠性从高到低尝试三种方式。

    以前只按占位文案找，而且找到的是文案那个 <ks-text-*> 文本元素本身——
    既不稳（TikTok 一改文案就全盘失效，当天就发生了），点它也未必能展开下拉。
    现在优先用结构定位，且返回的是下拉容器而不是里面的文字。
    """
    # ① 结构定位：不依赖任何文案，选中地区后占位文字消失也依然有效
    f = page.locator(_REGION_SELECT_CSS)
    if f.count() > 0:
        return f

    # ② 退一步：所有下拉容器里，文字命中地域占位文案的那个
    f = page.locator('[data-testid="lego-antd-select"]').filter(
        has_text=_REGION_PLACEHOLDER_RE
    )
    if f.count() > 0:
        return f

    # ③ 最后兜底：老界面的写法（input 的 placeholder，或纯文本元素）
    f = page.get_by_placeholder(_REGION_PLACEHOLDER_RE)
    if f.count() == 0:
        f = page.get_by_text(_REGION_PLACEHOLDER_RE)
    return f


def _wait_for_region_field(page, timeout_seconds=60):
    """等地域框出现【并且可见】，最多等 timeout_seconds，返回那个可见元素或 None。

    原来三处各写了一遍这样的逻辑：
        field = _locate_region_field(page)
        for _ in range(15):
            if field.count() > 0: break        # ← 用「存在」判断跳出
            page.mouse.wheel(0, 600); ...
        field.first.wait_for(state="visible", timeout=10000)   # ← 用「可见」判断成功

    两个判据不一致，2026-08-14 实测抓到两种翻车方式：
      * 地域区块整个还没渲染出来（命中=0）：循环滚满 15 次约 9000px 直接到页底
        （快照里输入框坐标都变成负数了），再花 10 秒等一个空定位器，必然超时；
      * 文字匹配命中了隐藏副本（ROAS 那次证明这页面上同文本的隐藏副本很常见）：
        立刻跳出循环、滚动一次都不执行，同样卡死在可见性等待上。
    而这个平台本来就会卡到接近一分钟（见 common.wait_until 的注释），10 秒远不够。

    改成：以【可见】为唯一判据，60 秒轮询。只在元素压根不在 DOM 里时才滚动
    （懒加载才需要滚；Playwright 的 is_visible() 跟元素在不在可视区无关，
    已经在 DOM 里的元素滚动帮不上忙），且滚动次数设上限，免得一路滚到页底。
    """
    from src.pages.common import wait_until

    scrolls = {"n": 0}

    def visible_field():
        f = _locate_region_field(page)
        n = f.count()
        if n > 0:
            for i in range(min(n, 10)):
                if f.nth(i).is_visible():
                    return f.nth(i)
            return None
        if scrolls["n"] < 15:
            scrolls["n"] += 1
            page.mouse.wheel(0, 600)
        return None

    return wait_until(page, visible_field, timeout_seconds=timeout_seconds)


def _select_all_available_regions_once(page):
    from src.pages.common import click_to_open, robust_click

    field = _wait_for_region_field(page)
    if not field:
        raise ValueError("地域选择框等了 60 秒还没出现（地域区块可能一直没渲染出来）")
    field.scroll_into_view_if_needed(timeout=5000)
    click_to_open(field, timeout=10000)
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
    from src.pages.common import click_to_open, robust_click, wait_until
    from src.region_lookup import load_region_map

    region_map = load_region_map()
    missing_ids = [rid for rid in excluded_ids if str(rid) not in region_map]
    excluded_names = {rid: region_map[str(rid)] for rid in excluded_ids if str(rid) in region_map}

    field = _wait_for_region_field(page)
    if not field:
        raise ValueError("地域选择框等了 60 秒还没出现（地域区块可能一直没渲染出来）")
    field.scroll_into_view_if_needed(timeout=5000)
    click_to_open(field, timeout=10000)
    page.wait_for_timeout(1000)

    def list_ready():
        has_rows = page.locator("span.ant-tree-checkbox").count() > 0
        has_argentina = page.get_by_text("阿根廷", exact=True).count() > 0
        return has_rows and not has_argentina

    wait_until(page, list_ready, timeout_seconds=60)

    # The region tree is VIRTUALIZED (rows get removed from the DOM once
    # scrolled far enough away, confirmed live on an account with a long
    # country list) - so a "select everything, then scroll back up to
    # uncheck the excluded one" approach is unreliable: by the time "select
    # all" finishes scrolling to the bottom, the excluded row may no longer
    # exist in the DOM at all to find and uncheck. Fixed design: iterate ROWS
    # (not raw checkboxes) forward-only, checking each row's own text against
    # the excluded names BEFORE deciding whether to click its own checkbox -
    # this way the excluded row is simply never clicked in the first place,
    # regardless of how far the list scrolls or whether virtualization later
    # removes it from the DOM. Self-correcting for virtualization too: rows
    # scrolled past and recycled don't need revisiting, since their checked
    # state persists in the underlying data even once un-rendered.
    excluded_names_list = list(excluded_names.values())
    seen_excluded = set()

    def process_visible_rows():
        newly_checked = 0
        rows = page.locator(".ant-tree-treenode")
        for i in range(rows.count()):
            row = rows.nth(i)
            try:
                text = row.inner_text()
            except Exception:
                continue
            matched_excluded = next((n for n in excluded_names_list if n in text), None)
            if matched_excluded:
                seen_excluded.add(matched_excluded)
                continue
            checkbox = row.locator(".ant-tree-checkbox")
            if checkbox.count() == 0:
                continue
            if checkbox.first.get_attribute("aria-checked") != "false":
                continue
            checkbox.first.scroll_into_view_if_needed(timeout=5000)
            robust_click(page, checkbox.first, timeout=5000)
            newly_checked += 1
            page.wait_for_timeout(200)
        return newly_checked

    checked_count = 0
    stale_rounds = 0
    for _ in range(300):
        checked_count += process_visible_rows()
        row_count_before = page.locator(".ant-tree-treenode").count()
        page.mouse.wheel(0, 300)
        page.wait_for_timeout(400)
        row_count_after = page.locator(".ant-tree-treenode").count()
        if row_count_after == row_count_before:
            stale_rounds += 1
            if stale_rounds >= 3:
                break
        else:
            stale_rounds = 0

    page.keyboard.press("Escape")
    page.wait_for_timeout(500)

    failed_regions = [
        (rid, name) for rid, name in excluded_names.items() if name not in seen_excluded
    ]
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
