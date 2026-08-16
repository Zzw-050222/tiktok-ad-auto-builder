"""短剧商品库 —— 广告组层。

流程（使用者手动操作口述 + 探针实测确认）：
    广告组名称 -> 关联商品库 -> 特定剧集（搜索、点小圆圈、添加）
    -> 选择 TikTok Mini -> 目标 ROAS -> 地域 -> 继续

其中「地域」和小游戏一模一样，直接复用 src/pages/adgroup_page.py 里那套（今天刚
修好：结构定位、60 秒轮询、虚拟滚动处理），不复制一份。
"""

import re

# 商品库下拉收起态的占位文字
CATALOG_PLACEHOLDER = "请选择商品库"

# 商品库列表项里的「ID: 数字」。实测这个账号下有 2 个商品库，而且每个 ID 在 DOM 里
# 还有隐藏副本，所以必须【按 ID 匹配 + 只取可见的】，取第一个或按名称都会选错。
_CATALOG_ID_RE = r"ID[:：]\s*{}"

# 剧集行里的「Series ID: TIKTOKSERIES###」，可见文字，可精确匹配
_SERIES_ID_RE = r"Series ID[:：]\s*{}"

# 「选中」状态：和计划层那个开关同一套判断——class 上的标记、aria-checked、
# data-tea-model_value，任一命中即可，丢掉一个也还能工作。
_ON_CLASS_MARKER = "is-checked"


def _is_selected(el):
    """读一个单选圈/复选框的选中状态。读不出来返回 None（调用方必须区分"确定没选中"
    和"读不出"，不能把读不出当成没选中就去点——点错方向会把已选的取消掉）。"""
    try:
        cls = el.get_attribute("class")
    except Exception:
        cls = None
    try:
        aria = el.get_attribute("aria-checked")
    except Exception:
        aria = None
    try:
        tea = el.get_attribute("data-tea-model_value")
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
    if cls is not None or tea == "0":
        return False
    return None


def _first_visible(loc, limit=12):
    """一批匹配里挑出真正可见的那一个。这个后台到处是同文本的隐藏副本，
    盲取 .first 是今天反复踩到的坑。"""
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


def fill_ad_group_name(page, ad_group_name, timeout_seconds=60):
    """填广告组名称。

    刻意【不】沿用小游戏那边的「页面上第一个可见文本输入框」——那种写法没有任何锚点，
    页面上多渲染一个输入框就会填错地方。

    也【不】用 XPath 的 following:: 轴。第一版就是这么写的：
        //*[normalize-space(text())='广告组名称']/following::input[1]
    结果 60 秒都找不到，而截图上输入框明明就在那儿。原因是 following:: 穿不过
    shadow DOM，而这个后台大量使用自定义元素——这条教训项目里早有记录
    （见 src/pages/duplicate.py 里关于 following:: 的注释），只是我又踩了一次。

    改用「先定位到含『广告组名称』的那个区块，再在区块内找 input」。Playwright 的
    locator 链是能穿透 shadow DOM 的。
    """
    from src.pages.common import wait_until

    def input_ready():
        # ① 首选：作用域限定在「广告组名称」那个区块内
        for sel in ('[data-testid="lego-section-item"]',
                    '[data-testid="lego-hybrid-section-item"]'):
            section = page.locator(sel).filter(has_text="广告组名称")
            for i in range(min(section.count(), 4)):
                box = _first_visible(section.nth(i).locator('input[type="text"]'))
                if box:
                    return box
        # ② 兜底：页面上第一个可见文本输入框。放在最后而不是最前——它没有锚点，
        #    只有在结构定位失效时才用，用上了至少还能跑通。
        return _first_visible(page.locator('input[type="text"]'))

    box = wait_until(page, input_ready, timeout_seconds=timeout_seconds)
    if not box:
        raise ValueError(
            f"等了 {timeout_seconds} 秒没找到广告组名称输入框"
            "（区块定位和兜底的『第一个可见文本框』都没命中）"
        )
    box.fill("")
    box.fill(str(ad_group_name))
    page.wait_for_timeout(300)

    # 确认真的填进去了——这个页面上输入框不止一个，填错地方不会报错
    try:
        got = box.input_value(timeout=3000)
        if str(ad_group_name).strip() not in got:
            raise ValueError(
                f"广告组名称填完后读回的是 {got!r}，和期望的不一致，"
                "可能填到了别的输入框里。"
            )
    except ValueError:
        raise
    except Exception:
        pass


