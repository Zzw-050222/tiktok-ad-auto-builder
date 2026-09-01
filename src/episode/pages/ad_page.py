"""短剧端计划 —— 广告层里和小游戏不一样的那部分。

目前只有一件事：文案要填【多条】。

使用者的表里，ads_text 这一格用 | 分隔多条文案，例如
    第一条|第二条|第三条|第四条|第五条
页面上「文案 (0/5)」这一块最多放 5 条：填完第一个框，下面会自动多出一个空框，
填第二个又多出第三个，依此类推。

小游戏那边 ads_text 是单条，用 ad_page.fill_ad_copy 填一个框就完事，
所以这里单独写一个，不去动小游戏那条已经跑了很久的路。
"""

from src.pages.ad_page import commit_input
from src.pages.common import wait_until

# 表格里分隔多条文案的符号
COPY_SEPARATOR = "|"

# 平台上限。页面标题上就写着「文案 (0/5)」。
MAX_COPIES = 5

_COPY_PLACEHOLDER = "输入文案"
_ADD_MORE_TEXT = "添加替代文案"


def split_copies(ads_text, separator=COPY_SEPARATOR):
    """把一格文案拆成多条。返回 (条目列表, 警告或 None)。

    去掉空白段：使用者手填时很容易多打一个分隔符，或者结尾带一个。
    超过 5 条的部分会被丢掉并【说出来】—— 平台就只收 5 条，
    默默截断的话，表里写了 7 条、页面上只有 5 条，人不会知道少了哪两条。
    """
    parts = [p.strip() for p in str(ads_text or "").split(separator)]
    parts = [p for p in parts if p]
    if not parts:
        return [], "ads_text 是空的，没有文案可填"
    if len(parts) > MAX_COPIES:
        dropped = parts[MAX_COPIES:]
        return parts[:MAX_COPIES], (
            f"表里这一格有 {len(parts)} 条文案，但页面最多只收 {MAX_COPIES} 条，"
            f"后面 {len(dropped)} 条没填进去：{dropped}"
        )
    return parts, None


def _visible_copy_boxes(page, limit=12):
    """当前可见的文案输入框，按页面顺序。

    只取【可见】的：DOM 里会同时留着别的广告/别的广告组的表单（沿「继续」走过
    的那些），占位文字一模一样。这条是 ad_page.first_visible_input 里踩出来的，
    盲取 .first 会填到隐藏的框上，页面上什么都不变。

    注意：填过内容的框，placeholder 属性还在，所以这里拿到的是【所有】文案框，
    不只是空的。
    """
    loc = page.get_by_placeholder(_COPY_PLACEHOLDER)
    out = []
    try:
        n = loc.count()
    except Exception:
        return out
    for i in range(min(n, limit)):
        el = loc.nth(i)
        try:
            if el.is_visible():
                out.append(el)
        except Exception:
            continue
    return out


def _box_values(page):
    """当前可见文案框里各自的值。"""
    vals = []
    for el in _visible_copy_boxes(page):
        try:
            vals.append((el.input_value(timeout=2000) or "").strip())
        except Exception:
            vals.append(None)
    return vals


def _click_add_more(page):
    """点「+ 添加替代文案」。点不到返回 False。"""
    from src.pages.common import robust_click

    loc = page.get_by_text(_ADD_MORE_TEXT, exact=False)
    try:
        n = loc.count()
    except Exception:
        return False
    for i in range(min(n, 6)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            robust_click(page, el, timeout=5000)
            return True
        except Exception:
            continue
    return False


def fill_ad_copies(page, ads_text):
    """把一格用 | 分隔的文案填成多条。返回警告列表。

    流程和人手动做的一样：
        填第 1 个框 -> 页面自动多出第 2 个空框 -> 填第 2 个 -> 再多出第 3 个 …
    自动没多出来就点「+ 添加替代文案」补一个。

    每填一条都【回读校验】。文案框和页面上别处的输入框占位文字相同、DOM 里还留着
    别的广告的表单，不校验的话很容易「填了但填到别的框上」——
    这个项目里已经因为这个吃过亏（短剧的 URL 填到隐藏框上，回读还通过了）。
    """
    warnings = []
    parts, warn = split_copies(ads_text)
    if warn:
        warnings.append(warn)
    if not parts:
        return warnings

    # 等文案区渲染出来
    boxes = wait_until(page, lambda: _visible_copy_boxes(page) or None,
                       timeout_seconds=60)
    if not boxes:
        raise ValueError(f"等了 60 秒没找到文案输入框（占位文字「{_COPY_PLACEHOLDER}」）")

    print(f"      [文案] 表里这一格拆出 {len(parts)} 条", flush=True)

    for i, text in enumerate(parts):
        boxes = _visible_copy_boxes(page)

        # 需要第 i+1 个框但页面上还没有 -> 点「添加替代文案」补一个
        if i >= len(boxes):
            if not _click_add_more(page):
                warnings.append(
                    f"要填第 {i + 1} 条文案，但页面上只有 {len(boxes)} 个框，"
                    f"也点不到「{_ADD_MORE_TEXT}」，后面 {len(parts) - i} 条没填"
                )
                break
            page.wait_for_timeout(1000)
            boxes = _visible_copy_boxes(page)
            if i >= len(boxes):
                warnings.append(
                    f"点了「{_ADD_MORE_TEXT}」但没多出输入框，第 {i + 1} 条起没填"
                )
                break

        el = boxes[i]
        try:
            el.scroll_into_view_if_needed(timeout=8000)
        except Exception:
            pass
        try:
            el.click(timeout=8000)
        except Exception:
            pass
        el.fill("")
        el.fill(text)
        page.wait_for_timeout(400)
        commit_input(page, el)

        # 回读同一个元素确认（填和读必须是同一个 element）
        got = None
        try:
            got = (el.input_value(timeout=3000) or "").strip()
        except Exception:
            pass
        if got is not None and got != text:
            el.fill("")
            el.fill(text)
            page.wait_for_timeout(500)
            commit_input(page, el)
            try:
                got = (el.input_value(timeout=3000) or "").strip()
            except Exception:
                pass
        if got is not None and got != text:
            warnings.append(
                f"第 {i + 1} 条文案填完读回的是 {got[:40]!r}，和表里的对不上"
            )

        # 不是最后一条的话，等页面自动多出下一个空框（等不到下一轮会点「添加替代文案」）
        if i < len(parts) - 1:
            need = i + 2
            wait_until(page, lambda n=need: len(_visible_copy_boxes(page)) >= n,
                       timeout_seconds=8)

    vals = [v for v in _box_values(page) if v]
    print(f"      [文案] 填完，页面上现在有 {len(vals)} 条", flush=True)
    if len(vals) < len(parts):
        warnings.append(
            f"预期填 {len(parts)} 条文案，页面上只读到 {len(vals)} 条"
        )
    return warnings
