"""沿右下角「继续」把一个计划的所有层级走一遍，在每个空广告层填内容。

## 为什么需要它

小游戏原来的「一个计划里多个广告组」是靠 Excel 的 Ad Group Name Number，在
【广告已经填完之后】复制广告组——副本会把素材一起复制走，于是所有广告组用的是
同一批素材。使用者要的是每个广告组下那个广告用【不同】的素材，所以复制的时机
必须提前到「刚进广告层、素材还没加」的那一刻，副本才是空的。

复制完 TikTok 不会停在原地，而是把你丢到某个广告组层。使用者实测出来的走法是
右下角那个「继续」把整个计划串成一条链：

    广告组层 --继续--> 广告层 --继续--> 下一个广告组层 --继续--> 广告层 --> …
    最后一个广告层上【没有「继续」，只有「全部发布」】

## 为什么不照抄点击次数

使用者描述的是「点一下进第一个广告组的广告层，再点一下进下一个广告组层……」。
照这个次数写死，就把「复制完落在第几个广告组」「链条按什么顺序走」这类平台行为
钉进代码里，TikTok 一改顺序就全错，而且错的方式是【往错误的广告里塞素材】——
边建边发布的流程下这是真花钱的错。

而「我现在在广告组层还是广告层」「这个广告填过没有」都是可以直接读出来的事实。
所以这里每到一站先看清状态再决定做什么。本项目反复踩出来的教训就是这条：
验证状态，别数动作。
"""

# 两个【互斥】的区块标题，都是本项目已经验证过的锚点：
#   广告组层  「广告组名称」—— wait_adgroup_page_ready 一直用它
#   广告层    「广告名称」
# 注意「广告名称」不是「广告组名称」的子串（中间隔着一个「组」），
# exact=True 下两者不会互相误命中。
_ADGROUP_MARK = "广告组名称"
_AD_MARK = "广告名称"

# 广告层最强的锚点：创意素材区块标题的 data-testid。
# 不能用「创意素材」这四个字判断——页面上有两处（区块标题 + 右侧「建议采纳情况」
# 里的检查项），命中两个会让 Playwright 抛 strict mode violation
# （wait_ad_page_ready 的注释里记着这个坑）。
_AD_TESTID = "creative-assets-header-title"

# 填过内容的判据：文案框或落地页框里有值。占位文字在填完之后依然在
# placeholder 属性上，所以这两个定位器一直有效。
_COPY_PLACEHOLDER = "输入文案"
_URL_PLACEHOLDER = "https://www.tiktok.com/minis/"


def _first_visible(locator, limit=12):
    """匹配里第一个【真正可见】的元素，没有就返回 None。

    绝不用裸 .first：这个后台到处都是同文本、同占位符的隐藏副本（尺寸 0，藏在
    收起的下拉、别的广告组的表单里）。.first 恰好是隐藏那个时，等它可见会一直
    超时，往里填值则会填到看不见的框上——回读还能通过，页面上却是空的。
    """
    try:
        n = locator.count()
    except Exception:
        return None
    for i in range(min(n, limit)):
        el = locator.nth(i)
        try:
            if el.is_visible():
                return el
        except Exception:
            continue
    return None


def _visible_exact_text(page, text):
    return _first_visible(page.get_by_text(text, exact=True))


def current_step(page):
    """现在停在哪一层：'ad' / 'adgroup' / None（还没渲染出来）。

    按可靠性从高到低判断，前面命中就不看后面的：
      ① 广告层的 data-testid（自定义标签名每次随机，但 testid 稳定）
      ② 「广告组名称」可见 -> 广告组层
      ③ 「广告名称」可见   -> 广告层（testid 万一改了的兜底）
    """
    if _first_visible(page.get_by_test_id(_AD_TESTID)) is not None:
        return "ad"
    if _visible_exact_text(page, _ADGROUP_MARK) is not None:
        return "adgroup"
    if _visible_exact_text(page, _AD_MARK) is not None:
        return "ad"
    return None