def select_product_catalog(page, catalog_id=None, timeout_seconds=60):
    """在「关联的商品库」下拉里选中商品库。

    catalog_id 为空时选【唯一可见的那一个】——目前这个账号下只有一个可用商品库。
    但如果发现可见的不止一个，就报错而不是挑一个：那说明账号下多了商品库，这时候
    猜哪个都可能投错，必须由人指定。

    无论哪种方式都只在【可见】的元素里挑。实测 DOM 里同一个 ID 会有隐藏副本
    （一个可见、一到两个不可见），而且还存在另一个商品库的 ID
    （7670120025105630216，不可见），盲取第一个会选错。
    """
    from src.pages.common import click_to_open, wait_until

    trigger = wait_until(
        page,
        lambda: _first_visible(page.get_by_text(CATALOG_PLACEHOLDER, exact=True)),
        timeout_seconds=timeout_seconds,
    )
    if not trigger:
        raise ValueError(
            f"等了 {timeout_seconds} 秒没看到「{CATALOG_PLACEHOLDER}」下拉。"
            "确认计划层的「设置商品库推广系列」开关已经打开——不打开就没有这一节。"
        )
    trigger.scroll_into_view_if_needed(timeout=5000)
    click_to_open(trigger, timeout=10000)

    all_ids = page.locator(r"text=/ID[:：]\s*\d{10,}/")

    def visible_ids():
        out = []
        for i in range(min(all_ids.count(), 20)):
            try:
                if all_ids.nth(i).is_visible():
                    out.append((i, all_ids.nth(i).inner_text().strip()))
            except Exception:
                continue
        return out or None

    found = wait_until(page, visible_ids, timeout_seconds=45)
    if not found:
        raise ValueError("下拉展开后，没有任何可见的商品库（等了 45 秒）")

    if catalog_id:
        want = str(catalog_id).strip()
        pattern = _CATALOG_ID_RE.format(re.escape(want))
        opt = _first_visible(page.locator(f"text=/{pattern}/"))
        if not opt:
            raise ValueError(
                f"下拉里没有可见的商品库 ID {want!r}。当前可见的是: "
                f"{[t for _, t in found]}"
            )
    else:
        if len(found) > 1:
            raise ValueError(
                f"没有指定商品库 ID，但下拉里有 {len(found)} 个可见商品库: "
                f"{[t for _, t in found]}。"
                "这时候挑哪个都可能投错，请在表里指定要用的商品库 ID。"
            )
        opt = all_ids.nth(found[0][0])

    opt.scroll_into_view_if_needed(timeout=5000)
    opt.click(timeout=10000)
    page.wait_for_timeout(2500)


def _episode_row_radio(page, row_text_locator):
    """给定剧集行里的某个文字元素，往上找到整行，再取行首那个小圆圈。

    使用者明确说过：必须点左边那个小圆圈才算选上，点整行没用。
    """
    js = """
    el => {
      let row = el;
      for (let k = 0; k < 8 && row; k++) {
        row = row.parentElement;
        if (!row) break;
        const r = row.getBoundingClientRect();
        // 整行：足够宽、且里面确实有一个单选/复选控件
        if (r.width > 400 &&
            row.querySelector('input[type=radio], input[type=checkbox], [role=radio], [role=checkbox]')) {
          const box = row.querySelector('[role=radio], [role=checkbox], input[type=radio], input[type=checkbox]');
          if (box) {
            box.setAttribute('data-drama-target', '1');
            return true;
          }
        }
      }
      return false;
    }
    """
    try:
        ok = row_text_locator.evaluate(js)
    except Exception:
        ok = False
    if not ok:
        return None
    marked = page.locator('[data-drama-target="1"]')
    return marked.first if marked.count() > 0 else None


