def start_new_campaign(page, advertiser_id: str):
    page.goto(
        f"https://ads.tiktok.com/i18n/dashboard?aadvid={advertiser_id}",
        wait_until="domcontentloaded",
        timeout=60000,
    )
    create_btn = page.get_by_role("button", name="创建广告")
    create_btn.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(500)
    create_btn.click(timeout=10000)
    # some accounts have a hover-preview panel that duplicates this label, same
    # issue as the "TikTok 即时增长" objective text - .first avoids strict mode
    page.get_by_text("推广目标", exact=True).first.wait_for(state="visible", timeout=30000)
    page.wait_for_timeout(500)


def select_native_growth_objective(page):
    from src.pages.common import wait_until

    def details_visible():
        loc = page.get_by_text("推广系列详情", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    def visible_radio():
        # 沿用 exact=True 的字符串匹配——它是实测能命中的，不要换成正则。
        # 唯一的改动是【不再盲取 .first】：本函数原有的注释就写了「有账号存在悬浮
        # 预览面板复制了这个标签」，一旦 .first 恰好是那个隐藏副本，就会死等到超时，
        # 而页面上明明有一个可见的。遍历所有匹配挑出真正可见的那一个。
        loc = page.get_by_text("TikTok 即时增长", exact=True)
        for i in range(min(loc.count(), 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    # 15 秒 -> 60 秒：这个平台会卡到接近一分钟（见 common.wait_until 的注释），
    # 项目里别处早就统一成 60 秒了，这里是漏网的一处。
    #
    # 注意这里【刻意不调用 dismiss_popups】：它会点击任何可见的「关闭」按钮，而在
    # 推广目标这一页上「关闭」是关掉整个创建面板的，一点就把要选的内容关没了
    # （2026-08-14 亲手踩过）。也刻意用普通 .click() 而不是 robust_click：单选项要的
    # 是真实点击，robust_click 会升级到 JS 直接派发，对单选项不如真实点击可靠。
    for attempt in range(5):
        radio = wait_until(page, visible_radio,
                           timeout_seconds=60 if attempt == 0 else 20)
        if not radio:
            raise TimeoutError("等了 60 秒还没看到可见的「TikTok 即时增长」推广目标")
        radio.click(timeout=10000)
        if wait_until(page, details_visible, timeout_seconds=12):
            break
        if attempt == 4:
            raise TimeoutError("选完'TikTok 即时增长'后一直没看到'推广系列详情'")
    page.wait_for_timeout(500)


def _input_after_label(page, label_text: str):
    return page.locator(
        f"xpath=//*[normalize-space(text())='{label_text}']/following::input[1]"
    )


def fill_campaign_details(page, campaign_name: str, daily_budget):
    """Fills campaign name always. Budget is only set here if this account's
    campaign-creation flow actually has a budget section at this level - a
    significant minority of accounts move budget down to the ad-group level
    instead (confirmed live: no 预算策略/推算系列预算 section here at all, just
    name + split-test toggle + PO number). Returns True if budget was set here,
    False if this account needs it filled at the ad-group level instead
    (see adgroup_page.fill_adgroup_budget_if_present).
    """
    from src.pages.common import wait_until

    # 15 秒 -> 60 秒：与项目里其它地方统一（见 common.wait_until 的注释，这个平台
    # 会卡到接近一分钟）。注意下面 budget_radio_visible 的 10 秒是【刻意】的短超时，
    # 用来区分「这个账号类型压根没有预算区」和「还在加载」，别跟着一起改。
    name_input = _input_after_label(page, "推广系列名称")
    name_input.wait_for(state="visible", timeout=60000)
    name_input.fill("")
    name_input.fill(campaign_name)

    # don't wait the full 60s here - if it's genuinely absent for this account
    # type, waiting longer never helps; ~10s (per live-confirmed behavior) is
    # enough to tell "still loading" apart from "just isn't here"
    def budget_radio_visible():
        loc = page.get_by_text("推广系列预算", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    budget_radio = wait_until(page, budget_radio_visible, timeout_seconds=10)
    if not budget_radio:
        page.wait_for_timeout(500)
        return False

    budget_radio.first.click(timeout=10000)
    page.wait_for_timeout(300)

    budget_input = page.get_by_placeholder("20.00 以上")
    budget_input.wait_for(state="visible", timeout=60000)
    budget_input.fill(str(daily_budget))
    page.wait_for_timeout(500)
    return True


def add_new_ad_group(page, campaign_name: str):
    """Click the campaign row's '+' icon in the left sidebar to add a fresh, blank
    ad group to the campaign (distinct from duplicating an existing one - use this
    when a new row has genuinely different data, not a repeat of the last row's).
    """
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    row = page.locator('[data-testid="creation_1nn_sidebar_campaign_node"]').filter(
        has_text=campaign_name
    )
    row.first.scroll_into_view_if_needed(timeout=10000)

    plus_icon = row.first.locator("ks-icon-plus-small")
    for attempt in range(3):
        row.first.hover(timeout=10000)
        page.wait_for_timeout(400)
        try:
            plus_icon.click(timeout=5000, force=True)
        except Exception:
            pass
        page.wait_for_timeout(800)
        # a new ad group node should now exist in the sidebar; give it a moment
        break
    page.wait_for_timeout(1000)


def continue_step(page):
    # 15 秒 -> 60 秒：同上，与项目里其它地方统一
    btn = page.get_by_role("button", name="继续", exact=True)
    btn.wait_for(state="visible", timeout=60000)
    btn.click(timeout=10000)
    page.wait_for_timeout(3000)


# ---------------------------------------------------------------- 发布
#
# 这一段原来只在 src/drama/pages/campaign_page.py 里有（短剧那边先遇到的），
# 2026-08-19 挪到这里共用。两个原因：
#
#  * 小游戏原来的发布是 get_by_role("button", name="全部发布").click()，命中多个
#    元素时 Playwright 会抛 strict mode violation。使用者的截图里，单个广告组时
#    「全部发布」是个普通按钮，而【多个广告组时它旁边多了一个下拉箭头】——
#    新的「多广告组、每组素材不同」正好是多广告组的场景，等于把这个隐患摆到了
#    主路径上。这里逐个挑【可见】的按钮，不会撞 strict mode。
#  * 使用者实测的平台 bug：一个计划里广告数量大于 1 时，点发布有概率弹报错框，
#    处理办法是点框右下角的「修复」，等它消失再点发布，还报错就重复。新的搭法
#    会在一个计划里建好几个广告，撞上这个 bug 的概率更高。
#
# 逻辑与短剧那份完全一致，只是搬了个位置——短剧那边现在从这里 import。

_PUBLISH_BUTTON_NAMES = ("全部发布", "发布")


def _first_visible_button(page, name, limit=5):
    """按名字找第一个【可见】的按钮，没有就返回 None。

    不用 .first：这个后台经常同时存在同名的隐藏副本，而且 .click() 在命中多个时
    会直接抛 strict mode violation。
    """
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
    from src.pages.common import robust_click

    for name in _PUBLISH_BUTTON_NAMES:
        btn = _first_visible_button(page, name)
        if btn is not None:
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

    平台有个已知的概率性 bug（使用者实测）：一个计划里广告数量大于 1 时，
    点发布有概率弹出报错框。处理办法是点那个框右下角的「修复」，然后再点发布；
    还报错就再重复一次。所以这里是「点发布 -> 看到修复按钮就点它 -> 等它消失 ->
    再点发布」的循环，最多 max_fix_rounds 轮。

    绝不要自己强行跳转去计划列表：中途跳走会打断发布，计划实际不会上线。
    慢没关系，早跳不行。
    """
    from src.pages.common import robust_click, wait_until

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
            # 既没跳走、也没报错框、也没看到进度提示。把【当前可见的按钮和弹层
            # 文字】打出来——一出现就能立刻看出该认什么，不用再猜。
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
