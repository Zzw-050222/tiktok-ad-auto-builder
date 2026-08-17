import re


def _wait_visible(page, text_or_re, what, timeout_seconds=60):
    """等一个文字元素出现【并且可见】，最多 timeout_seconds，返回那个可见元素。

    比裸的 scroll_into_view_if_needed(timeout=10000) 强在两点：给足这个平台真实
    需要的时间（见 common.wait_until 的注释），以及在页面上存在多个同文本副本
    （其中大部分尺寸为 0）时挑出真正能点的那一个 —— 这页面上这种情况很常见。
    """
    from src.pages.common import wait_until

    def visible_one():
        loc = page.get_by_text(text_or_re)
        n = loc.count()
        for i in range(min(n, 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    found = wait_until(page, visible_one, timeout_seconds=timeout_seconds)
    if not found:
        raise ValueError(f"等了 {timeout_seconds} 秒还没看到{what}")
    return found


def _wait_visible_button(page, name, what, timeout_seconds=60):
    """同上，但按钮走 role 定位。"""
    from src.pages.common import wait_until

    def visible_one():
        loc = page.get_by_role("button", name=name, exact=True)
        n = loc.count()
        for i in range(min(n, 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    found = wait_until(page, visible_one, timeout_seconds=timeout_seconds)
    if not found:
        raise ValueError(f"等了 {timeout_seconds} 秒还没看到{what}")
    return found


# 读出一个素材复选框所属卡片的【唯一身份】。
#
# 去重必须认素材本身，不能认位置。原来的做法是记「已经用掉 N 个」然后跳过列表里
# 前 N 个复选框——只要列表顺序在两次页面加载之间变了（按上传时间排序、中途上传了
# 新素材、DOM 里混进别的复选框），跳过的就不是同一批素材，去重形同虚设，而且无法
# 验证也无法自我纠正。
#
# 按可靠性依次尝试：带长数字的 data-* 属性（素材 ID 最可能在这里）→ 缩略图/视频
# URL 去掉查询参数后的路径尾段（查询参数里有每次都变的签名，必须去掉）→ title/alt
# 里的素材名。全都拿不到就返回空串，调用方会拒绝去重而不是硬猜。
# 实测（2026-08-14）素材卡的真实结构：
#   <div class="container">
#     <label role="checkbox" class="vi-checkbox cardCheckbox">…</label>   ← 传进来的 el
#     <div class="video" id="v10033g50000d9up75vog65qe3a2vui0">           ← TikTok 视频 ID
#       … <img src="https://p16.tiktokcdn.com/…">                        ← 缩略图，懒加载
#
# 用那个 <div class="video"> 上的 id 当身份：每个素材唯一，而且【从一开始就在 DOM
# 里】，不受缩略图懒加载影响。
#
# 之前用缩略图 URL 当身份是错的，两个原因叠加：
#  * 缩略图是懒加载的，加载完成前 30 张卡全是同一张占位图 —— 实测「30 张只有 1 个
#    不同标识」，等 8 秒后才变成 30 个。拿它去重会把 29 个不同素材误判成同一个。
#  * 更糟的是原来的容器定位是「从复选框往上找到第一个含 img 的祖先」。缩略图还没
#    插入时卡片里根本没有 <img>，于是一路走到整个弹层（pane-library / drawer-…），
#    30 个复选框全部解析到同一个巨大容器、同一张图。
# 所以现在改成：以复选框的父元素为锚点（就是卡片容器），只往上找 2 层，且要求 id
# 形如 v+数字 且足够长，这样不会误中 pane-library 这类外层容器的 id。
_TILE_IDENTITY_JS = """
el => {
  const looksLikeVideoId = (s) => !!s && /^v\\d{5,}/.test(s) && s.length >= 20;

  let card = el.parentElement;
  for (let k = 0; k < 2 && card; k++) {
    const direct = card.querySelector('div.video[id]');
    if (direct && looksLikeVideoId(direct.id)) return 'vid:' + direct.id;
    for (const n of card.querySelectorAll('[id]')) {
      if (looksLikeVideoId(n.id)) return 'vid:' + n.id;
    }
    card = card.parentElement;
  }

  // 兜底：缩略图 URL。注意它是懒加载的，早期是占位图，所以只在拿不到视频 ID 时用，
  // 并且调用方的唯一性校验会拦住占位图阶段。
  card = el.parentElement;
  if (card) {
    const media = card.querySelector('img[src], video[src], video source[src]');
    if (media) {
      const raw = media.getAttribute('src') || media.getAttribute('poster') || '';
      const seg = (raw.split('?')[0].split('/').filter(Boolean).pop() || '');
      if (seg.length >= 8) return 'media:' + seg;
    }
  }
  return '';
}
"""


def _tile_identity(checkbox):
    try:
        return checkbox.evaluate(_TILE_IDENTITY_JS) or ""
    except Exception:
        return ""


def _assert_identity_usable(page, checkboxes, total, timeout_seconds=40):
    """确认取到的身份确实【唯一】，否则拒绝去重而不是悄悄用一个不可靠的标识。

    正常情况下身份来自 <div class="video"> 的 id，从一开始就在 DOM 里，第一次读就
    是唯一的。但如果某个账号只能退到缩略图 URL 兜底，那它是懒加载的——加载完成前
    30 张卡全是同一张占位图（实测「30 张只有 1 个不同标识」，等 8 秒后才变成 30
    个）。所以这里轮询而不是一次判定：等它变唯一，等不到才报错。

    宁可明确报错中止，也不要拿一个会把不同素材误判成同一个的标识去做假去重。
    """
    from src.pages.common import wait_until

    n = min(total, 30)
    state = {"ids": [], "n_got": 0}

    def unique_now():
        ids = [_tile_identity(checkboxes.nth(i)) for i in range(n)]
        got = [x for x in ids if x]
        state["ids"], state["n_got"] = ids, len(got)
        return got if (len(got) == n and len(set(got)) == n) else None

    got = wait_until(page, unique_now, timeout_seconds=timeout_seconds, interval_ms=1500)
    if got:
        return got[0]

    ids = state["ids"]
    got = [x for x in ids if x]
    if not got:
        raise ValueError(
            f"素材卡片上读不出任何身份标识（等了 {timeout_seconds} 秒）。"
            "无法保证不重复使用素材，已中止。请把 logs/ 发出来以便补充识别方式。"
        )
    if len(got) < n:
        raise ValueError(
            f"前 {n} 张素材卡里有 {n - len(got)} 张读不出身份标识"
            f"（等了 {timeout_seconds} 秒仍如此），无法保证不重复，已中止。"
        )
    dup = len(got) - len(set(got))
    raise ValueError(
        f"素材卡片的身份标识不唯一：前 {len(got)} 张里有 {dup} 个重复值"
        f"（样例 {got[0]!r}，等了 {timeout_seconds} 秒仍不唯一）。"
        "拿它去重会把不同素材误判成同一个，已中止。"
    )


# 找到素材卡所在的【真正可滚动容器】并直接把它滚到底。
#
# 绝不能靠 page.mouse.wheel：使用者实测观察到滚轮滚的是弹层【后面的页面】而不是
# 列表本身。原因是 wheel 只是往鼠标位置派发滚轮事件——一旦列表容器已经到底，或者
# 鼠标没落在容器的可滚动区域里，事件就冒泡到外层页面去了。表现就是后面的页面在
# 动、列表一动不动，于是永远等不到下一批素材。
#
# 直接设置 scrollTop 是确定性的：先沿 DOM 往上找第一个「overflow 允许滚动且
# scrollHeight 明显大于 clientHeight」的祖先，那就是列表容器，然后一次到底。
# 设置 scrollTop 通常会自动派发 scroll 事件，这里再补派一次，确保懒加载的监听器
# 一定收到。找不到容器时把整条祖先链带出来，方便排查而不是静默失败。
_SCROLL_LIBRARY_JS = """
el => {
  const chain = [];
  let n = el;
  while (n && n !== document.body && n !== document.documentElement) {
    const s = getComputedStyle(n);
    const oy = s.overflowY;
    const scrollable = (oy === 'auto' || oy === 'scroll' || oy === 'overlay');
    const cls = (n.className && n.className.toString ? n.className.toString() : '').slice(0, 40);
    if (scrollable && n.scrollHeight > n.clientHeight + 4) {
      const before = n.scrollTop;
      n.scrollTop = n.scrollHeight;
      n.dispatchEvent(new Event('scroll', {bubbles: true}));
      return {
        found: true,
        tag: n.tagName.toLowerCase(),
        cls: cls,
        testid: n.getAttribute('data-testid') || '',
        before: Math.round(before),
        after: Math.round(n.scrollTop),
        scrollHeight: Math.round(n.scrollHeight),
        clientHeight: Math.round(n.clientHeight)
      };
    }
    chain.push(`${n.tagName.toLowerCase()}.${cls} oy=${oy} sh=${n.scrollHeight} ch=${n.clientHeight}`);
    n = n.parentElement;
  }
  return {found: false, chain: chain.slice(0, 12)};
}
"""


def _scroll_library_to_bottom(page, tiles):
    """把素材库【列表自身】滚到底 —— 触发下一批 30 个素材加载的必要条件。

    返回诊断字典：found 表示有没有找到列表的滚动容器，before/after 是滚动前后的
    scrollTop（可用来确认真的滚动了）。调用方在 found 为假时会明确报错，而不是
    默默少选几个素材。
    """
    n = tiles.count()
    if n == 0:
        return {"found": False, "reason": "列表里没有素材卡"}

    last = tiles.nth(n - 1)
    try:
        info = last.evaluate(_SCROLL_LIBRARY_JS)
    except Exception as e:
        return {"found": False, "reason": f"查找滚动容器时出错: {e}"}

    # 给懒加载一点反应时间；真正的等待在调用方（轮询 checkbox 数量变多）
    page.wait_for_timeout(400)
    return info


def wait_ad_page_ready(page):
    page.get_by_text("创意素材", exact=True).wait_for(state="visible", timeout=90000)
    page.wait_for_timeout(1000)


def select_identity(page, handle_name: str):
    from src.pages.common import dismiss_popups, robust_click, wait_until

    dismiss_popups(page)

    dropdown = page.locator('[data-testid="components-IdentityListComponent-szvjSS"]')
    dropdown.scroll_into_view_if_needed(timeout=15000)
    dropdown.click(timeout=10000)
    page.wait_for_timeout(800)

    # only a handful of identities are shared to this account - no need to search,
    # just click the matching one directly from the list that's already shown.
    # The list can take a while to render, so wait (up to a minute) for a VISIBLE
    # match before concluding it's genuinely absent.
    def visible_match():
        candidates = page.get_by_text(handle_name, exact=False)
        for i in range(candidates.count()):
            c = candidates.nth(i)
            if c.is_visible():
                return c
        return None

    result = wait_until(page, visible_match, timeout_seconds=60)
    if not result:
        raise ValueError(f"身份 '{handle_name}' 不在当前广告账户可选的身份列表里")

    result.scroll_into_view_if_needed(timeout=5000)
    robust_click(page, result, timeout=5000)
    page.wait_for_timeout(500)


def select_creative_materials(page, search_term: str, count: int, used_ids=None,
                              batch_wait_seconds=25, batch_settle_ms=0):
    """从素材库里手动挑 count 个素材（而不是沿用 TikTok 默认的「自动选择」），
    按 search_term 搜索。

    去重按【素材身份】进行，不按位置：
      used_ids —— 一个 set，装本次运行中这个 (广告主, 小游戏) 组合已经用过的素材
      身份。函数会跳过里面已有的，选中新的之后就地把身份加进去（原地修改，调用方
      同一个 set 一直传下去即可）。

    旧版是靠 skip=N「跳过列表里前 N 个复选框」，纯按位置。只要列表顺序在两次页面
    加载之间变了（按上传时间排序、中途上传了新素材、DOM 里混进别的复选框），跳过
    的就不是同一批素材，去重形同虚设；而且它只记「用掉多少个」不记「用了哪些」，
    既无法验证也无法自我纠正，偏移量一旦算错就永久错下去。

    素材不够时会【绕回头复用】：整个库遍历完还没选够，就清空 used_ids 重新扫一
    遍，保证本条广告一定选满 count 个。效果是「先把所有素材都用一遍，用完了才开始
    重复」。

    batch_wait_seconds / batch_settle_ms —— 加载下一批素材的耐心。默认值就是小游戏
    一直在用的行为，不要改。短剧那边传的更大：使用者要求「宁可慢，也要保证不选重复」，
    所以多给等待时间、每批加载完再静置一会儿才开始选。

    返回 (选中数量, 是否绕回头复用过)。选中数量小于 count 只会发生在库里连一轮都
    凑不满 count 个的情况下。
    """
    from src.pages.common import dismiss_popups, robust_click, wait_until

    if used_ids is None:
        used_ids = set()

    dismiss_popups(page)

    # the "自动选择" box can take a while to finish generating.
    #
    # 这个守卫单独用是不可靠的：它的判据是「'正在加载中' 不存在就算好了」，而
    # wait_until 是立刻开始轮询的——页面还没【开始】加载时这个字样自然也不存在，
    # 于是第一次轮询就直接放行，等于什么都没等。真正的等待必须落在「目标元素出现」
    # 上（见下面的 _wait_visible），这里留着它只是为了在确实处于加载中时多等一会。
    def not_loading():
        loc = page.get_by_text("正在加载中", exact=False)
        return True if loc.count() == 0 else None

    wait_until(page, not_loading, timeout_seconds=60)
    page.wait_for_timeout(500)

    # 2026-08-14 实测：'自动选择' 这个框会晚于 10 秒才渲染出来（当天 TikTok 给
    # 这块加了「自动选择功能重磅上线」的推广横幅，整体变慢）。原来直接
    # scroll_into_view_if_needed(timeout=10000) 就会在 10 秒时抛
    # TimeoutError，而抓失败现场时元素其实已经在页面上了。改成 60 秒轮询等它
    # 【可见】，跟本项目其它地方（set_target_roas、区域列表等）统一。
    #
    # 用锚定的正则而不是 exact=True：页面上同时存在「自动选择功能重磅上线」这个
    # 横幅，它包含「自动选择」但不能点。锚定首尾正好把它排除掉。
    auto_select_box = _wait_visible(page, re.compile(r"^\s*自动选择\s*$"), "自动选择的框")
    auto_select_box.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, auto_select_box, timeout=5000)
    page.wait_for_timeout(1500)

    # the TOP-LEVEL "+ 添加创意素材" button - NOT the nested "+ 添加内容"
    # under "你的自有内容" (that path was confirmed inconsistent across
    # accounts, this one is not)
    top_add_btn = _wait_visible_button(page, "添加创意素材", "顶层的「添加创意素材」按钮")
    top_add_btn.scroll_into_view_if_needed(timeout=10000)
    robust_click(page, top_add_btn, timeout=5000)
    page.wait_for_timeout(1200)

    # switch to the "创意素材库" tab - a plain text match is ambiguous (an
    # info banner sentence also contains this exact substring and can
    # trigger a spurious "退出此页面" dialog instead of switching tabs), so
    # match the actual tab element via its stable class name instead
    lib_tab = page.locator(".tab-item-text", has_text="创意素材库")
    robust_click(page, lib_tab.first, timeout=5000)
    page.wait_for_timeout(1000)

    search_box = page.get_by_placeholder("按名称或ID搜索")
    search_box.first.click(timeout=5000)
    page.keyboard.type(search_term)

    # scope everything below to this tab's own container (derived from the
    # search box's own ancestor, not a page-wide `.first` on the container's
    # selector - its data-testid has a random suffix that can shift which
    # element `.first` resolves to after searching). The hidden "TikTok 帖子"
    # tab's DOM otherwise pollutes page-wide text/role matches for tiles and
    # checkboxes (confirmed live: nearly doubled tile counts, matched an
    # unrelated "已选择 2 个 TikTok 账号" filter instead of the real counter).
    lib_pane = search_box.first.locator(
        "xpath=ancestor::div[starts-with(@data-testid, 'tab-library-')][1]"
    )
    tiles = lib_pane.locator(r"text=/^\d{2}:\d{2}$/")

    # results flicker while settling (appear, clear, reload) - require the
    # SAME non-zero count across 3 consecutive checks, not just "count > 0
    # once", or a transient empty/partial state gets mistaken for "ready"
    stable_hits, last_count = 0, -1
    for _ in range(120):  # up to ~60s
        c = tiles.count()
        if c > 0 and c == last_count:
            stable_hits += 1
            if stable_hits >= 3:
                break
        else:
            stable_hits = 0
        last_count = c
        page.wait_for_timeout(500)

    # the real checkbox is a `role="checkbox"` <label> wrapping a visually
    # hidden native <input> - matching the native input directly finds
    # nothing, since it's never Playwright-"visible"
    checkboxes = lib_pane.get_by_role("checkbox")

    # 搜索没有结果时要单独说清楚，别混进下面那个「读不出身份标识」的报错里。
    # 那句话会让人以为是识别逻辑坏了，实际是这个搜索词在库里一个素材都没有
    # （实测：某个剧还没上素材，搜剧名 0 结果，报错却说「读不出身份标识」，
    # 白排查了一轮）。
    if checkboxes.count() == 0:
        raise ValueError(
            f"素材库里搜 {search_term!r} 没有任何结果——这个搜索词在当前账号的"
            "创意素材库里一个素材都没有。先确认素材已经上传、名字里确实带这个词。"
        )

    # 再确认卡片上的身份标识确实唯一，不唯一就直接中止（见 _assert_identity_usable）
    sample_id = _assert_identity_usable(page, checkboxes, checkboxes.count())

    picked = []          # 本条广告已选中的素材身份（有序，便于排查）
    scanned = 0          # 已经检查过的复选框下标
    wrapped = False      # 是否已经把整个库用过一轮、开始复用
    stale_rounds = 0

    for _ in range(400):
        cur_total = checkboxes.count()

        # 按【身份】而不是按位置推进：逐张读身份，用过的直接跳过（不点击）。
        # 这样列表顺序变了、中途上传了新素材、DOM 里混进别的复选框，都不会导致
        # 重复使用——判断依据是素材本身。
        while scanned < cur_total and len(picked) < count:
            cb = checkboxes.nth(scanned)
            scanned += 1

            ident = _tile_identity(cb)
            if not ident:
                continue                      # 读不出身份的宁可不选，绝不冒险
            if ident in picked:
                continue                      # 本条广告已经选过这一个
            if not wrapped and ident in used_ids:
                continue                      # 本次运行别的计划用过，优先挑没用过的

            # 已经是选中态就别再点——再点一次会把它取消掉
            try:
                if cb.get_attribute("aria-checked") == "true":
                    picked.append(ident)
                    used_ids.add(ident)
                    continue
            except Exception:
                pass

            cb.scroll_into_view_if_needed(timeout=5000)
            robust_click(page, cb, timeout=5000)
            page.wait_for_timeout(250)
            try:
                really_checked = cb.get_attribute("aria-checked") == "true"
            except Exception:
                really_checked = False
            if really_checked:
                picked.append(ident)
                used_ids.add(ident)           # 只有真的选中了才记账

        if len(picked) >= count:
            break

        # 已加载的都看过了，让素材库加载下一批。
        #
        # 这个库的真实行为（使用者手动操作确认）：一次只给 30 个（每行 5 个），
        # 必须【滚到底】才会触发下一批，之后 10 秒内出现。这里是轮询而不是死等：
        # wait_until 每 500ms 查一次，新素材一出现就立刻继续选，25 秒只是上限。
        before = cur_total
        diag = _scroll_library_to_bottom(page, tiles)

        if not diag.get("found"):
            # 找不到列表的滚动容器 —— 说明滚动压根没作用在列表上（使用者实测见过
            # 滚轮把弹层后面的页面滚了）。这种情况下再等也不会有新素材，明确报错
            # 比默默少选素材好。
            raise ValueError(
                "找不到素材库列表自己的滚动容器，无法加载下一批素材。"
                f"原因/祖先链: {diag.get('reason') or diag.get('chain')}"
            )
        if diag["after"] <= diag["before"] and diag["after"] + 4 < diag["scrollHeight"]:
            # 容器找到了但没滚动成功，也不要当成「素材不够」
            raise ValueError(
                f"素材库列表的滚动容器没能滚动（scrollTop {diag['before']}->{diag['after']}, "
                f"scrollHeight {diag['scrollHeight']}, 容器 {diag['tag']}.{diag['cls']}）"
            )

        def more_loaded():
            return checkboxes.count() > before

        if wait_until(page, more_loaded, timeout_seconds=batch_wait_seconds):
            stale_rounds = 0
            if batch_settle_ms:
                # 新一批刚出现时 DOM 还在补，静置一会儿再选，宁可慢也别选错
                page.wait_for_timeout(batch_settle_ms)
            continue

        stale_rounds += 1
        if stale_rounds < 2:
            continue                          # 再给一次机会

        # 整个库都遍历完了还没选够。
        if not wrapped:
            # 绕回头复用：把「本次运行用过」的记录清空，重新从头扫一遍，保证这条
            # 广告也能选满 count 个。清空同时意味着后面的计划开始新的一轮，效果是
            # 「先把所有素材都用一遍，用完了才开始重复」——正是需要的行为。
            # 本条广告已经选中的仍然留在记录里，避免同一条广告里选到重复素材。
            wrapped = True
            used_ids.clear()
            used_ids.update(picked)
            scanned = 0
            stale_rounds = 0
            continue
        break                                 # 绕过一轮还是不够，只能到此为止

    selected = len(picked)

    confirm_btn = page.get_by_role("button", name="添加创意素材", exact=True)
    robust_click(page, confirm_btn.first, timeout=10000)
    page.wait_for_timeout(1500)

    save_btn = page.get_by_role("button", name="保存", exact=True)
    robust_click(page, save_btn.first, timeout=10000)
    page.wait_for_timeout(2000)

    return selected, wrapped


def fill_ad_copy(page, ads_text: str):
    from src.pages.common import wait_until

    def label_visible():
        loc = page.get_by_text("文案 (0/5)", exact=False)
        if loc.count() == 0:
            loc = page.get_by_text("文案", exact=True)
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    label = wait_until(page, label_visible, timeout_seconds=60)
    if not label:
        raise ValueError("一直没找到'文案'区域")
    label.first.scroll_into_view_if_needed(timeout=10000)

    def input_ready():
        loc = page.get_by_placeholder("输入文案")
        if loc.count() == 0:
            loc = page.locator(
                "xpath=//*[contains(normalize-space(text()),'文案')]/following::textarea[1]"
            )
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    input_box = wait_until(page, input_ready, timeout_seconds=60)
    if not input_box:
        raise ValueError("一直没找到文案输入框")
    input_box.first.click(timeout=10000)
    input_box.first.fill(ads_text)
    page.wait_for_timeout(500)


def fill_landing_url(page, url: str):
    from src.pages.common import wait_until

    def field_visible():
        loc = page.get_by_placeholder("https://www.tiktok.com/minis/")
        return loc if (loc.count() > 0 and loc.first.is_visible()) else None

    field = wait_until(page, field_visible, timeout_seconds=60)
    if not field:
        raise ValueError("一直没找到落地页链接输入框")
    field.first.scroll_into_view_if_needed(timeout=10000)
    field.first.fill("")
    field.first.fill(url)
    page.wait_for_timeout(500)
