import re


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


# 把广告表单自己滚到【顶部】。
#
# 做法和 _SCROLL_LIBRARY_JS 一样：沿 DOM 往上找第一个真正可滚动的祖先，直接设
# scrollTop。绝不用 page.mouse.wheel —— 本项目实测过它会滚到「弹层后面的页面」
# 而不是目标容器（滚轮事件冒泡到外层去了）。
_SCROLL_TO_TOP_JS = """
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
      n.scrollTop = 0;
      n.dispatchEvent(new Event('scroll', {bubbles: true}));
      return {found: true, tag: n.tagName.toLowerCase(), cls: cls,
              before: Math.round(before), after: Math.round(n.scrollTop)};
    }
    chain.push(`${n.tagName.toLowerCase()}.${cls} oy=${oy} sh=${n.scrollHeight} ch=${n.clientHeight}`);
    n = n.parentElement;
  }
  // 表单不在独立滚动容器里时，整页滚到顶也算
  const se = document.scrollingElement || document.documentElement;
  const before = se.scrollTop;
  se.scrollTop = 0;
  window.scrollTo(0, 0);
  return {found: before !== se.scrollTop, page: true,
          before: Math.round(before), after: Math.round(se.scrollTop),
          chain: chain.slice(0, 10)};
}
"""


def scroll_ad_form_to_top(page):
    """把广告层的表单滚到最顶部，返回诊断字典（失败也不抛，调用方自己决定）。

    锚点按「当前最可能已经渲染出来的东西」依次尝试：落地页链接框（使用者实测平台
    就是把页面定位到这里）、文案框、「广告名称」标题、创意素材区块标题。
    """
    anchors = (
        page.get_by_placeholder("https://www.tiktok.com/minis/"),
        page.get_by_placeholder("输入文案"),
        page.get_by_text("广告名称", exact=True),
        page.get_by_test_id("creative-assets-header-title"),
    )
    for loc in anchors:
        try:
            n = loc.count()
        except Exception:
            continue
        for i in range(min(n, 8)):
            el = loc.nth(i)
            try:
                if not el.is_visible():
                    continue
                info = el.evaluate(_SCROLL_TO_TOP_JS)
            except Exception:
                continue
            page.wait_for_timeout(300)
            return info
    # 一个锚点都找不到：退一步整页滚到顶
    try:
        page.evaluate(
            "() => { const se = document.scrollingElement || document.documentElement;"
            " se.scrollTop = 0; window.scrollTo(0, 0); }"
        )
        page.wait_for_timeout(300)
        return {"found": True, "page": True, "note": "没找到锚点，整页滚到顶"}
    except Exception as e:
        return {"found": False, "reason": str(e)[:120]}


def wait_ad_page_ready(page):
    """等广告层页面就绪。

    不能用 get_by_text("创意素材")：这四个字页面上有【两个】——
      1) 真正的区块标题  data-testid="creative-assets-header-title"
      2) 右侧「建议采纳情况」里的检查项（#sppFormRightSideBarContainer 内）
    命中两个时 Playwright 的 strict mode 会直接抛
    「strict mode violation: ... resolved to 2 elements」。这个 bug 一直潜伏着，
    以前靠右侧清单渲染得比标题慢侥幸过关；复制广告之后右侧清单已经在了，就必炸。

    所以锚定那个稳定的 data-testid（自定义标签名 ks-text-* 每次加载都随机，
    但 data-testid 稳定），找不到才退回按文字取第一个可见的。

    2026-08-19 又改一处：从 header.first.wait_for(visible) 换成【遍历挑可见的】。
    沿「继续」把一个计划的多个广告组走一遍时，走过的广告组的表单还留在 DOM 里
    （不可见），.first 可能正好是那个隐藏副本——等它可见就是干等 90 秒，而页面上
    明明有一个可见的。这是本项目的老坑（ROAS、地域都栽过），只是这里以前不会遇到
    多套表单共存所以没暴露。
    """
    from src.pages.common import wait_until

    def _first_visible_of(loc, limit=12):
        try:
            n = loc.count()
        except Exception:
            return 0, None
        for i in range(min(n, limit)):
            try:
                if loc.nth(i).is_visible():
                    return n, loc.nth(i)
            except Exception:
                continue
        return n, None

    def visible_marker():
        # 优先级要和原来一致：只要 data-testid 还在 DOM 里，就【只等它可见】，
        # 不能退到按文字找。因为「创意素材」这四个字右侧「建议采纳情况」里也有一份，
        # 那份可能先可见——退过去就会在广告表单还没渲染好时就判定就绪。
        n, el = _first_visible_of(page.get_by_test_id("creative-assets-header-title"))
        if n > 0:
            return el
        # testid 压根不在 DOM 里（TikTok 改了结构）才退回按文字找可见的
        _n, el = _first_visible_of(page.get_by_text("创意素材", exact=True))
        return el

    if wait_until(page, visible_marker, timeout_seconds=90) is None:
        raise ValueError(
            "等了 90 秒广告层还没就绪（没看到可见的「创意素材」区块标题）。"
            f"当前地址: {page.url[:120]}"
        )
    page.wait_for_timeout(1000)


