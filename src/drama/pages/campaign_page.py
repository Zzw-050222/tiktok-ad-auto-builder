"""短剧商品库 —— 计划（推广系列）层。

和小游戏的差别只有一处：多一个「设置商品库推广系列」开关，默认关闭，必须打开。
其余步骤（打开后台、选「TikTok 即时增长」、填名称和预算、点继续）与小游戏完全
相同，直接复用 src/pages/campaign_page.py，不复制一份——那些函数里塞满了今天踩
出来的账号差异处理，复制等于以后每个 bug 要修两遍。
"""

# 商品库开关所在的区块。id 是语义化的、没有随机后缀，比旁边那些带哈希的
# data-testid（catalog-campaign-index-v2-9hyftC）可靠得多。
DASHBOARD_URL = "https://ads.tiktok.com/i18n/dashboard"

# 「创建广告」按钮在两种语言下的文案。用它判断当前 Ads Manager 是中文还是英文。
_ZH_CREATE_AD = "创建广告"
_EN_CREATE_AD = "Create ad"


def _ui_language(page):
    """判断当前 Ads Manager 界面是中文、英文，还是都没加载出来。

    返回 'zh' / 'en' / None。
    """
    for name, lang in ((_ZH_CREATE_AD, "zh"), (_EN_CREATE_AD, "en")):
        try:
            btn = page.get_by_role("button", name=name)
            for i in range(min(btn.count(), 6)):
                if btn.nth(i).is_visible():
                    return lang
        except Exception:
            pass
    return None


def ensure_chinese_ui(page, advertiser_id, attempts=4):
    """确保 Ads Manager 是中文界面，否则整条流程的中文定位全部失效。

    2026-08-16 实测：同一个账号、同一个 profile，Ads Manager 在多次运行之间【中文
    和英文来回切】——账户选择页 /i18n/home 始终是中文（右上角写着「中文（简体）」），
    但 Ads Manager 有时渲染成英文（Welcome to Ads Manager / Create ad / Dashboard）。
    启动参数里的 locale="zh-CN" 和 Accept-Language 都不能保证它听话。

    英文状态下不是「少一个按钮」而是【整页文案都不是中文】，后面每一步定位都会失败，
    所以必须在最开头拦住，而不是让它带着错误语言往下跑。

    做法：进 dashboard 看语言；是英文就重新加载再看（实测它是在两种状态间来回切，
    重载往往就回到中文）；试满 attempts 次仍是英文就明确报错，让人去手动切语言，
    而不是硬闯下去产生一堆莫名其妙的超时。
    """
    from src.pages.common import wait_until

    url = f"{DASHBOARD_URL}?aadvid={advertiser_id}"
    seen = []
    for attempt in range(attempts):
        page.goto(url, wait_until="domcontentloaded", timeout=60000)

        lang = wait_until(page, lambda: _ui_language(page), timeout_seconds=45)
        seen.append(lang)
        if lang == "zh":
            return True
        if lang is None:
            raise TimeoutError(
                "进入 Ads Manager 后 45 秒内既没看到「创建广告」也没看到「Create ad」，"
                "页面可能没加载出来，或者当前登录账号没有这个广告主的权限"
                "（无权限时 TikTok 会跳到 /i18n/forbidden）。"
                f"当前地址: {page.url[:100]}"
            )

        # 是英文 —— 去 /i18n/home 把语言切回中文再回来。
        # 这一步不能省：实测这个账号的语言【会自己弹回英文】，切过一次不代表下次还是
        # 中文，所以每次跑之前都要确认并在需要时切回来，而不是让人手动兜底。
        from src.drama.set_language import switch_to_chinese

        ok = switch_to_chinese(page, verbose=False)
        if not ok:
            raise ValueError(
                "Ads Manager 是英文界面，尝试自动切换成中文也失败了。\n"
                "语言按钮的定位是 .ac-lang-avater__lang-btn（在 /i18n/home 右上角，"
                "显示的是【当前】语言，所以不能按文字找）。\n"
                "请手动在那里切成「中文（简体）」后重跑。"
            )
        page.wait_for_timeout(1500)

    raise ValueError(
        f"Ads Manager 连续 {attempts} 次都是英文界面（每次检测结果: {seen}），"
        "中间已经尝试过自动切换语言。\n"
        "整套定位都依赖中文文案，英文界面下每一步都会失败，所以在这里就停住，"
        "而不是带着错误语言往下跑、产生一堆莫名其妙的超时。\n"
        "请手动在 /i18n/home 右上角把语言切成「中文（简体）」后重跑。"
    )