# 【不要】再写一个「靠文案/落地页有没有值来判断这个广告填过没有」的函数。
# 试过，是错的，而且错得很隐蔽（2026-08-20 使用者实测）：
#
#   * 小游戏的落地页链接【平台会自己带出来】（小游戏一选好就填上了），所以那个框
#     从一开始就是非空的。于是「非空 = 填过了」在第一个广告上就成立，链条把每一个
#     广告都当成「已经填过」跳过——日志里那句「预期填 5 个广告，实际只填了 0 个」
#     就是这么来的，而且它不报错，只是一声不响地什么都没干。
#   * 新顺序下更不可能用：现在是【先】把文案和 URL 写完再复制广告组，所有副本
#     一出生就带着文案和 URL，这个判据永远为真。
#
# 所以「这个广告轮到我了吗」改成按【数】来定：链条按顺序走，走到第 k 个广告层就
# 填第 k 个，填够 expected_ads 就停。代价是这条路要求「链条上的广告层都是本行刚
# 复制出来的」——一个计划里有多行时不满足，所以 builder 那边直接不让多行走这条路
# （见 build_campaign_group 里的 len(rows) > 1 分支），而不是在这里赌。
_COPY_PLACEHOLDER_UNUSED = _COPY_PLACEHOLDER
_URL_PLACEHOLDER_UNUSED = _URL_PLACEHOLDER


def find_continue_button(page):
    """右下角可见的「继续」按钮，没有就返回 None（= 走到链条末尾了）。

    不能用 continue_step()：它会等 60 秒再抛超时，而「没有继续按钮」在这条链上
    是【正常的终点信号】而不是错误。
    """
    return _first_visible(page.get_by_role("button", name="继续", exact=True), limit=6)


def find_publish_button(page):
    """可见的「全部发布」按钮，用来确认链条真的走到了末尾。"""
    return _first_visible(
        page.get_by_role("button", name="全部发布", exact=True), limit=6
    )


def _wait_next_step(page, prev_step, timeout_seconds=90):
    """点完「继续」之后，等页面真的换到下一站（层级从广告组层 <-> 广告层翻过去）。

    链条正常走就是这样交替的。等不到就返回 None，由调用方决定怎么办。

    注意这里【只认层级翻转】。原来还有一条「层级没变但广告是空的也算换了一站」的
    分支，用来应付一个广告组下有多个广告（广告层 -> 广告层）的情况——那条分支靠的是
    「广告是空的」这个判据，而那个判据本身是错的（见上面那段说明），所以一起去掉了。
    这条路本来就是「一个广告组一个广告」，用不到它。
    """
    from src.pages.common import wait_until

    def changed():
        step = current_step(page)
        if step is None or step == prev_step:
            return None
        return step

    return wait_until(page, changed, timeout_seconds=timeout_seconds)