def select_identity(page, handle_name: str):
    """选身份（TikTok 账号）。

    2026-08-19：下拉框改成【遍历挑可见的】。原来是
        dropdown = page.locator('[data-testid="..."]')
        dropdown.scroll_into_view_if_needed(...)   ← 命中多个就抛 strict mode
    沿「继续」把一个计划的多个广告组走一遍时，走过的广告组的表单还留在 DOM 里，
    这个 data-testid 就会命中好几个，scroll_into_view_if_needed 直接报
    「strict mode violation: resolved to N elements」。以前一个计划只走一套表单，
    永远只有一个，所以没暴露。
    """
    from src.pages.common import dismiss_popups, robust_click, wait_until

    dismiss_popups(page)

    def visible_dropdown():
        loc = page.locator('[data-testid="components-IdentityListComponent-szvjSS"]')
        try:
            n = loc.count()
        except Exception:
            return None
        for i in range(min(n, 12)):
            try:
                if loc.nth(i).is_visible():
                    return loc.nth(i)
            except Exception:
                continue
        return None

    dropdown = wait_until(page, visible_dropdown, timeout_seconds=60)
    if dropdown is None:
        raise ValueError("等了 60 秒没找到可见的身份（TikTok 账号）下拉框")
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


# 「自动选择」那个框的文案。用锚定正则而不是 exact=True：页面上同时存在
# 「自动选择功能重磅上线」这个推广横幅，它包含「自动选择」但不能点，锚定首尾
# 正好把它排除掉。生成中时这个框写的是「正在生成自动选择」，也不该点，同样被排除。
_AUTO_SELECT_RE = re.compile(r"^\s*自动选择\s*$")


def _auto_select_debug(page):
    """页面上所有含「自动选择」的文字连可见性 —— 失败时用来分清卡在哪一种情况。"""
    seen = []
    try:
        loc = page.get_by_text("自动选择", exact=False)
        for i in range(min(loc.count(), 8)):
            try:
                seen.append(
                    f"{(loc.nth(i).inner_text() or '').strip()[:30]!r}"
                    f"{'(可见)' if loc.nth(i).is_visible() else '(隐藏)'}"
                )
            except Exception:
                continue
    except Exception:
        pass
    return seen or ["（一个都没有）"]


def _reload_ad_page(page):
    """刷新当前广告层，刷完确认「还在广告层」且「这个广告还是空的」。

    草稿是平台自动保存的（页面底部一直写着「草稿已保存」），而且卡在这一步时当前
    这个广告本来还什么都没填（素材是 fill_ad_core 的第一件事），所以刷新不会丢东西，
    代价只是等它重新加载。

    刷完必须确认两件事，缺一不可：
      * 还在广告层 —— 万一刷新把页面带到别处，后面每一步都会莫名其妙地失败
      * 这个广告还是空的 —— 如果刷新后落到了【别的、已经填好的】广告上，继续往下
        走就是给同一个广告重复加素材。那是静默的错（发布了才发现），宁可明确中止。
    """
    # 万一浏览器弹原生的「确定要离开此页面吗」，接受它（我们就是要重新加载）。
    # 用完就摘掉监听器，别让它去接后面无关的弹窗。
    def _accept(d):
        try:
            d.accept()
        except Exception:
            pass

    page.on("dialog", _accept)
    try:
        page.reload(wait_until="domcontentloaded", timeout=90000)
    finally:
        try:
            page.remove_listener("dialog", _accept)
        except Exception:
            pass

    page.wait_for_timeout(3000)
    wait_ad_page_ready(page)
    from src.pages.common import dismiss_popups

    dismiss_popups(page)

    from src.pages.step_flow import ad_already_filled

    if ad_already_filled(page):
        raise ValueError(
            "刷新页面之后落到了一个【已经填过内容】的广告上（文案或落地页非空），"
            "说明刷新把左侧选中的广告换掉了。继续下去会给同一个广告重复加素材，已中止。"
            "请手动到后台看这个计划，确认哪个广告还是空的。"
        )


