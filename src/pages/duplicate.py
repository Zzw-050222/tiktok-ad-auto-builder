# 左侧那一行上的「复制」图标怎么定位。
#
# 2026-08-21 实测（src/dev_probe_dupicon.py）—— 这是「点不到复制按钮」的真正原因：
# 那一行里的复制图标真实长这样
#     <ks-icon size="14px" name="copy-content" ks-v="1.0.5"
#              class="ks-icon ks-icon--rtlable KsIcon KsIconCopyContent">
# 标签名是朴素的 <ks-icon>，「copy-content」在 name 属性和 class 里。
# 而老代码写的是 row.locator("ks-icon-copy-content") —— 把它当成【元素名】去找，
# 命中 0 个，于是点了几次都是点空气，弹窗当然不出现。
# 探针里逐个坐标点过一遍：点这个 <ks-icon name="copy-content"> 才会打开「副本数量」，
# 点右边的 more-vertical（⋮）和它外面的 ks-dropdown-menu 都不行。
#
# 这也顺带解释了使用者说的「有些账号能复制有些不能」——不同广告主的界面版本不同，
# 有的还是老的独立标签名，有的已经换成 name 属性了。所以三种写法都留着当兜底。
_COPY_ICON_SELECTORS = (
    '[name="copy-content"]',        # 现在的写法（实测命中）
    ".KsIconCopyContent",           # 同一个元素的 class，双保险
    "ks-icon-copy-content",         # 老的独立标签名，老界面还留着
)


def _find_copy_icon(scope):
    """在给定的行里找复制图标，返回第一个【有尺寸】的。找不到返回 None。"""
    for sel in _COPY_ICON_SELECTORS:
        loc = scope.locator(sel)
        try:
            n = loc.count()
        except Exception:
            continue
        for i in range(min(n, 6)):
            el = loc.nth(i)
            try:
                if el.bounding_box():
                    return el
            except Exception:
                continue
    return None


def _click_copy_icon(page, row, icon):
    """点复制图标。用【真实鼠标点坐标】——探针里就是这么点开的。

    先 hover 那一行（图标是 hover 才显现的），再按图标中心坐标点。
    坐标拿不到时退回 robust_click。
    """
    from src.pages.common import robust_click

    try:
        row.hover(timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(400)
    box = None
    try:
        box = icon.bounding_box()
    except Exception:
        pass
    if box:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    else:
        robust_click(page, icon, timeout=6000)


def _find_copy_count_input(page):
    """找「副本数量」那个数字输入框。找不到返回 None。

    2026-08-21 从 xpath 换成这个写法 —— 【照搬 duplicate_ad_n_times 里已经能用的
    那份】。那个函数的注释早就写明了原因：

        avoid xpath's `following::` axis here - it doesn't cross shadow DOM
        boundaries, which some accounts' components use for this exact modal.
        A plain CSS/text-based Playwright locator does pierce shadow DOM

    而广告组复制这边一直还在用
        //*[normalize-space(text())='副本数量']/following::input[1]
    于是在把这个弹窗渲染成 shadow DOM 的账号上，弹窗其实【已经打开了】，只是这个
    xpath 永远匹配不到，5 秒后超时、三轮之后抛错。使用者报的
    「Locator.wait_for: Timeout 5000ms exceeded … '副本数量'/following::input[1]」
    就是这一句，而且「有些账号能复制、有些不能」也正好由此解释。
    """
    count_input = page.locator(
        'input[type="text"]:visible, input[type="number"]:visible'
    )
    try:
        n = count_input.count()
    except Exception:
        return None
    # 优先挑值恰好是 "1" 的那个（副本数量的默认值）
    for i in range(min(n, 30)):
        try:
            if count_input.nth(i).input_value(timeout=500) == "1":
                return count_input.nth(i)
        except Exception:
            continue
    return None


def _modal_open(page):
    """「副本数量」弹窗开着没有。用文字判断——文字定位器能穿透 shadow DOM。"""
    try:
        loc = page.get_by_text("副本数量", exact=True)
        for i in range(min(loc.count(), 6)):
            if loc.nth(i).is_visible():
                return True
    except Exception:
        pass
    return False


def _open_duplicate_modal(page, ad_group_name: str, count: int):
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    row = page.locator('[data-testid="creation_1nn_sidebar_adgroup_node"]').filter(
        has_text=ad_group_name
    )
    row.first.scroll_into_view_if_needed(timeout=10000)

    for attempt in range(4):
        try:
            row.first.hover(timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(500)

        icon = _find_copy_icon(row.first)
        if icon is None:
            if attempt == 3:
                raise ValueError(
                    f"广告组 {ad_group_name!r} 那一行上找不到复制图标"
                    f"（试过 {list(_COPY_ICON_SELECTORS)}）。"
                    f"当前地址: {page.url[:120]}"
                )
            page.wait_for_timeout(800)
            continue

        _click_copy_icon(page, row.first, icon)
        page.wait_for_timeout(1500)
        if _modal_open(page):
            break
        if attempt == 3:
            raise ValueError(
                "点了 4 次广告组行上的复制图标，「副本数量」弹窗始终没出现。"
                f"广告组名 {ad_group_name!r}，当前地址: {page.url[:120]}"
            )
        page.wait_for_timeout(800)

    target_input = _find_copy_count_input(page)
    if target_input is None:
        raise ValueError(
            "「副本数量」弹窗已经打开，但找不到那个数字输入框（默认值应该是 1）。"
            "把 logs/ 发出来以便补充识别方式。"
        )

    target_input.fill("")
    target_input.fill(str(count))
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
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    # TikTok's internal term for "ad" here is "creative" (matches the ad-level
    # URL path .../create/spc-creative too) - confirmed live, NOT
    # "..._ad_node" (that guess matched zero elements)
    row = page.locator('[data-testid="creation_1nn_sidebar_creative_node"]')
    row.first.scroll_into_view_if_needed(timeout=10000)

    # 复制图标的定位方式和广告组那边一样，2026-08-21 一起修的：写死
    # ks-icon-copy-content 这个【元素名】是错的，实际是
    # <ks-icon name="copy-content" class="… KsIconCopyContent">
    for attempt in range(4):
        try:
            row.first.hover(timeout=10000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        icon = _find_copy_icon(row.first)
        if icon is None:
            if attempt == 3:
                raise ValueError(
                    "广告那一行上找不到复制图标"
                    f"（试过 {list(_COPY_ICON_SELECTORS)}）"
                )
            page.wait_for_timeout(800)
            continue
        _click_copy_icon(page, row.first, icon)
        page.wait_for_timeout(1500)
        if _modal_open(page):
            break
        if attempt == 3:
            raise ValueError("点了 4 次广告行上的复制图标，「副本数量」弹窗始终没出现")
        page.wait_for_timeout(800)

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