# 剧集弹层里搜索维度下拉的取值。实测点开后有三项：
#     短剧名称
#     短剧 ID        <- 要选的这个，注意【中间有空格】
#     唯一短剧 ID    <- 另一个 ID，别选错
# 「短剧ID」写成无空格找不到——TikTok 会在中文和拉丁字母之间加空格，今天上午
# 「目标ROAS」实际渲染成「目标 ROAS」也是同一回事。
# 用锚定正则同时兼容有无空格，并且【必须锚定首尾】，否则会连「唯一短剧 ID」一起命中。
SEARCH_DIM_NAME = "短剧名称"
SEARCH_DIM_ID = "短剧 ID"
_SEARCH_DIM_ID_RE = re.compile(r"^\s*短剧\s*ID\s*$")


# 搜索维度下拉的真实结构（elementFromPoint 实测得出）：
#   <div class="vi-select vi-select--medium">        <- 容器
#     <div class="vi-input vi-input--suffix">
#       <input class="vi-input__inner">              <- 「短剧名称」是它的 value！
#       <i class="vi-select__caret vi-icon-arrow-up"> <- 箭头
#
# 关键：那四个字是 <input> 的 value，【不是文本节点】。所以按文字找它永远找不到，
# 只会找到表格里那个同名的列头 <th>。前三种写法（取第一个可见的、逐个候选试、
# 逐层祖先点击）失败的都是这一个原因。页面上也没有任何原生 <select>（实测 0 个）。
_SELECT_CSS = "div.vi-select"
_SELECT_INPUT_CSS = "input.vi-input__inner"


def _find_dimension_select(page):
    """找到那个 value 是「短剧名称」（或已经是「短剧ID」）的自定义下拉。

    按 value 认，而不是按位置或顺序——弹层里 .vi-select 不止一个（右上角还有个
    「可用」筛选）。
    """
    sels = page.locator(_SELECT_CSS)
    for i in range(min(sels.count(), 10)):
        sel = sels.nth(i)
        try:
            if not sel.is_visible():
                continue
            inp = sel.locator(_SELECT_INPUT_CSS)
            if inp.count() == 0:
                continue
            val = (inp.first.input_value(timeout=2000) or "").strip()
        except Exception:
            continue
        if val == SEARCH_DIM_NAME or _SEARCH_DIM_ID_RE.match(val):
            return sel, inp.first, val
    return None, None, None


def _switch_search_dimension_to_id(page):
    """把剧集弹层的搜索维度从「短剧名称」切成「短剧ID」。

    使用者明确说过：必须先选「短剧ID」，不能直接搜。
    切换成功的判据是那个 input 的 value 变成了「短剧ID」——只点不验证的话，
    下拉没展开或点空了都发现不了，后面按 ID 搜会搜不到，报出一个看起来毫不相干
    的「找不到这部剧」。
    """
    from src.pages.common import wait_until

    sel, inp, val = _find_dimension_select(page)
    if sel is None:
        return False
    if _SEARCH_DIM_ID_RE.match(val or ""):
        return True   # 已经是按 ID 搜了

    for _ in range(3):
        try:
            inp.click(timeout=8000)
        except Exception:
            try:
                sel.click(timeout=8000)
            except Exception:
                pass
        page.wait_for_timeout(1200)

        opt = _first_visible(page.get_by_text(_SEARCH_DIM_ID_RE))
        if opt:
            opt.click(timeout=8000)
            page.wait_for_timeout(1200)

        def switched():
            _, inp2, v2 = _find_dimension_select(page)
            return bool(v2 and _SEARCH_DIM_ID_RE.match(v2))

        if wait_until(page, switched, timeout_seconds=8):
            return True
        page.wait_for_timeout(800)

    return False


