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


def fill_drama_ad_copy(page, ads_text):
    """填文案，填完【回读确认】。占位文字实测和小游戏一致（「输入文案」）。

    回读这一步不能省：这一页输入框不止一个，填错地方不会报任何错。
    本项目反复吃过「验证动作而不是验证结果」的亏（点了就当成功、改了就当对）。
    """
    from src.pages.ad_page import fill_ad_copy

    fill_ad_copy(page, ads_text)
    got = _read_value(page, page.get_by_placeholder("输入文案"))
    if got is not None and got.strip() != (ads_text or "").strip():
        raise ValueError(f"文案填完读回的是 {got[:60]!r}，期望 {ads_text[:60]!r}")


def fill_drama_minis_url(page, url):
    """填 TikTok Minis URL，填完【回读确认】。占位实测一致（https://www.tiktok.com/minis/）。"""
    from src.pages.ad_page import fill_landing_url

    fill_landing_url(page, url)
    got = _read_value(page, page.get_by_placeholder("https://www.tiktok.com/minis/"))
    if got is not None and got.strip() != (url or "").strip():
        raise ValueError(f"Minis URL 填完读回的是 {got!r}，期望 {url!r}")


def _read_value(loc_page, loc):
    """读输入框当前的值。读不出来返回 None（区别于「读到了空字符串」）。"""
    try:
        for i in range(min(loc.count(), 5)):
            el = loc.nth(i)
            if el.is_visible():
                return el.input_value(timeout=3000)
    except Exception:
        return None
    return None
