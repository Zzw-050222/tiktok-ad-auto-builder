import re


def _wait_visible(page, text_or_re, what, timeout_seconds=60):
    """等一个文字元素出现【并且可见】，最多 timeout_seconds，返回那个可见元素。

    比裸的 scroll_into_view_if_needed(timeout=10000) 强在两点：给足这个平台真实
    需要的时间（见 common.wait_until 的注释），以及在页面上存在多个同文本副本
    （其中大部分尺寸为 0）时挑出真正能点的那一个 —— 这页面上这种情况很常见。
    """
    from src.pages.common import wait_until

    def visible_one():
        loc = page.get_by_text(text_or_re)
        n = loc.count()
        for i in range(min(n, 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    found = wait_until(page, visible_one, timeout_seconds=timeout_seconds)
    if not found:
        raise ValueError(f"等了 {timeout_seconds} 秒还没看到{what}")
    return found


def _wait_visible_button(page, name, what, timeout_seconds=60):
    """同上，但按钮走 role 定位。"""
    from src.pages.common import wait_until

    def visible_one():
        loc = page.get_by_role("button", name=name, exact=True)
        n = loc.count()
        for i in range(min(n, 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    found = wait_until(page, visible_one, timeout_seconds=timeout_seconds)
    if not found:
        raise ValueError(f"等了 {timeout_seconds} 秒还没看到{what}")
    return found


def _scroll_library_to_bottom(page, tiles):
    """把素材库面板滚到底 —— 触发下一批 30 个素材加载的必要条件。

    对最后一个已加载的素材卡做 scroll_into_view_if_needed，比按固定像素 wheel
    可靠得多：不用猜卡片高度，也不会因为一次只滚 400px 而根本没触到底部。之后
    再补几次 wheel，确保确实压在底部、把懒加载触发出来。

    锚点必须取真实可见卡片的坐标，绝不能用硬编码坐标 —— 硬编码位置可能整个错过
    这个面板，去滚了底层页面（这个坑项目里别处已经踩过并写在注释里了）。
    """
    n = tiles.count()
    if n == 0:
        return
    last = tiles.nth(n - 1)
    try:
        last.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    box = last.bounding_box()
    if not box:
        return
    page.mouse.move(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    for _ in range(4):
        page.mouse.wheel(0, 800)
        page.wait_for_timeout(300)


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

    # the "自动选择" box can take a while to finish generating.
    #
    # 这个守卫单独用是不可靠的：它的判据是「'正在加载中' 不存在就算好了」，而
    # wait_until 是立刻开始轮询的——页面还没【开始】加载时这个字样自然也不存在，
    # 于是第一次轮询就直接放行，等于什么都没等。真正的等待必须落在「目标元素出现」
    # 上（见下面的 _wait_visible），这里留着它只是为了在确实处于加载中时多等一会。
    def not_loading():
        loc = page.get_by_text("正在加载中", exact=False)
        return True if loc.count() == 0 else None

    wait_until(page, not_loading, timeout_seconds=60)
    page.wait_for_timeout(500)

    # 2026-08-14 实测：'自动选择' 这个框会晚于 10 秒才渲染出来（当天 TikTok 给
    # 这块加了「自动选择功能重磅上线」的推广横幅，整体变慢）。原来直接
    # scroll_into_view_if_needed(timeout=10000) 就会在 10 秒时抛
    # TimeoutError，而抓失败现场时元素其实已经在页面上了。改成 60 秒轮询等它
    # 【可见】，跟本项目其它地方（set_target_roas、区域列表等）统一。
    #
    # 用锚定的正则而不是 exact=True：页面上同时存在「自动选择功能重磅上线」这个
    # 横幅，它包含「自动选择」但不能点。锚定首尾正好把它排除掉。
    auto_select_box = _wait_visible(page, re.compile(r"^\s*自动选择\s*$"), "自动选择的框")
    auto_select_box.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, auto_select_box, timeout=5000)
    page.wait_for_timeout(1500)

    # the TOP-LEVEL "+ 添加创意素材" button - NOT the nested "+ 添加内容"
    # under "你的自有内容" (that path was confirmed inconsistent across
    # accounts, this one is not)
    top_add_btn = _wait_visible_button(page, "添加创意素材", "顶层的「添加创意素材」按钮")
    top_add_btn.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, top_add_btn, timeout=5000)
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
    idx = skip
    stable_rounds = 0
    for _ in range(200):
        cur_total = checkboxes.count()

        # 往前推进直到真的选够 count 个。
        #
        # 原来的条件是 idx < min(cur_total, skip + count)，配合无条件
        # selected += 1。两个问题：
        #  * robust_click 的最后一级兜底是 JS 直接派发 el.click()，永远不抛错，
        #    所以 selected 统计的是「点击次数」而不是「真正选中数」。2026-08-14
        #    实测出现过「返回 30，实际只有 29 个变成选中态」。
        #  * 调用方用这个返回值累加 creative_usage 的偏移量
        #    （creative_usage[key] = skip + selected），虚高会让后续计划的 skip
        #    越算越偏，最终重复选到已经用过的素材——去重就白做了。
        #  * 而且上限写死在 skip+count，一旦中间有点击失败，就再也补不回来了。
        # 改成：以「真正变成选中态」计数，并且允许越过 skip+count 去补足。
        while selected < count and idx < cur_total:
            cb = checkboxes.nth(idx)
            cb.scroll_into_view_if_needed(timeout=5000)
            robust_click(page, cb, timeout=5000)
            page.wait_for_timeout(250)
            idx += 1
            try:
                if cb.get_attribute("aria-checked") == "true":
                    selected += 1
            except Exception:
                # 读不到属性时保守按成功计，避免在异常状态下空转
                selected += 1
        if selected >= count:
            break

        # 还不够，需要让素材库加载下一批。
        #
        # 这个库的真实行为（使用者手动操作确认）：一次只给 30 个（每行 5 个），
        # 必须【滚到底】才会触发下一批，而且下一批要等【大约 10 秒】才出来。
        #
        # 原来的写法每轮只滚 400px、等 700ms，连续 4 轮数量没变就判定「素材不够
        # 了」——总共只等了约 2.8 秒，远小于 10 秒。后果是从第二个计划起
        # （去重让 skip=30，要拿第 31~60 个）永远等不到新素材：
        #   while idx < min(cur_total=30, target_end=60)  →  while 30 < 30  →  假
        # 一个都点不到，还误报「素材库里不够了」，而实际上素材是够的。
        before = cur_total
        _scroll_library_to_bottom(page, tiles)

        def more_loaded():
            return checkboxes.count() > before

        if wait_until(page, more_loaded, timeout_seconds=25):
            stable_rounds = 0
            continue

        # 滚到底并等满 25 秒仍然没有新素材，再给一次机会；两轮都没有才认定真的没了
        stable_rounds += 1
        if stable_rounds >= 2:
            break

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