def add_specific_episode(page, series_id=None, series_name=None, timeout_seconds=60):
    """选中一部特定短剧。series_id 优先；没有 ID 时才退回按剧名。

    为什么优先用 ID：实测列表里存在
        「Mark of the Moon」        Series ID: TIKTOKSERIES097
        「Mark of the Moon Season 2」Series ID: TIKTOKSERIES098
    这样一对——按剧名搜「Mark of the Moon」会同时命中两部。今天在小游戏那边已经
    因为同类的子串包含关系（hkycool 是 hkycool02 的子串）静默选错过身份，所以这里
    按剧名匹配时【要求完全相等】，仍然有多行匹配就直接报错，绝不猜一个。
    """
    from src.pages.common import wait_until

    if not series_id and not series_name:
        raise ValueError("add_specific_episode 需要 series_id 或 series_name 至少一个")

    # ① 打开弹层
    add_btn = _first_visible(page.get_by_role("button", name="添加", exact=True))
    if not add_btn:
        raise ValueError("没找到「特定剧集」的「添加」按钮（先确认商品库已经选好）")
    add_btn.scroll_into_view_if_needed(timeout=5000)
    add_btn.click(timeout=10000)

    # ② 等剧集真正加载出来。以「Series ID」出现为准——弹层刚打开时文案是
    #    module_common_add_series 这类未翻译的 i18n 键名、列表显示「0件」，
    #    那是加载中的中间状态，据此判断会误以为没有剧集。
    loaded = wait_until(page, lambda: page.locator("text=/Series ID/").count() > 0,
                        timeout_seconds=timeout_seconds)
    if not loaded:
        raise ValueError(f"点开「添加」后等了 {timeout_seconds} 秒，剧集列表没加载出来")
    page.wait_for_timeout(1200)

    # ③ 用【剧名】搜索缩小范围，最终【按 Series ID 认行】。
    #
    #  为什么不去切「短剧ID」搜索维度：那个下拉试了两种写法都展不开（点文字没反应），
    #  而我们从 商品库-剧目.xlsx 同时拿到了剧名和 series_id，用不着它——搜索用能工作
    #  的默认维度（按名称），最终确认用最可靠的依据（Series ID）。比单用任何一种都稳：
    #  搜名字可能因为重名多出几行，但认 ID 不会认错。
    #
    #  搜索框必须用 exact=True。弹层里有两个：左栏「搜索商品系列」、右栏「搜索」，
    #  而 get_by_placeholder("搜索") 是子串匹配，会先命中左栏那个——实测就是这么搜错
    #  地方的，输进去之后右边列表一行没少（Series ID 行数搜索前后都是 20）。
    # 使用者明确要求：必须先把维度切成「短剧ID」，不能直接搜。
    if series_id:
        if not _switch_search_dimension_to_id(page):
            raise ValueError(
                "没能把搜索维度切换成「短剧ID」。这个下拉的「短剧名称」是 <input> 的 "
                "value 而不是文本节点，所以按文字找不到它；代码是按 "
                "div.vi-select 里 input 的 value 来认的。"
            )
        keyword = series_id
    else:
        keyword = series_name

    search = _first_visible(page.get_by_placeholder("搜索", exact=True))
    if not search:
        raise ValueError(
            "没找到剧集列表的搜索框（右栏那个 placeholder 恰好是「搜索」的）。"
            "注意左栏还有一个「搜索商品系列」，不能用子串匹配。"
        )
    search.click(timeout=5000)
    search.fill(str(keyword))
    page.keyboard.press("Enter")
    page.wait_for_timeout(3500)

    # ④ 定位目标行：有 ID 用 ID，没有就用完全相等的剧名
    if series_id:
        want = str(series_id).strip()
        pattern = _SERIES_ID_RE.format(re.escape(want))
        matches = page.locator(f"text=/{pattern}/")
        how = f"Series ID {want!r}"
    else:
        want = str(series_name).strip()
        matches = page.get_by_text(want, exact=True)
        how = f"剧名 {want!r}（完全相等）"

    target = wait_until(page, lambda: _first_visible(matches), timeout_seconds=30)
    if not target:
        raise ValueError(f"搜索 {keyword!r} 之后，列表里没有可见的 {how}")

    visible_count = sum(
        1 for i in range(min(matches.count(), 12))
        if _safe_visible(matches.nth(i))
    )
    if visible_count > 1 and not series_id:
        raise ValueError(
            f"按 {how} 匹配到 {visible_count} 行，无法确定是哪一部"
            f"（例如「Mark of the Moon」和「Mark of the Moon Season 2」）。"
            "请在表格里改用 Series ID 指定，或填写完整不重名的剧名。"
        )

    # ⑤ 点行首那个小圆圈——使用者明确说过点整行没用
    radio = _episode_row_radio(page, target)
    if not radio:
        raise ValueError(f"找到了 {how} 那一行，但没能定位到行首的选择圈")

    if _is_selected(radio) is True:
        pass  # 已经选中了，别再点——再点会取消
    else:
        radio.scroll_into_view_if_needed(timeout=5000)
        radio.click(timeout=10000)
        page.wait_for_timeout(800)
        # 必须确认真的变成选中态（使用者说「冒绿色了就是选上了」）
        ok = wait_until(page, lambda: _is_selected(radio) is True, timeout_seconds=15)
        if not ok:
            raise ValueError(
                f"点了 {how} 那一行的选择圈，但它没有变成选中态。"
                "不确认选中就点「添加」会得到一个没有剧集的广告组。"
            )

    # ⑥ 弹层右下角的「添加」确认。
    #
    # 必须限定在弹层容器内。页面上同时存在两个「添加」：
    #   * 底层页面「特定剧集」旁边那个（就是用来打开这个弹层的）
    #   * 弹层右下角的确认按钮
    # 第一版按「页面上最后一个可见且可用的添加」来挑，挑到了底层那个，点击被弹层的
    # 遮罩拦下，报 "<div class=\"mask\"> ... subtree intercepts pointer events"。
    # 注意底层那个按钮在 Playwright 眼里是 visible+enabled 的——被遮罩挡住不影响
    # 这两个判断，所以光靠可见性筛不掉它，必须靠作用域。
    dialog = None
    for sel in ('[class*="catalog-choose-products"]',
                '[data-testid^="side-slip-sideslip"]'):
        loc = page.locator(sel)
        for i in range(min(loc.count(), 4)):
            try:
                if loc.nth(i).is_visible():
                    dialog = loc.nth(i)
                    break
            except Exception:
                continue
        if dialog is not None:
            break

    scope = dialog if dialog is not None else page
    confirm = _first_visible(scope.get_by_role("button", name="添加", exact=True))
    if not confirm:
        raise ValueError(
            "剧集选中了，但没在弹层里找到「添加」确认按钮。"
            "注意不能用页面级选择器——底层页面上「特定剧集」旁边还有一个同名按钮，"
            "点它会被弹层遮罩拦下。"
        )
    confirm.click(timeout=10000)
    page.wait_for_timeout(2500)


