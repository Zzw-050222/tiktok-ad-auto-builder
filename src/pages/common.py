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