def _open_auto_select(page, find_seconds=10, effect_seconds=12, max_reloads=2):
    """让「自动选择」那个框变成可点、点开它，返回顶层的「添加创意素材」按钮。

    使用者实测（2026-08-20）：搭到【最后一个广告组】的广告层时，这个框有非常大的
    概率卡住不给点——已经滚到顶、框就在那儿，但点不动。处理办法是【刷新界面】，
    刷完就能点了。使用者的原话：「滚到上面然后十秒之内点击不了那个自动选择素材的
    那个地方你就刷新界面」。

    所以这里是：滚到顶 -> {find_seconds} 秒内找到框 -> 用【真实点击】点它 ->
    {effect_seconds} 秒内确认真的点开了；做不到就刷新页面重来，最多刷 max_reloads 次。

    关键点：这一步【不能用 robust_click】。robust_click 在普通点击失败后会升级到
    force 点击、再升级到 JS 直接派发 click 事件——而 JS 派发「只要元素在 DOM 里就
    一定不报错」，等于把「点不动」这件事整个吞掉：看起来点了，实际页面毫无反应，
    然后卡在后面等「添加创意素材」上超时。要检测「点不了」，就必须让普通点击把
    异常抛出来。robust_click 只留给最后一次尝试当兜底。

    「真的点开了」的判据用顶层「添加创意素材」按钮出现——它本来就是紧接着要用的那个
    按钮，拿它当判据不额外增加对页面结构的假设。另外即使点击报了超时也要先看一眼
    效果：本项目实测过「普通点击报 TimeoutError、但弹层其实已经打开」这种情况
    （见 common.click_to_open 的注释），不先看效果就刷新等于白刷一次。
    """
    from src.pages.common import robust_click, wait_until

    for attempt in range(max_reloads + 1):
        last_attempt = attempt == max_reloads

        box = _find_auto_select_box(page, timeout_seconds=find_seconds)
        if box is None:
            print(f"        [自动选择] 第{attempt + 1}次：滚到顶后 {find_seconds} 秒内"
                  f"还是没看到这个框，{'放弃' if last_attempt else '刷新页面重来'}。"
                  f"页面上含「自动选择」的文字: {_auto_select_debug(page)}", flush=True)
            if last_attempt:
                break
            _reload_ad_page(page)
            continue

        try:
            box.scroll_into_view_if_needed(timeout=5000)
        except Exception:
            pass

        click_error = None
        try:
            # 真实点击，不 force、不 JS —— 点不动就要它抛出来
            box.click(timeout=find_seconds * 1000)
        except Exception as e:
            click_error = str(e).splitlines()[0][:90]

        if click_error and last_attempt:
            # 最后一次了，才允许升级到 robust_click 兜底（老账号上有「普通点击超时
            # 但 force/JS 能点开」的情况，不能因为新加的检测把它们挡死）
            print(f"        [自动选择] 普通点击失败（{click_error}），"
                  "最后一次尝试，升级到 force / JS 点击兜底", flush=True)
            try:
                robust_click(page, box, timeout=8000)
            except Exception:
                pass

        btn = wait_until(
            page,
            lambda: _first_visible_button_or_none(page, "添加创意素材"),
            timeout_seconds=effect_seconds,
        )
        if btn:
            if click_error:
                print(f"        [自动选择] 点击报了「{click_error}」，"
                      "但「添加创意素材」已经出现，按点开处理", flush=True)
            return btn

        why = f"点击报错（{click_error}）" if click_error else \
            f"点击没报错，但 {effect_seconds} 秒内「添加创意素材」没出现"
        print(f"        [自动选择] 第{attempt + 1}次：{why}，"
              f"{'放弃' if last_attempt else '刷新页面重来'}", flush=True)
        if last_attempt:
            break
        _reload_ad_page(page)

    raise ValueError(
        f"「自动选择」这个框试了 {max_reloads + 1} 次（中间刷新了 {max_reloads} 次页面）"
        "都没能点开，已中止。"
        f"页面上含「自动选择」的文字: {_auto_select_debug(page)}"
    )


