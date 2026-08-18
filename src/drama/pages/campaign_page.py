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


CAMPAIGN_LIST_URL = "https://ads.tiktok.com/i18n/manage/campaign"


def _newest_campaign_link(page, campaign_name):
    """计划列表里名字完全等于 campaign_name、且【最靠上】的那个链接。

    两个条件缺一不可，都是实测决定的：
      * 不能只按「点第一行」——点错行会把广告组建进【别的计划】里，而且新流程是
        边建边真发布，错了就是真花钱。
      * 不能只按名字——同名计划真的存在（探针在列表里看到同一个计划名出现两次，
        因为同一份表跑过两遍），必须取最靠上的那个才是刚建的。

    定位来自真实 DOM：计划名是 role="link"、class 含 KsLink 的元素，
    自定义标签名（ks-link-1-1-1w）每次加载都随机，不能用。名字在 DOM 里是
    【完整的】，页面上看到的省略号只是 CSS 截断，所以可以精确比对。
    """
    want = (campaign_name or "").strip()
    if not want:
        return None
    loc = page.locator('[role="link"]')
    best, best_y = None, None
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(min(n, 80)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            if (el.inner_text() or "").strip() != want:
                continue
            box = el.bounding_box()
            if not box:
                continue
            if best_y is None or box["y"] < best_y:
                best, best_y = el, box["y"]
        except Exception:
            continue
    return best


_PUBLISH_BUTTON_NAMES = ("全部发布", "发布")


def _first_visible_button(page, name, limit=5):
    btn = page.get_by_role("button", name=name, exact=True)
    try:
        n = btn.count()
    except Exception:
        return None
    for i in range(min(n, limit)):
        try:
            if btn.nth(i).is_visible():
                return btn.nth(i)
        except Exception:
            continue
    return None


def _click_publish(page):
    """点发布按钮。返回点中的按钮名，一个都没有就返回 None。

    两个名字都试：主流程上是「全部发布」，报错弹层修复之后有时只剩「发布」。
    """
    for name in _PUBLISH_BUTTON_NAMES:
        btn = _first_visible_button(page, name)
        if btn is not None:
            from src.pages.common import robust_click

            robust_click(page, btn, timeout=15000)
            return name
    return None


def _visible_button_names(page, limit=25):
    """当前页面上所有可见按钮的文字。用于「发布卡住了」时看清实际有哪些按钮。"""
    out = []
    try:
        btn = page.get_by_role("button")
        for i in range(min(btn.count(), limit)):
            try:
                if not btn.nth(i).is_visible():
                    continue
                t = (btn.nth(i).inner_text() or "").replace("\n", " ").strip()
                if t:
                    out.append(t[:24])
            except Exception:
                continue
    except Exception:
        pass
    return out


def _dialog_texts(page, limit=3):
    """当前可见弹层/对话框里的文字，截断后返回。"""
    out = []
    try:
        loc = page.locator('[role="dialog"]:visible, [class*="modal"]:visible')
        for i in range(min(loc.count(), limit)):
            try:
                t = (loc.nth(i).inner_text() or "").replace("\n", " ").strip()
                if t:
                    out.append(t[:180])
            except Exception:
                continue
    except Exception:
        pass
    return out


def publish_all(page, timeout_seconds=300, max_fix_rounds=5):
    """点「全部发布」并等到真的发布完（页面自己跳回计划列表）。

    平台有个已知的概率性 bug（使用者实测）：一个广告组下的广告数量大于 1 时，
    点发布有概率弹出报错框。处理办法是点那个框右下角的「修复」，然后再点发布；
    还报错就再重复一次。所以这里是「点发布 -> 看到修复按钮就点它 -> 再点发布」
    的循环，最多 max_fix_rounds 轮。

    绝不要自己强行跳转去计划列表：中途跳走会打断发布，计划实际不会上线。
    慢没关系，早跳不行。
    """
    from src.pages.common import wait_until

    for round_no in range(max_fix_rounds + 1):
        clicked = _click_publish(page)
        if clicked is None:
            raise ValueError(
                "找不到「全部发布」或「发布」按钮，无法发布。"
                f"当前地址: {page.url[:120]}"
            )

        def outcome():
            # 顺序要紧：已经跳回列表就算成功，其次才看有没有报错要修
            if "manage/campaign" in page.url:
                return "done"
            if _first_visible_button(page, "修复") is not None:
                return "fix"
            try:
                loc = page.get_by_text("广告创建中", exact=False)
                if loc.count() > 0 and loc.first.is_visible():
                    return "publishing"
            except Exception:
                pass
            return None

        what = wait_until(page, outcome, timeout_seconds=90)

        if what == "fix":
            fix = _first_visible_button(page, "修复")
            print(f"          [发布] 第{round_no + 1}轮弹出报错，点「修复」", flush=True)
            if fix is not None:
                from src.pages.common import robust_click

                robust_click(page, fix, timeout=15000)

            # 必须等这个窗口【真的消失】再去点发布。
            # 不能点完修复就立刻点发布：弹层还在时它会盖住发布按钮，点了不生效，
            # 白耗一轮重试次数。使用者的说法就是「点修复然后消失之后再点发布」。
            gone = wait_until(
                page,
                lambda: True if _first_visible_button(page, "修复") is None else None,
                timeout_seconds=60,
            )
            if gone:
                print("          [发布] 修复窗口已消失，重新点发布", flush=True)
            else:
                print("          [发布] 修复窗口点了之后 60 秒还没消失，"
                      f"当前可见按钮: {_visible_button_names(page)}", flush=True)
            page.wait_for_timeout(1500)
            continue

        if what is None:
            # 既没跳走、也没报错框、也没看到进度提示。
            # 「修复」这个按钮名是按使用者的描述写的，还没在真实报错场景下验证过；
            # 万一实际文字不是这两个字，就会走到这里白等。所以把【当前可见的按钮和
            # 弹层文字】打出来——下次一出现就能立刻看出该认什么，不用再猜。
            print(f"          [发布] 第{round_no + 1}轮点完没有明确结果。"
                  f"当前可见按钮: {_visible_button_names(page)}", flush=True)
            print(f"          [发布] 弹层文字: {_dialog_texts(page)}", flush=True)
            page.wait_for_timeout(2000)
            continue

        # publishing 或 done：等页面【自己】跳回计划列表
        page.wait_for_url(
            lambda url: "manage/campaign" in url, timeout=timeout_seconds * 1000
        )
        wait_until(page, lambda: "manage/campaign" in page.url, timeout_seconds=30)
        page.wait_for_timeout(1500)
        return

    raise ValueError(
        f"点了 {max_fix_rounds + 1} 轮发布（每次报错都点过「修复」），"
        "页面始终没有跳回计划列表。请手动到后台看这个计划的状态，别重复跑。"
    )


def open_campaign_and_create_adgroup(
    page, advertiser_id, campaign_name, settle_seconds=5, timeout_seconds=120
):
    """发布完之后，回到刚建的那个计划里【再建一个广告组】。

    新流程（使用者指定）：不复制广告组、也不复制广告，而是
        建一个 -> 发布 -> 回计划列表 -> 点刚建的计划 -> 点右上「创建」-> 再建一个

    发布完页面会自己停在计划列表。使用者提醒：偶尔会卡一下，所以先缓冲几秒再点，
    别在列表还没刷新出来的时候就去点第一行。
    """
    from src.pages.common import robust_click, wait_until

    if "manage/campaign" not in page.url:
        page.goto(
            f"{CAMPAIGN_LIST_URL}?aadvid={advertiser_id}",
            wait_until="domcontentloaded",
            timeout=60000,
        )
    # 缓冲：列表可能还在刷新，刚发布的计划未必已经排到最上面
    page.wait_for_timeout(int(settle_seconds * 1000))

    link = wait_until(
        page,
        lambda: _newest_campaign_link(page, campaign_name),
        timeout_seconds=timeout_seconds,
    )
    if link is None:
        raise ValueError(
            f"在计划列表里找不到名字完全等于 {campaign_name!r} 的计划。"
            "没找到就【不点】——盲点第一行有可能把广告组建进别的计划里，"
            "而这条流程是边建边真发布的。"
        )
    robust_click(page, link, timeout=10000)

    if not wait_until(page, lambda: "manage/adgroup" in page.url, timeout_seconds=90):
        raise ValueError(
            f"点了计划 {campaign_name!r} 之后没能进入广告组列表，当前地址: {page.url[:120]}"
        )

    def create_btn():
        b = page.get_by_role("button", name="创建", exact=True)
        for i in range(min(b.count(), 5)):
            if b.nth(i).is_visible():
                return b.nth(i)
        return None

    btn = wait_until(page, create_btn, timeout_seconds=90)
    if not btn:
        raise ValueError("广告组列表页上没找到右上角的「创建」按钮")
    robust_click(page, btn, timeout=10000)

    if not wait_until(
        page, lambda: "create/spc-adgroup" in page.url, timeout_seconds=120
    ):
        raise ValueError(
            f"点「创建」之后没能进入广告组创建页，当前地址: {page.url[:120]}"
        )
    wait_until(
        page,
        lambda: page.get_by_text("广告组名称", exact=True).count() > 0,
        timeout_seconds=90,
    )
    page.wait_for_timeout(1500)
