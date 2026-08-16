def wait_until(page, condition_fn, timeout_seconds=60, interval_ms=500):
    """Poll condition_fn() (a zero-arg callable returning truthy/falsy) every
    interval_ms until it returns truthy, or timeout_seconds elapses (default a
    full minute - this account's platform lag can genuinely run that long, per
    the user: wait it out rather than fail early). Returns the last truthy value
    (or False) so callers can use either the boolean result or whatever object
    the condition returned.
    """
    rounds = max(1, int(timeout_seconds * 1000 / interval_ms))
    for _ in range(rounds):
        result = condition_fn()
        if result:
            return result
        page.wait_for_timeout(interval_ms)
    return condition_fn()


def wait_visible_text(page, text_or_re, what, timeout_seconds=60):
    """等一个文字元素出现【并且可见】，返回那个可见元素，等不到就抛 TimeoutError。

    千万不要写成 page.get_by_text(...).first.wait_for(state="visible")。这个后台的
    页面上大量存在同文本的隐藏副本（尺寸 0x0，藏在收起的下拉、悬浮预览面板里）——
    2026-08-14 实测「目标 ROAS」一个页面上命中 5 个、其中 4 个尺寸为 0。先取 .first
    再等它可见，一旦 .first 恰好是隐藏那份，就会一直等到超时，而页面上明明有一个
    可见的。必须遍历所有匹配、挑出真正可见的那一个。

    text_or_re 传正则时记得【锚定首尾】，否则会误中包含该文字的长句子。
    """
    def visible_one():
        loc = page.get_by_text(text_or_re)
        n = loc.count()
        for i in range(min(n, 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    found = wait_until(page, visible_one, timeout_seconds=timeout_seconds)
    if not found:
        raise TimeoutError(f"等了 {timeout_seconds} 秒还没看到{what}")
    return found


def dismiss_popups(page):
    for label in ["知道了", "我知道了", "关闭"]:
        btn = page.get_by_role("button", name=label, exact=True)
        if btn.count() > 0 and btn.first.is_visible():
            btn.first.click(timeout=3000)
            page.wait_for_timeout(500)
            return True
    return False


def robust_click(page, locator, timeout=5000):
    """Try a normal click, then a forced click, then finally a raw JS-dispatched
    click that bypasses every Playwright actionability/viewport check entirely.
    Some of TikTok's popup lists (mini game / duplicate icon) occasionally report
    "element is outside of the viewport" even after scroll_into_view_if_needed()
    and even a force click - the JS fallback is the last resort that always works
    as long as the element exists in the DOM at all.
    """
    try:
        locator.click(timeout=timeout)
        return
    except Exception:
        pass
    try:
        locator.click(timeout=timeout, force=True)
        return
    except Exception:
        pass
    locator.evaluate("el => el.click()")


def click_to_open(trigger_locator, timeout=10000):
    """Click a toggle-style dropdown/popover trigger EXACTLY ONCE, swallowing
    a timeout exception rather than escalating to a force-click or JS click.
    Escalating (like robust_click does) is unsafe here: confirmed live that a
    plain click can report a Playwright TimeoutError - blocked by a
    transient intercepting overlay - while the popover still ends up open
    anyway (a partial pointer event got through during Playwright's internal
    retries). A second, forced click then lands on an ALREADY-open toggle and
    closes it right back, so all downstream "find something inside the now-
    open dropdown" logic - including any fallback scrolling - ends up
    operating on a closed page instead. Tried several ways to positively
    detect "is it already open" (ARIA state, page text markers, DOM
    ancestors) before landing on this - none were reliable, partly because
    this account's picker uses shadow DOM. Trust the caller's own downstream
    readiness wait/retry instead of trying to detect state here.
    """
    try:
        trigger_locator.click(timeout=timeout)
    except Exception:
        pass


def exit_draft(page):
    page.get_by_role("button", name="退出", exact=True).first.click(timeout=10000)
    page.wait_for_timeout(1000)
    dialog = page.get_by_text("你确定要退出此页面吗？")
    if dialog.count() > 0:
        page.get_by_role("button", name="退出", exact=True).last.click(timeout=10000)
    page.wait_for_timeout(2000)
