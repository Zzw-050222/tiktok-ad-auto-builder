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


def _visible_input_value(page, placeholder):
    """某个占位符对应的【可见】输入框里现在的值；框不在或读不出返回 None。"""
    el = _first_visible(page.get_by_placeholder(placeholder), limit=10)
    if el is None:
        return None
    try:
        return el.input_value(timeout=3000)
    except Exception:
        return None


def ad_already_filled(page):
    """这个广告层是不是已经被我们填过了（文案或落地页非空）。

    这个判断是整条链的安全绳。链条会把【整个计划】的广告组都走一遍，而不只是
    当前这一行的；一个计划里有多行、或者因为点击没生效在同一站转了一圈时，
    都可能再次走到已经填好的广告上。没有这道判断就会往同一个广告里【重复添加
    素材】——那是静默的错，发布出去才发现。

    只认「有没有值」，不认「值对不对」：不同行的文案本来就不一样，
    而这里要回答的问题只是「这个广告轮到我填了吗」。
    """
    for placeholder in (_COPY_PLACEHOLDER, _URL_PLACEHOLDER):
        v = _visible_input_value(page, placeholder)
        if v and v.strip():
            return True
    return False


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
    """点完「继续」之后，等页面真的换到下一站。

    「换到下一站」有两种表现，都要认：
      * 层级变了（广告组层 <-> 广告层）—— 链条正常交替时就是这样
      * 层级没变，但这个广告层是空的 —— 一个广告组下有多个广告时会出现
        广告层 -> 广告层，层级不变但确实换了一个广告

    等不到就返回 None，由调用方决定是报错还是接着看当前状态（当前状态本身
    是安全的：填过的广告会被 ad_already_filled 挡住）。
    """
    from src.pages.common import wait_until

    def changed():
        step = current_step(page)
        if step is None:
            return None
        if step != prev_step:
            return step
        if step == "ad" and not ad_already_filled(page):
            return step
        return None

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

    for n in range(max_steps):
        if step == "ad":
            if ad_already_filled(page):
                say(f"        [链条] 第{n + 1}站是广告层，但内容已经填过，跳过")
            else:
                say(f"        [链条] 第{n + 1}站是广告层，开始填第 {filled + 1}/"
                    f"{expected_ads} 个广告")
                issue = fill_one(filled)
                filled += 1
                if issue:
                    warnings.append(issue)
        elif step == "adgroup":
            # 副本把广告组层的设置（小游戏 / ROAS / 地域 / 预算）全继承了，
            # 这一站什么都不用改，直接往下走。
            say(f"        [链条] 第{n + 1}站是广告组层（副本已继承设置），直接继续")

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
            # 没等到明确的变化。不硬失败：当前状态本身是安全的（填过的广告会被
            # ad_already_filled 挡住），继续往下走，真正走不动会撞上 max_steps。
            nxt = current_step(page)
            say(f"        [链条] 点了「继续」但 90 秒内没看出层级变化"
                f"（现在读到 {nxt}），按当前状态继续")
            if nxt is None:
                raise ValueError(
                    "点了「继续」之后读不出在哪一层，已中止，避免往错误的广告里填内容。"
                    f"当前地址: {page.url[:120]}"
                )
        step = nxt
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
