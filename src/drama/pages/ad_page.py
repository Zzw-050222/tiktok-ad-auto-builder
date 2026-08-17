"""短剧商品库 —— 广告层。

创意素材这块和小游戏【完全一样】（使用者截图逐项对过：「自动选择」框、顶层
「添加创意素材」按钮、「创意素材库」tab、「按名称或ID搜索」搜索框、素材一次
30 个、滚到底才加载下一批），所以直接复用 src/pages/ad_page 里的
select_creative_materials，不复制一份——那个函数里装着按素材身份去重、库用完后
绕回头复用、滚动容器诊断等一堆实测踩出来的处理，复制等于以后每个 bug 要修两遍。

搜索词用【剧名】。使用者的说法是「搜索计划名称的第一个字段」，这里不直接按
'-' 切计划名，而是用 series_lookup 从商品库表里匹配出来的剧名：商品库里有 4 个
剧名自身就带连字符（The Seventh-Year Intern、Married to My Ex-Fiance、
The Ex-Wife Who Drank the Moon、The Stand-In Brid），按 '-' 切会把剧名切断。
两种算法在不带连字符的剧名上结果相同。

文案和落地页链接同样照搬（占位文字实测一致：「输入文案」、
`https://www.tiktok.com/minis/`），值取自表格的 ads_text 和 TT Mini URL。

**身份（TikTok 账号）不要动**：短剧这条流程里选完素材后 TikTok 会自动填好
（实测显示 WeShorts_US），页面上还写着「自定义身份已不再可用」。小游戏那边的
select_identity 是按表格里的 Identity_ID / TikTok Account ID 去手动挑的，
这里【不要】调用它——去点一个已经选好的下拉，只会有把它改错的风险。

也不要写「只读确认身份」那种诊断：试过两版按标题往上找容器再抠文字的写法，
分别读出「身份（TikTok 账号）」和「刷新」，都不是账号名。这个项目的规律是
猜出来的定位基本都要返工，而流程本身并不依赖这个值——要看状态就看截图。
"""


def select_drama_creatives(page, series_name, count, used_ids=None):
    """在广告层按剧名搜素材并挑 count 个。返回 (选中数量, 是否绕回头复用过)。

    用法上和小游戏一致：used_ids 传同一个 set 一路传下去，就能做到同账号同商品下
    跨广告不重复用素材，库用完了才开始复用。
    """
    from src.pages.ad_page import select_creative_materials, wait_ad_page_ready

    wait_ad_page_ready(page)
    # 比小游戏更有耐心：使用者明确要求「宁可慢，也要保证不选重复」。
    # 素材库一次给 30 个，滚到底才加载下一批，新一批出现后 DOM 还在补，
    # 所以多等（40 秒）并且每批加载完静置 3 秒再开始选。
    return select_creative_materials(
        page, search_term=series_name, count=count, used_ids=used_ids,
        batch_wait_seconds=40, batch_settle_ms=3000,
    )


def _first_visible_input(page, locator, what, timeout_seconds=60):
    """取第一个【可见】的匹配输入框，并返回那个具体元素。

    为什么不能用 .first：一个广告组里有多个广告时，DOM 里会同时存在好几个占位符
    相同的输入框（当前广告的可见，其他广告的隐藏）。.first 拿到的可能是隐藏的那个，
    fill() 填进去页面上什么都不会变。

    实测就是这么错的：URL 用 field.first.fill() 填到了隐藏的框上，而回读时又是
    「找第一个可见的」——两者不是同一个元素，于是【回读通过、页面上却是空的】，
    平台在发布时报缺少 URL。加了验证反而把问题掩盖了。
    所以填和读必须锁定同一个元素，这个函数就是用来拿到那个元素的。
    """
    from src.pages.common import wait_until

    def pick():
        try:
            n = locator.count()
        except Exception:
            return None
        for i in range(min(n, 12)):
            el = locator.nth(i)
            try:
                if el.is_visible():
                    return el
            except Exception:
                continue
        return None

    el = wait_until(page, pick, timeout_seconds=timeout_seconds)
    if el is None:
        raise ValueError(f"等了 {timeout_seconds} 秒没找到可见的{what}")
    return el


def _commit(page, el):
    """让输入框失焦，把值真正提交给组件。

    使用者实测发现的：填完 URL 之后必须点一下框附近，值才会被保存；
    而且不能点左侧的广告列表——点那里不保存。原因是 fill() 只把值写进 DOM，
    组件是在 blur / change 时才把值收进自己的状态，平台发布时读的是组件状态。

    这也是为什么【回读验证检测不出这个问题】：input_value() 读的是 DOM 里的值，
    一直是对的，但组件里是空的，所以发布时平台报缺少 URL。加了验证反而给了
    假的安全感——这个坑值得记住：回读只能证明「写进去了」，不能证明「被接住了」。

    用 Tab 键失焦而不是去点某个坐标：效果和点空白处一样，但不会误点到别的控件
    （尤其是左侧列表）上。再补一次显式的 change + blur 事件兜底。
    """
    try:
        page.keyboard.press("Tab")
    except Exception:
        pass
    page.wait_for_timeout(500)
    try:
        el.evaluate("""e => {
          e.dispatchEvent(new Event('input', {bubbles: true}));
          e.dispatchEvent(new Event('change', {bubbles: true}));
          if (e.blur) e.blur();
        }""")
    except Exception:
        pass
    page.wait_for_timeout(400)


def _fill_and_verify(page, locator, value, what):
    """填一个输入框并回读确认——填和读【同一个元素】，见 _first_visible_input。"""
    el = _first_visible_input(page, locator, what)
    try:
        el.scroll_into_view_if_needed(timeout=8000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    try:
        el.click(timeout=8000)
    except Exception:
        pass
    el.fill("")
    el.fill(str(value))
    page.wait_for_timeout(500)
    _commit(page, el)

    got = None
    try:
        got = el.input_value(timeout=3000)
    except Exception:
        pass
    if got is not None and got.strip() != str(value).strip():
        # 再填一次：有时组件把第一次输入吞掉了
        el.fill("")
        el.fill(str(value))
        page.wait_for_timeout(600)
        _commit(page, el)
        try:
            got = el.input_value(timeout=3000)
        except Exception:
            got = None
    if got is not None and got.strip() != str(value).strip():
        raise ValueError(
            f"{what}填完读回的是 {str(got)[:80]!r}，期望 {str(value)[:80]!r}"
        )


def fill_drama_ad_copy(page, ads_text):
    """填文案，填完回读确认（填和读同一个元素）。占位文字「输入文案」。"""
    _fill_and_verify(page, page.get_by_placeholder("输入文案"), ads_text, "文案")


def fill_drama_minis_url(page, url):
    """填 TikTok Minis URL，填完回读确认（填和读同一个元素）。

    这里必须自己找「第一个可见的」输入框，不能复用小游戏的 fill_landing_url——
    那个函数用的是 .first，在一个广告组有多个广告时会填到隐藏的框上去。
    """
    _fill_and_verify(
        page,
        page.get_by_placeholder("https://www.tiktok.com/minis/"),
        url,
        "TikTok Minis URL",
    )


