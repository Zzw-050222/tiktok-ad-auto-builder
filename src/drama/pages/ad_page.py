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
"""


def select_drama_creatives(page, series_name, count, used_ids=None):
    """在广告层按剧名搜素材并挑 count 个。返回 (选中数量, 是否绕回头复用过)。

    用法上和小游戏一致：used_ids 传同一个 set 一路传下去，就能做到同账号同商品下
    跨广告不重复用素材，库用完了才开始复用。
    """
    from src.pages.ad_page import select_creative_materials, wait_ad_page_ready

    wait_ad_page_ready(page)
    return select_creative_materials(
        page, search_term=series_name, count=count, used_ids=used_ids
    )