def _first_visible_button_or_none(page, name, limit=12):
    loc = page.get_by_role("button", name=name, exact=True)
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(min(n, limit)):
        try:
            if loc.nth(i).is_visible():
                return loc.nth(i)
        except Exception:
            continue
    return None


def _find_auto_select_box(page, timeout_seconds=10):
    """找「自动选择」那个可见的框，中途反复把表单滚到顶。找不到返回 None（不抛）。

    为什么要边等边滚（2026-08-19 使用者实测）：沿「继续」走到最后一个广告层时，
    平台发现落地页链接还没填，会【自动把页面定位到 URL 那一块】。而「自动选择」在
    表单最顶部、URL 在最底部，于是它在视口外，原来那句 60 秒轮询一直等不到，
    报「等了 60 秒还没看到自动选择的框」（使用者的截图就是这个）。
    使用者的说法：「自动选择框在最上面，url 在最下面，这个时候你要是没看到的话
    就滚轮滑到顶就行了」。

    不是滚一次就完事：平台每次校验都可能再把页面拽回 URL 那里，所以每约 3 秒
    重新滚一次顶，直到框出现。

    找不到【不抛异常】：调用方 _open_auto_select 要靠这个来决定「刷新页面重来」，
    抛异常就没机会重来了。
    """
    from src.pages.common import wait_until

    state = {"n": 0}

    def ready():
        state["n"] += 1
        loc = page.get_by_text(_AUTO_SELECT_RE)
        try:
            n = loc.count()
        except Exception:
            n = 0
        for i in range(min(n, 12)):
            try:
                if loc.nth(i).is_visible():
                    return loc.nth(i)
            except Exception:
                continue
        # 第 1 轮就滚一次，之后每约 3 秒（轮询间隔 500ms）再滚一次。
        # 比原来的 5 秒勤一点：这里总共只有 10 秒，滚得太少就白等了。
        if state["n"] % 6 == 1:
            scroll_ad_form_to_top(page)
        return None

    return wait_until(page, ready, timeout_seconds=timeout_seconds) or None


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
    # 上（见下面的 _open_auto_select），这里留着它只是为了在确实处于加载中时
    # 多等一会。
    def not_loading():
        loc = page.get_by_text("正在加载中", exact=False)
        return True if loc.count() == 0 else None

    wait_until(page, not_loading, timeout_seconds=60)
    page.wait_for_timeout(500)

    # 点开「自动选择」。这一步包含「滚到顶 -> 10 秒内点不动就刷新页面重来」，
    # 因为搭到最后一个广告组时这个框有很大概率卡住不给点（使用者实测）。
    # 返回的就是顶层的「+ 添加创意素材」按钮 —— NOT the nested "+ 添加内容"
    # under "你的自有内容" (that path was confirmed inconsistent across
    # accounts, this one is not)
    top_add_btn = _open_auto_select(page)
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
        # scrollTop 的最大值是 scrollHeight - clientHeight，【不是 scrollHeight】。
        # 已经滚到底时 scrollTop 本来就不会再变，原来的判据
        # （after + 4 < scrollHeight 就算「没滚动成功」）会把「到底了」误判成
        # 「容器坏了」并直接抛错——实测 scrollTop 203->203、scrollHeight 886、
        # clientHeight 683，203+683=886 明明已经到底，却报「滚动容器没能滚动」，
        # 于是素材还够用的情况下整条流程被中断。
        at_bottom = (
            diag["after"] + diag.get("clientHeight", 0) + 4 >= diag["scrollHeight"]
        )
        if diag["after"] <= diag["before"] and not at_bottom:
            # 容器找到了但确实没滚动成功，也不要当成「素材不够」
            raise ValueError(
                f"素材库列表的滚动容器没能滚动（scrollTop {diag['before']}->{diag['after']}, "
                f"scrollHeight {diag['scrollHeight']}, clientHeight "
                f"{diag.get('clientHeight')}, 容器 {diag['tag']}.{diag['cls']}）"
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


def first_visible_input(page, locator, what, timeout_seconds=60):
    """取第一个【可见】的匹配输入框，并返回那个具体元素。

    为什么不能用 .first：DOM 里会同时存在多个占位符相同的输入框——一个广告组下有
    多个广告时是这样，沿「继续」把整个计划的广告组走一遍时也是这样（前面走过的
    广告组的表单还留在 DOM 里，只是不可见）。.first 拿到的可能是隐藏的那个，
    fill() 填进去页面上什么都不会变。

    实测就是这么错的（短剧那边）：URL 用 field.first.fill() 填到了隐藏的框上，
    而回读时又是「找第一个可见的」——两者不是同一个元素，于是
    【回读通过、页面上却是空的】，平台在发布时报缺少 URL。加了验证反而把问题掩盖了。
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


def commit_input(page, el):
    """让输入框失焦，把值真正提交给组件。

    使用者实测发现的：填完 URL 之后必须点一下框附近，值才会被保存；而且不能点
    左侧的广告列表——点那里不保存。原因是 fill() 只把值写进 DOM，组件是在
    blur / change 时才把值收进自己的状态，平台发布时读的是组件状态。

    这也是为什么【回读验证检测不出这个问题】：input_value() 读的是 DOM 里的值，
    一直是对的，但组件里是空的，所以发布时平台报缺少 URL。加了验证反而给了
    假的安全感——回读只能证明「写进去了」，不能证明「被接住了」。

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


def fill_and_verify(page, locator, value, what):
    """填一个输入框并回读确认——填和读【同一个元素】，见 first_visible_input。"""
    el = first_visible_input(page, locator, what)
    try:
        el.scroll_into_view_if_needed(timeout=10000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    try:
        el.click(timeout=10000)
    except Exception:
        pass
    el.fill("")
    el.fill(str(value))
    page.wait_for_timeout(500)
    commit_input(page, el)

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
        commit_input(page, el)
        try:
            got = el.input_value(timeout=3000)
        except Exception:
            got = None
    if got is not None and got.strip() != str(value).strip():
        raise ValueError(
            f"{what}填完读回的是 {str(got)[:80]!r}，期望 {str(value)[:80]!r}"
        )


def fill_ad_copy(page, ads_text: str):
    """填文案。

    2026-08-19 改：从 input_box.first.fill() 换成锁定可见元素 + 失焦提交 + 回读
    （见 first_visible_input / commit_input）。原来只有「一个计划一个广告组」这
    一种走法时 DOM 里只有一套表单，.first 恰好就是可见那个；新的「多广告组、
    每组素材不同」会沿「继续」把整个计划走一遍，DOM 里同时留着好几套表单，
    .first 就可能是隐藏的那个了。
    """
    from src.pages.common import wait_until

    def label_visible():
        loc = page.get_by_text("文案 (0/5)", exact=False)
        if loc.count() == 0:
            loc = page.get_by_text("文案", exact=True)
        for i in range(min(loc.count(), 12)):
            if loc.nth(i).is_visible():
                return loc.nth(i)
        return None

    label = wait_until(page, label_visible, timeout_seconds=60)
    if not label:
        raise ValueError("一直没找到'文案'区域")
    try:
        label.scroll_into_view_if_needed(timeout=10000)
    except Exception:
        pass

    box = page.get_by_placeholder("输入文案")
    if box.count() == 0:
        box = page.locator(
            "xpath=//*[contains(normalize-space(text()),'文案')]/following::textarea[1]"
        )
    fill_and_verify(page, box, ads_text, "文案")


def fill_landing_url(page, url: str):
    """填落地页链接（TikTok Minis URL）。同 fill_ad_copy，改成锁定可见元素后再填。"""
    fill_and_verify(
        page,
        page.get_by_placeholder("https://www.tiktok.com/minis/"),
        url,
        "落地页链接",
    )
