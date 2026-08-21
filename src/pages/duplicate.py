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
    """在给定的行里找复制图标，返回第一个【存在】的（不要求有尺寸）。

    2026-08-21 实测：在【广告层】上，那一行的操作按钮是【零尺寸】的——
        · <ks-button …class="sidebar-item-node__operate-btn-…">  rect=[0,0,0,0]
        · <ks-icon name="copy-content" class="… KsIconCopyContent">  rect=[0,0,0,0]
        · <ks-dropdown-menu data-testid="ttam-sidebar-more-actions__moreIcon"> rect=[0,0,0,0]
    只有鼠标悬到那一行上才会撑开。而 Playwright 对零尺寸元素的 bounding_box()
    返回 None，所以上一版「要求 bounding_box() 有值」就把它判成了「找不到复制图标」。
    （在广告组页面上它是有尺寸的，所以之前那个探针能找到——两个页面不一样。）

    这里只要元素【在 DOM 里】就返回，尺寸留给 _click_copy_icon 在 hover 之后再取。
    """
    for sel in _COPY_ICON_SELECTORS:
        loc = scope.locator(sel)
        try:
            if loc.count() > 0:
                return loc.first
        except Exception:
            continue
    return None


def _click_copy_icon(page, row, icon):
    """点复制图标：先 hover 那一行把按钮撑开，再按坐标点；拿不到坐标就退回 robust_click。

    顺序很重要——必须 hover 之后再读 bounding_box()，因为在广告层上这些按钮
    hover 之前是 0x0（见 _find_copy_icon）。

    每次 hover 之前先看弹窗是不是已经开了，开了就立刻回来。
    2026-08-21 使用者实测：「点到了 + 号但是到了复制窗口居然一直在滑滚轮」——
    就是这里造成的：弹窗其实已经打开，但外层判定没认出来又来重试，而 hover()
    自带 scroll-into-view，4 轮重试 × 每轮 3 次 hover = 一直在滚。
    """
    from src.pages.common import robust_click

    box = None
    for _ in range(3):
        if _modal_open(page):
            return "（弹窗已开，没再点）"
        try:
            row.hover(timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(500)
        try:
            box = icon.bounding_box()
        except Exception:
            box = None
        if box and box.get("width") and box.get("height"):
            break
        box = None

    if _modal_open(page):
        return "（弹窗已开，没再点）"
    if box:
        page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        return "鼠标点坐标"
    # 还是 0x0：直接让 robust_click 走到 JS 派发那一步（它对零尺寸元素也有效）
    robust_click(page, icon, timeout=6000)
    return "robust_click(JS派发)"


def _wait_modal(page, timeout_seconds=10):
    """等「副本数量」弹窗出现。轮询而不是固定 sleep。

    原来是点完固定等 1.5 秒再判一次，等不到就当没开、再点一遍。而这个后台经常
    卡到几秒，于是「其实开了、只是慢」被当成「没开」，然后又点又滚（见
    _click_copy_icon 的说明）。改成轮询，开了立刻走。
    """
    from src.pages.common import wait_until

    return bool(wait_until(page, lambda: _modal_open(page) or None,
                           timeout_seconds=timeout_seconds))


def _dup_failure_detail(page):
    """复制弹窗死活不出现时，把现场信息带进报错里，免得下次还要靠猜。"""
    btns, dlgs = [], []
    try:
        b = page.get_by_role("button")
        for i in range(min(b.count(), 20)):
            try:
                if not b.nth(i).is_visible():
                    continue
                t = (b.nth(i).inner_text() or "").replace("\n", " ").strip()
                if t:
                    btns.append(t[:20])
            except Exception:
                continue
    except Exception:
        pass
    try:
        d = page.locator('[role="dialog"]:visible, [class*="modal"]:visible')
        for i in range(min(d.count(), 3)):
            try:
                t = (d.nth(i).inner_text() or "").replace("\n", " ").strip()
                if t:
                    dlgs.append(t[:160])
            except Exception:
                continue
    except Exception:
        pass
    return f"当前可见按钮: {btns}；弹层文字: {dlgs or '（没有可见弹层）'}"


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
        # 每轮开头先看弹窗是不是已经开着。开着就别再碰那一行——再 hover 就会又滚一遍
        # （使用者实测「到了复制窗口居然一直在滑滚轮」就是这么来的）。
        if _modal_open(page):
            break

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
                    f"{_dup_failure_detail(page)}"
                )
            page.wait_for_timeout(800)
            continue

        how = _click_copy_icon(page, row.first, icon)
        if _wait_modal(page):
            if attempt or how != "鼠标点坐标":
                print(f"          [复制广告组] 第{attempt + 1}次（{how}）打开了"
                      "「副本数量」弹窗", flush=True)
            break
        print(f"          [复制广告组] 第{attempt + 1}次（{how}）没打开弹窗", flush=True)
        if attempt == 3:
            raise ValueError(
                "点了 4 次广告组行上的复制图标，「副本数量」弹窗始终没出现。"
                f"广告组名 {ad_group_name!r}。{_dup_failure_detail(page)}"
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
        # 同广告组那边：弹窗已经开着就立刻停手，别再 hover 那一行（hover 会滚动）
        if _modal_open(page):
            break

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
                    f"（试过 {list(_COPY_ICON_SELECTORS)}）。{_dup_failure_detail(page)}"
                )
            page.wait_for_timeout(800)
            continue
        how = _click_copy_icon(page, row.first, icon)
        if _wait_modal(page):
            if attempt or how != "鼠标点坐标":
                print(f"          [复制广告] 第{attempt + 1}次（{how}）打开了"
                      "「副本数量」弹窗", flush=True)
            break
        print(f"          [复制广告] 第{attempt + 1}次（{how}）没打开弹窗", flush=True)
        if attempt == 3:
            raise ValueError(
                "点了 4 次广告行上的复制图标，「副本数量」弹窗始终没出现。"
                f"{_dup_failure_detail(page)}"
            )
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