def _safe_visible(loc):
    try:
        return loc.is_visible()
    except Exception:
        return False


MINI_PLACEHOLDER = "选择 TikTok Mini"


# 找「短剧」那个区块里的选择器，并给它打个标记好让 Playwright 抓到。
#
# 这个页面上【两套组件库并存】，别把一套的规律套到另一套上：
#   ks-*  用在主表单（商品库、TikTok Mini）—— ks-input-selector，文字在 shadow DOM 里
#   vi-*  用在弹层内（搜索维度、可用性、分页）—— div.vi-select + 只读 input
# 我先按 vi-select 找 TikTok Mini，找不到；又按文字找，也找不到——因为占位文字在
# ks-input-selector 的 shadow root 里，普通的 querySelectorAll('*') 扫不到。
# 所以这里按【区块结构】定位：找标题恰好是「短剧」的 lego-section-item，
# 取它内容区里的 ks-input-selector。不依赖那串带哈希的 data-testid（KsSelect-...-2EimZ5）。
_MARK_MINI_JS = """
() => {
  document.querySelectorAll('[data-drama-mini]').forEach(e => e.removeAttribute('data-drama-mini'));
  const sections = document.querySelectorAll('[data-testid="lego-section-item"]');
  for (const sec of sections) {
    const header = sec.querySelector('[data-testid="lego-section-item-header"]');
    if (!header) continue;
    const title = (header.innerText || '').trim();
    if (title !== '短剧') continue;          // 恰好是「短剧」，不是「优化位置」那种
    const sel = sec.querySelector('ks-input-selector, [data-testid^="KsSelect"]');
    if (!sel) continue;
    const r = sel.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    sel.setAttribute('data-drama-mini', '1');
    // 必须递归 shadow DOM 取文字：ks-input-selector 的显示内容在它的 shadow root 里，
    // 宿主元素的 innerText 【读不到】——第一版就是用 innerText 判断"选中了没"，
    // 结果点击前后都是空字符串，验证永远失败。
    const deepText = (node) => {
      let out = '';
      const walk = (n) => {
        if (!n) return;
        if (n.nodeType === 3) { out += n.textContent; return; }
        if (n.shadowRoot) walk(n.shadowRoot);
        for (const c of n.childNodes || []) walk(c);
      };
      walk(node);
      return out.replace(/\s+/g, ' ').trim();
    };
    return {found: true, text: deepText(sel).slice(0, 60)};
  }
  return {found: false};
}
"""