CATALOG_SECTION_ID = "catalog-campaign"

# 必须限定在这个区块里找开关。2026-08-16 实测整页有 4 个 role="switch"，其中一个
# 是左上角的「推广系列已启用」——用页面级选择器点第一个，会把整个推广系列停用掉。
CATALOG_SWITCH_CSS = f'#{CATALOG_SECTION_ID} [role="switch"]'

# 开关的「已打开」状态同时体现在三个地方（实测点击前后逐一对比得出）：
#   class                : 'vi-switch'      -> 'vi-switch is-checked'
#   aria-checked         : （属性不存在）    -> 'true'      ← 关闭时是【没有这个属性】
#   data-tea-model_value : '0'              -> '1'
# 三个一起判断，任一命中即视为打开，这样 TikTok 改掉其中一个也还能工作。
_ON_CLASS_MARKER = "is-checked"


def _switch_is_on(switch):
    """读开关当前状态。读不出来返回 None —— 调用方必须区分「确定是关」和「读不出」。"""
    # 注意不要写成 `get_attribute("class") or ""`：那样 None 会被转成空字符串，
    # 下面「三个属性全都读不到 -> 返回 None」的判断就永远不成立，读不出状态会被
    # 当成「确定是关闭」，进而去点开关——而那正是可能把已打开的关掉的情形。
    try:
        cls = switch.get_attribute("class")
    except Exception:
        cls = None
    try:
        aria = switch.get_attribute("aria-checked")
    except Exception:
        aria = None
    try:
        tea = switch.get_attribute("data-tea-model_value")
    except Exception:
        tea = None

    if cls is None and aria is None and tea is None:
        return None
    if cls and _ON_CLASS_MARKER in cls:
        return True
    if aria == "true":
        return True
    if tea == "1":
        return True
    # class 读到了但没有 is-checked，或 tea 明确是 '0' —— 确定是关闭
    if cls is not None or tea == "0":
        return False
    return None


def enable_catalog_campaign(page, timeout_seconds=60):
    """打开计划层的「设置商品库推广系列」开关（默认关闭）。已经打开则不动它。

    开关和按钮不同：按钮多点一次最多浪费时间，开关多点一次会【关掉】它，而且不会
    报任何错。所以这里是「先读状态 -> 需要才点 -> 点完必须确认变成打开 -> 没变就
    重试 -> 仍不对就明确报错」，绝不无脑点一下就往下走。
    """
    from src.pages.common import wait_until

    def section_ready():
        loc = page.locator(CATALOG_SWITCH_CSS)
        if loc.count() == 0:
            return None
        return loc.first if loc.first.is_visible() else None

    switch = wait_until(page, section_ready, timeout_seconds=timeout_seconds)
    if not switch:
        raise ValueError(
            f"等了 {timeout_seconds} 秒没找到「设置商品库推广系列」开关"
            f"（选择器 {CATALOG_SWITCH_CSS}）。这个账号可能不支持商品库推广系列，"
            "或者页面结构又变了。"
        )

    state = _switch_is_on(switch)
    if state is True:
        return False  # 本来就是打开的，没动它

    if state is None:
        raise ValueError(
            "读不出「设置商品库推广系列」开关的状态（class / aria-checked / "
            "data-tea-model_value 都拿不到）。不确定状态就点开关有把它关掉的风险，已中止。"
        )

    switch.scroll_into_view_if_needed(timeout=5000)
    for attempt in range(4):
        switch.click(timeout=10000)
        page.wait_for_timeout(800)

        # 重新取一次元素再读状态：点击后组件可能重新渲染，旧引用未必反映新状态
        fresh = wait_until(page, section_ready, timeout_seconds=15)
        if fresh and _switch_is_on(fresh) is True:
            page.wait_for_timeout(500)
            return True
        page.wait_for_timeout(1200)

    raise ValueError(
        "点了 4 次「设置商品库推广系列」开关，状态始终没有变成打开。"
        "不要重跑硬闯——先手动确认这个账号是否允许开启商品库推广系列。"
    )