def walk_and_fill_ads(page, fill_one, expected_ads, log=None, max_steps=None):
    """从当前位置沿「继续」走到链条末尾，在每个【空的】广告层调用 fill_one。

    fill_one(index) -> str | None
        填第 index 个广告（0 起算）。返回一句警告文字，或者 None 表示没问题。
        素材去重由调用方通过 creative_usage 保证，这里不掺和。

    expected_ads
        预期要填几个广告（广告组数量 × 每组 1 个广告）。只用于日志和最后的校验：
        少填了会作为警告报出来，而不是默默当成成功。

    返回 (填了几个广告, [警告…])。

    走到最后一个广告层时右下角只剩「全部发布」，这里就停下并把发布留给调用方——
    发布的等待/重试逻辑在 builder 里，不该塞进导航函数。
    """
    from src.pages.common import robust_click

    def say(msg):
        if log:
            log(msg)
        else:
            print(msg, flush=True)

    warnings = []
    # 上限按预期站数给足余量：每个广告组两站（广告组层 + 广告层），再留 12 站
    # 应付平台多插一站或某次「继续」没生效。到上限就报错，绝不无限点下去。
    if max_steps is None:
        max_steps = expected_ads * 3 + 12

    filled = 0
    step = current_step(page)
    if step is None:
        raise ValueError(
            "沿「继续」走链条之前读不出当前在哪一层"
            "（既没看到「广告组名称」也没看到「广告名称」）。"
            f"当前地址: {page.url[:120]}"
        )

    # 当前这一站的内容处理过了没有。必须有这个标志：某次「继续」没生效时我们会停在
    # 原地重试，如果不记住「这一站已经处理过」，重试就会给同一个广告【再加一遍素材】。
    handled = False

    for n in range(max_steps):
        if not handled:
            if step == "ad":
                if filled >= expected_ads:
                    # 已经填够了。正常不该走到这里（链条上的广告层数量就等于
                    # expected_ads），走到了说明平台多插了一站，宁可跳过也别多加素材。
                    say(f"        [链条] 第{n + 1}站又是广告层，但 {expected_ads} 个"
                        "已经填够了，跳过（不重复加素材）")
                else:
                    say(f"        [链条] 第{n + 1}站是广告层，开始挑第 {filled + 1}/"
                        f"{expected_ads} 个广告的素材")
                    issue = fill_one(filled)
                    filled += 1
                    if issue:
                        warnings.append(issue)
            elif step == "adgroup":
                # 副本把广告组层的设置（小游戏 / ROAS / 地域 / 预算）全继承了，
                # 这一站什么都不用改，直接往下走。
                say(f"        [链条] 第{n + 1}站是广告组层（副本已继承设置），直接继续")
            handled = True

        btn = find_continue_button(page)
        if btn is None:
            # 链条末尾：确认一下真的是「只剩全部发布」，而不是按钮还没渲染出来。
            # 这两件事必须分清——把「还没加载完」当成末尾，会漏掉后面所有广告。
            if find_publish_button(page) is None:
                from src.pages.common import wait_until

                again = wait_until(page, lambda: find_continue_button(page),
                                   timeout_seconds=30)
                if again is not None:
                    btn = again
                else:
                    raise ValueError(
                        f"第{n + 1}站上既没有「继续」也没有「全部发布」，"
                        "分不清是走到末尾还是页面没加载完，已中止。"
                        f"当前层级={step}，地址: {page.url[:120]}"
                    )
            if btn is None:
                say(f"        [链条] 第{n + 1}站没有「继续」、只有「全部发布」，"
                    f"链条走完，共填了 {filled} 个广告")
                break

        prev = step
        robust_click(page, btn, timeout=15000)
        page.wait_for_timeout(1500)
        nxt = _wait_next_step(page, prev, timeout_seconds=90)
        if nxt is None:
            # 90 秒都没看出层级翻转。可能是这一次「继续」没生效，也可能页面渲染慢。
            # 这里【不能】把当前状态当成新的一站往下走：现在判断「填过没有」靠的是
            # 计数，把同一个广告层数成两站就会给它加两遍素材。所以停在原地重试，
            # 由 max_steps 兜底。
            cur = current_step(page)
            if cur is None:
                raise ValueError(
                    "点了「继续」之后读不出在哪一层，已中止，避免往错误的广告里加素材。"
                    f"当前地址: {page.url[:120]}"
                )
            step = cur
            if cur == prev:
                # 原地没动：保持 handled=True，下一轮只重新点一次「继续」，
                # 【不再】重复处理这一站的内容
                say(f"        [链条] 点了「继续」但 90 秒内层级没变（还是 {cur}），"
                    "只重新点「继续」，不重复处理这一站")
                continue
            # 层级其实变了，只是 _wait_next_step 没等到 —— 当成新的一站处理
            handled = False
        else:
            step = nxt
            handled = False
    else:
        raise ValueError(
            f"沿「继续」走了 {max_steps} 站还没走到末尾（已填 {filled}/{expected_ads} "
            "个广告）。为免无限点下去已中止，请手动到后台看这个计划的状态。"
        )

    if filled < expected_ads:
        warnings.append(
            f"预期填 {expected_ads} 个广告，实际只填了 {filled} 个"
            "（链条提前走完了）。请手动检查这个计划里有没有空广告。"
        )
    return filled, warnings