def _find_mini_select(page):
    """找「短剧」区块里的 TikTok Mini 选择器，返回 (locator, 当前显示文字)。"""
    try:
        r = page.evaluate(_MARK_MINI_JS)
    except Exception:
        return None, None
    if not r.get("found"):
        return None, None
    loc = page.locator('[data-drama-mini="1"]')
    return (loc.first, r.get("text", "")) if loc.count() > 0 else (None, None)


def select_tiktok_mini(page, tt_mini_id=None, timeout_seconds=60):
    """选「短剧」区块里那个 TikTok Mini。

    按【TT Mini ID】精确匹配，和商品库、剧集同一套路。实测下拉展开后每一项长这样：
        We Shorts
        短剧 | ID: mnk980l0ef79v57q      <- 这个 ID 就是表里的 TT Mini ID
        有效
    所以不用「点第一个可见项」——那种写法在账号下多一个 Mini 时就会静默选错，
    而这个后台今天已经反复证明「同类元素不止一个」是常态。
    tt_mini_id 为空时才退回选唯一可见项，并且发现多于一个就报错。
    """
    from src.pages.common import wait_until

    def ready():
        s2, t2 = _find_mini_select(page)
        return (s2, t2) if s2 is not None else None

    got = wait_until(page, ready, timeout_seconds=timeout_seconds)
    if not got:
        raise ValueError(
            f"等了 {timeout_seconds} 秒没找到「短剧」区块里的 TikTok Mini 选择器"
            "（按标题恰好是「短剧」的 lego-section-item 找的）"
        )
    sel, before_text = got
    if before_text and before_text.strip():
        return   # 已经选好了，别再动

    for attempt in range(3):
        sel.scroll_into_view_if_needed(timeout=5000)
        try:
            sel.click(timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(2000)

        if tt_mini_id:
            want = str(tt_mini_id).strip()
            opt = _first_visible(page.locator(f"text=/ID[:：]\\s*{re.escape(want)}/"))
            if not opt:
                page.wait_for_timeout(1500)
                continue
        else:
            ids = page.locator(r"text=/ID[:：]\s*[a-z0-9]{10,}/")
            vis = [i for i in range(min(ids.count(), 10))
                   if _safe_visible(ids.nth(i))]
            if not vis:
                page.wait_for_timeout(1500)
                continue
            if len(vis) > 1:
                raise ValueError(
                    f"没有指定 TT Mini ID，但下拉里有 {len(vis)} 个可见候选，"
                    "这时候挑哪个都可能选错，请在表里填 TT Mini ID。"
                )
            opt = ids.nth(vis[0])

        opt.scroll_into_view_if_needed(timeout=5000)
        opt.click(timeout=10000)
        page.wait_for_timeout(2000)

        def picked():
            _, t = _find_mini_select(page)
            return bool(t and t.strip())

        if wait_until(page, picked, timeout_seconds=10):
            return

    _, t = _find_mini_select(page)
    raise ValueError(
        f"选 TikTok Mini 失败：点完之后选择器显示的仍是 {t!r}。"
        + (f"（要找的是 ID {tt_mini_id!r}）" if tt_mini_id else "")
    )
