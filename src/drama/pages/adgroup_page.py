"""短剧商品库 —— 广告组层。

流程（使用者手动操作口述 + 探针实测确认）：
    广告组名称 -> 关联商品库 -> 特定剧集（搜索、点小圆圈、添加）
    -> 选择 TikTok Mini -> 目标 ROAS -> 地域 -> 继续

其中「地域」和小游戏一模一样，直接复用 src/pages/adgroup_page.py 里那套（今天刚
修好：结构定位、60 秒轮询、虚拟滚动处理），不复制一份。
"""

import re
import time

from src.pages.common import ON_CLASS_MARKER, is_selected
from src.pages.value_type import (
    VALUE_TYPE_AD_REVENUE,
    VALUE_TYPE_IAP,
    option_row_of,
    select_ad_revenue_value_type,
    value_type_box,
    wait_value_type_settled,
)
from src.pages.roas import (
    ROAS_PLACEHOLDER_RE,
    ROAS_VALUE_RE,
    bidding_section_text,
    current_roas,
    same_number,
    set_target_roas_shared,
    visible_placeholders,
)
from src.pages.viewport import (
    MEASURE_JS as _MEASURE_JS,
    SCROLL_BY_JS as _SCROLL_BY_JS,
    SCROLL_CENTER_JS as _SCROLL_CENTER_JS,
    on_screen,
    scroll_into_comfortable_view,
    viewport_h,
)

# 商品库下拉收起态的占位文字
CATALOG_PLACEHOLDER = "请选择商品库"

# 商品库列表项里的「ID: 数字」。实测这个账号下有 2 个商品库，而且每个 ID 在 DOM 里
# 还有隐藏副本，所以必须【按 ID 匹配 + 只取可见的】，取第一个或按名称都会选错。
_CATALOG_ID_RE = r"ID[:：]\s*{}"

# 剧集行里的「Series ID: TIKTOKSERIES###」，可见文字，可精确匹配
_SERIES_ID_RE = r"Series ID[:：]\s*{}"

# 「选中」状态的判断搬到了 src/pages/common.py（「短剧端计划」选优化位置的三个
# 单选圈也要用）。这里保留同名私有别名，本文件的调用点一个字都不用改。
_ON_CLASS_MARKER = ON_CLASS_MARKER
_is_selected = is_selected


# 视口/滚动那一套搬到了 src/pages/viewport.py（「短剧端计划」那个模式也要用，
# 不复制第二份）。这里保留同名私有别名，本文件的调用点一个字都不用改。
_viewport_h = viewport_h
_on_screen = on_screen
_scroll_into_comfortable_view = scroll_into_comfortable_view


def _first_visible(loc, limit=200):
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


def _catalog_section_text(page, limit=120):
    """读「关联的商品库」这一节当前显示的文字（选好了会是商品库名字）。读不到返回 None。"""
    try:
        lab = page.get_by_text("关联的商品库", exact=True)
        if lab.count() == 0:
            return None
        return lab.first.evaluate("""(el, lim) => {
          const deep = (n) => {
            let out = '';
            const walk = (x) => {
              if (!x) return;
              if (x.nodeType === 3) { out += x.textContent; return; }
              if (x.tagName === 'SLOT') { for (const a of x.assignedNodes()) walk(a); return; }
              if (x.shadowRoot) { walk(x.shadowRoot); return; }
              for (const c of x.childNodes || []) walk(c);
            };
            walk(n);
            return out.replace(/\\s+/g, ' ').trim();
          };
          let box = el.parentElement;
          for (let k = 0; k < 5 && box; k++) {
            const t = deep(box).replace('关联的商品库', '').trim();
            if (t) return t.slice(0, lim);
            box = box.parentElement;
          }
          return null;
        }""", limit)
    except Exception:
        return None


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

    # 先等「商品库」这一节渲染出来，再判断要不要选。
    # 不能一上来就死等占位文字：商品库和 TikTok Mini / ROAS / 地域一样，
    # 会随着账号里已发布的计划变多而【自动带值】。带值时占位文字「请选择商品库」
    # 根本不出现，死等就是白等满 60 秒然后报一句误导的错（说「开关没打开」，
    # 其实开关好好的、商品库也好好的，只是已经填上了）。
    # 今天 Mini、价值类型、ROAS、地域都补过这个「已经对了就跳过」的分支，
    # 只有商品库漏了——这是同一个坑的第五次。
    wait_until(
        page,
        lambda: page.get_by_text("关联的商品库", exact=True).count() > 0,
        timeout_seconds=timeout_seconds,
    )

    trigger = _first_visible(page.get_by_text(CATALOG_PLACEHOLDER, exact=True))
    if not trigger:
        trigger = wait_until(
            page,
            lambda: _first_visible(page.get_by_text(CATALOG_PLACEHOLDER, exact=True)),
            timeout_seconds=20,
        )
    if not trigger:
        # 占位文字不在，可能是【已经选好了】。把这一节的实际内容读出来判断，
        # 而不是直接报错。
        shown = _catalog_section_text(page)
        if shown and CATALOG_PLACEHOLDER not in shown:
            print(f"          [商品库] 已经选好了（{shown[:40]!r}），不用再选", flush=True)
            return
        raise ValueError(
            f"等了 {timeout_seconds} 秒既没看到「{CATALOG_PLACEHOLDER}」下拉，"
            f"也读不出已选的商品库。「商品库」这一节现在的内容: {shown!r}\n"
            "如果这一节整个不存在，检查计划层的「设置商品库推广系列」开关有没有打开。"
        )
    trigger.scroll_into_view_if_needed(timeout=5000)
    page.wait_for_timeout(500)

    # ---- 展开下拉：必须用【真实鼠标点坐标】，不能点占位文字元素 ----
    #
    # 这一步坑了很久，根因探针实测：
    #   祖先0 <span class="...__display--placeholder">  pointer-events: none  ← 占位文字
    #   祖先1 <div  class="value-field__texted__input">  pointer-events: auto  ← 这层才收点击
    # 占位文字自己【不接收点击】，点它等于没点，下拉一动不动。使用者一直说
    # 「是点不上那个框」「点请选择商品库右边一点的白色部分」，说的就是这件事。
    #
    # 换成 page.mouse.click(坐标) 之后，下拉立刻展开，里面就是
    # 「短剧 商品库 / ID: 7665919003159774992」。
    #
    # 更要记住的教训：在此之前我以为是「匹配规则太窄」，接连改了三版选项匹配
    # （去掉 ID、改 role=option、读弹层文字），全都是在解决一个不存在的问题——
    # 下拉压根没开，匹配什么都匹配不到。中途还把页头的广告主账号名
    # （class=advertiser_name，坐标 (1387,27)）误认成商品库。
    # 报错说「没有任何可见的商品库」时，先确认下拉是不是真的开了。
    def dropdown_open():
        return page.locator(r"text=/ID[:：]\s*\d{10,}/").count() > 0

    opened = False
    for attempt in range(3):
        box = trigger.bounding_box()
        if not box:
            break
        # 点框的中部偏右：占位文字那一层不收点击，右边的空白区域属于外层容器。
        cx = box["x"] + box["width"] * 0.75
        cy = box["y"] + box["height"] / 2
        page.mouse.click(cx, cy)
        page.wait_for_timeout(2500)
        if wait_until(page, lambda: dropdown_open() or None, timeout_seconds=20):
            opened = True
            break
        print(f"          [商品库] 第{attempt + 1}次点击没能展开下拉，重试", flush=True)
        page.keyboard.press("Escape")
        page.wait_for_timeout(800)

    if not opened:
        raise ValueError(
            "点了「关联的商品库」那个框，但下拉一直没有展开。\n"
            "注意占位文字本身是 pointer-events:none，必须点框（这里已经用真实鼠标"
            "点坐标了）。如果仍然打不开，多半是这个广告主下没有可用商品库，"
            "或者页面报了「网络错误。请稍后重试。」——刷新后重跑。"
        )

    # ---- 选项匹配：按 ID 行找（这本来就是对的，之前被我误改过，已还原）----
    # DOM 里同一个 ID 会有隐藏副本，所以只在【可见】的里面挑。
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
        raise ValueError("下拉已展开，但里面没有任何带 ID 的商品库（等了 45 秒）")

    if catalog_id:
        want = str(catalog_id).strip()
        hit = [(i, t) for i, t in found if want in t]
        if not hit:
            raise ValueError(
                f"下拉里没有商品库 ID {want!r}。当前可见的是: {[t for _, t in found]}"
            )
        opt = all_ids.nth(hit[0][0])
    else:
        # 没指定就要求唯一。使用者确认：所有投短剧的账号共用同一个商品库，
        # 所以正常情况下这里就是一个。多于一个时不猜，挑错商品库会投错钱。
        if len(found) > 1:
            raise ValueError(
                f"没有指定商品库 ID，但下拉里有 {len(found)} 个可见商品库: "
                f"{[t for _, t in found]}。请在表里指定要用的商品库 ID。"
            )
        opt = all_ids.nth(found[0][0])
        print(f"          [商品库] 选唯一可见的: {found[0][1][:50]!r}", flush=True)

    opt.scroll_into_view_if_needed(timeout=5000)
    opt.click(timeout=10000)
    page.wait_for_timeout(2000)

    # 点完必须确认【真的选上了】，不能点完就走。
    # 判据：占位文字「请选择商品库」从页面上消失——选中后框里显示的是商品库名字。
    #
    # 这一步原来是没有的，于是商品库没选上时这个函数照样返回成功，错误延后到
    # 「特定剧集」才爆出来，报的还是「没找到添加按钮」——看错误信息根本想不到
    # 是商品库没选上。本项目在「验证动作而不是验证结果」上已经栽过好几次。
    def selected():
        return _first_visible(page.get_by_text(CATALOG_PLACEHOLDER, exact=True)) is None

    if not wait_until(page, selected, timeout_seconds=30):
        # 再点一次那个选项——下拉可能还开着，第一次点没落到实处
        try:
            opt.click(timeout=8000)
            page.wait_for_timeout(2000)
        except Exception:
            pass
    if not wait_until(page, selected, timeout_seconds=30):
        raise ValueError(
            f"点了商品库选项，但「{CATALOG_PLACEHOLDER}」这几个字仍在页面上，"
            "说明商品库没有真正选上。后面的「特定剧集」依赖它，所以在这里就停住，"
            "而不是带着未选中的状态往下跑。"
        )
    page.wait_for_timeout(1000)


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




# 把页面上所有 ks 选择器列出来（含各自的标签和真实显示文字），用于
#   ① 找到该点的那个 TikTok Mini 框
#   ② 验证到底选中了没
#
# 为什么不再用「找标题恰好是『短剧』的 lego-section-item」：实测那样标记到的不是
# 使用者截图里显示 We Shorts 的那个框，而是另一个显示「无法使用此 TikTok Mini…」的
# 元素，导致【明明选中了却判定失败】。页面上「短剧」这两个字至少出现三处（优化位置
# 的值、短剧字段的标签、左栏计划名），靠标题文字锚定不可靠。
#
# deepText 用【组合树】遍历，这是上一版报错文字里同一句出现两遍的原因：
# 老写法对有 shadowRoot 的宿主同时走 shadowRoot 和 childNodes，被 slot 分配的
# 光 DOM 内容就被数了两遍。正确做法是遇到 <slot> 走 assignedNodes()，
# 遇到 shadowRoot 就【只】走 shadow 树。
# 读一个元素的显示文字，会走进它自己的 shadow root。
#
# 注意分工：【找元素】必须用 Playwright 定位器，【读文字】才用这段 JS。
# document.querySelectorAll 穿不透 shadow DOM——上一版整个清单用原生 JS 扫，
# 结果「页面上 0 个选择器」，而同一时刻 get_by_text 明明能找到那段占位文字。
# Playwright 的 CSS 引擎会穿透 shadow root，所以用它找；找到之后在元素上
# evaluate 是可以正常访问该元素自己的 shadowRoot 的。
#
# 遍历用【组合树】：遇到 <slot> 走 assignedNodes()，遇到 shadowRoot 就只走 shadow 树。
# 老写法对有 shadowRoot 的宿主同时走 shadowRoot 和 childNodes，被 slot 分配的内容
# 会被数两遍——报错信息里「无法使用此 TikTok Mini」出现两次就是这么来的。
_DEEP_TEXT_JS = """
el => {
  let out = '';
  const walk = (n) => {
    if (!n) return;
    if (n.nodeType === 3) { out += n.textContent; return; }
    if (n.tagName === 'SLOT') { for (const a of n.assignedNodes()) walk(a); return; }
    if (n.shadowRoot) { walk(n.shadowRoot); return; }
    for (const c of n.childNodes || []) walk(c);
  };
  walk(el);
  return out.replace(/\s+/g, ' ').trim();
}
"""

# 主表单上的选择器控件。ks-* 这套用在主表单，vi-* 那套用在弹层里，别混用。
_SELECTOR_CSS = 'ks-input-selector, [data-testid^="KsSelect"]'


def _mini_inventory(page, limit=40):
    """列出主表单上所有可见的选择器：[{i, text, y, h}]。

    出错【不吞异常】——上一版 try/except 直接 return []，把「JS 报错」和
    「页面上真的没有」混为一谈，白跑了一轮才发现清单是空的。
    """
    out = []
    loc = page.locator(_SELECTOR_CSS)
    try:
        n = loc.count()
    except Exception as e:
        print(f"          [mini] 数选择器出错: {type(e).__name__}: {str(e)[:80]}",
              flush=True)
        return out
    for i in range(min(n, limit)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            box = el.bounding_box()
            text = el.evaluate(_DEEP_TEXT_JS) or ""
        except Exception:
            continue
        out.append({
            "i": i,
            "text": text[:80],
            "y": round(box["y"]) if box else None,
            "h": round(box["height"]) if box else None,
        })
    return out


def _sel_locator(page, i):
    return page.locator(_SELECTOR_CSS).nth(i)


def _mini_is_selected(page, mini_name=None, tt_mini_id=None):
    """选中判据：占位文字「选择 TikTok Mini」消失，且 Mini 名字出现在页面上。

    刻意【不】按组件类型去读某个框的文字。实测整页只有两个
    ks-input-selector/KsSelect，一个在排期区（显示「刷新新增」）、一个是空的——
    Mini 框根本不属于这类组件。上一版按组件类型挑「靠下那个」，结果点到排期区去了。

    也不能只看「名字出现了」：下拉展开时选项本身就写着 We Shorts。所以要求
    占位文字同时消失——选中后框里显示的就是 Mini 名字，占位文字会被替换掉。
    """
    name = (mini_name or "").strip()
    placeholder_gone = _first_visible(
        page.get_by_text(MINI_PLACEHOLDER, exact=True)) is None
    if not name:
        return placeholder_gone
    shown = _first_visible(page.get_by_text(name, exact=True)) is not None
    return placeholder_gone and shown


# _option_row_of 也搬到了 src/pages/value_type.py（选 Mini 和选价值类型都用它）。
_option_row_of = option_row_of


def _mini_text_is_selected(text, tt_mini_id=None):
    """判断 TikTok Mini 选择器显示的文字是否代表【真的选中了】。

    只看「非空」是不够的——TikTok 会把错误提示也渲染在这个框里：
        无法使用此 TikTok Mini。可能是你的账号权限存在问题，或未满足某些使用要求。
    这类文字非空、也可能包含 Mini 的 ID，所以必须显式排除。
    """
    if not text or not text.strip():
        return False
    t = text.strip()
    for bad in ("无法使用", "权限", "未满足", "选择 TikTok Mini"):
        if bad in t:
            return False
    if tt_mini_id:
        return str(tt_mini_id).strip() in t
    return True


# 「短剧」这个字段的标题，拿来当【滚动锚点】。
#
# 使用者的原话：「你就下滑到优化和出价下面短剧这两个字 没那么难找吧 然后看到
# 短剧两字下面的这个框去点击」——就是这个锚点。
#
# 为什么锚在标题上而不是那个框上：要点的占位文字「选择 TikTok Mini」在
# ks-input-selector 的 shadow root 里，算位置要往上找祖先（历史上 bounding_box()
# 对它返回 None，见 select_tiktok_mini 的说明）；而这个标题是普通 DOM 里的一小段
# 文字，自己就有真实盒子，位置一次就算准，不用猜该拿哪个祖先。
#
# 只当锚点、【不】当点击目标：这套「按区块标题找」的写法早先被用来找那个框本身，
# 结果标记到的是同区块里另一个显示「无法使用此 TikTok Mini…」的元素
# （见 _MARK_MINI_JS 上面那段说明）。锚点用错顶多滚的位置差一点，
# 点击目标用错就会点到别处去。
_MINI_ANCHOR_JS = """
() => {
  document.querySelectorAll('[data-drama-mini-anchor]').forEach(
    e => e.removeAttribute('data-drama-mini-anchor'));
  const secs = document.querySelectorAll('[data-testid="lego-section-item"]');
  for (const sec of secs) {
    const h = sec.querySelector('[data-testid="lego-section-item-header"]');
    if (!h) continue;
    // 恰好是「短剧」两个字。页面上「短剧」至少出现三处（优化位置的值、
    // 这个字段的标题、左栏计划名），所以要 exact，不能用 includes。
    if ((h.innerText || '').trim() !== '短剧') continue;
    const r = h.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    h.setAttribute('data-drama-mini-anchor', '1');
    return true;
  }
  return false;
}
"""


def _scroll_to_drama_field(page):
    """滚到「短剧」这个字段上（TikTok Mini 那个框就在它下面）。

    找不到锚点就返回 False，让调用方退回去直接滚那个框——锚点是【加速】手段，
    不是新的必要条件，找不到不该让整步失败。
    """
    try:
        if not page.evaluate(_MINI_ANCHOR_JS):
            return False
    except Exception:
        return False
    loc = page.locator('[data-drama-mini-anchor="1"]')
    try:
        if loc.count() == 0:
            return False
    except Exception:
        return False
    return _scroll_into_comfortable_view(page, loc.first, label="短剧字段")


def select_tiktok_mini(page, tt_mini_id=None, mini_name=None, timeout_seconds=90):
    """选「短剧」区块下面那个 TikTok Mini。

    使用者演示的操作就三步，也是实测唯一走通过的一条路：
        往下滑到「短剧」-> 点「选择 TikTok Mini」这段文字 -> 点列表里的 Mini 名字

    走过的弯路，别再回去：
      * 按组件类型定位（ks-input-selector / KsSelect）——整页只有两个这类元素，
        一个在排期区显示「刷新新增」、一个是空的，Mini 框不属于这类组件。
        按类型挑「靠下那个」会点到排期区。
      * 用 document.querySelectorAll 扫元素——穿不透 shadow DOM，扫出 0 个。
        Playwright 的定位器会穿透，所以【找元素一律用定位器】。

    真正坏过的是【验证】不是点击：占位文字是 shadow root 里的 <slot>，
    bounding_box() 返回 None，导致滚动函数直接放弃、页面一次都没滚过；
    验证又死盯错误的元素，把已经选上的 We Shorts 判成失败。
    """
    from src.pages.common import robust_click, wait_until

    name = (mini_name or "").strip()
    mid = (tt_mini_id or "").strip()

    def state():
        ph = _first_visible(page.get_by_text(MINI_PLACEHOLDER, exact=True))
        nm = _first_visible(page.get_by_text(name, exact=True)) if name else None
        return ph, nm

    if _mini_is_selected(page, name, mid):
        return

    for attempt in range(3):
        # ① 找占位文字。Playwright 的 get_by_text 能穿透 shadow DOM。
        anchor = wait_until(
            page,
            lambda: _first_visible(page.get_by_text(MINI_PLACEHOLDER, exact=True)),
            timeout_seconds=25,
        )
        if anchor is None:
            if _mini_is_selected(page, name, mid):
                return
            print(f"          [mini] 第{attempt + 1}轮：没找到「{MINI_PLACEHOLDER}」",
                  flush=True)
            page.wait_for_timeout(2000)
            continue

        # ② 滚到位。先拿「短剧」这个字段标题当锚点，一次就能算准；
        #    没找到锚点、或者滚完那个框还是不在屏幕上，才退回去直接滚它自己。
        #    判「在不在屏幕上」必须用 _on_screen —— _first_visible 认为屏幕外的
        #    元素也「可见」，用它判断的话等于永远不滚。
        if not _scroll_to_drama_field(page) or not _on_screen(page, anchor):
            _scroll_into_comfortable_view(page, anchor, label="mini框")
        page.wait_for_timeout(300)

        # ③ 点这段文字，展开列表
        robust_click(page, anchor, timeout=8000)
        page.wait_for_timeout(2000)

        # ④ 点列表里的 Mini 名字
        def find_option():
            if name:
                t = _first_visible(page.get_by_text(name, exact=True))
                if t is not None:
                    return t
            if mid:
                return _first_visible(page.locator(f"text=/{re.escape(mid)}/"))
            return None

        target = wait_until(page, find_option, timeout_seconds=15)
        if target is None:
            print(f"          [mini] 下拉里没找到 {name!r}，重试", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            continue

        row = _option_row_of(page, target) or target
        robust_click(page, row, timeout=8000)
        page.wait_for_timeout(2500)

        if wait_until(page, lambda: _mini_is_selected(page, name, mid),
                      timeout_seconds=25):
            print(f"          [mini] 已选中 {name!r}", flush=True)
            return
        ph, nm = state()
        print(f"          [mini] 还没选上：占位文字还在={ph is not None} "
              f"{name!r}可见={nm is not None}", flush=True)
        page.wait_for_timeout(1500)

    raise ValueError(
        f"选 TikTok Mini 失败：点了 3 轮，占位文字「{MINI_PLACEHOLDER}」仍在页面上。"
        "\n注意：「无法使用此 TikTok Mini…」是【未选中】时的默认提示，不代表平台拒绝。"
    )


# 价值类型那一套搬到了 src/pages/value_type.py（「短剧端计划」也要求
# 「广告收入价值」，行为一模一样，不复制第二份）。这里保留同名别名。
_value_type_box = value_type_box
_wait_value_type_settled = wait_value_type_settled


# 目标 ROAS 那一套搬到了 src/pages/roas.py（「短剧端计划」的出价区块结构一模一样，
# 不复制第二份）。这里保留同名别名，本文件和 drama/builder.py 的调用点都不用改。
_DRAMA_ROAS_PLACEHOLDER_RE = ROAS_PLACEHOLDER_RE
_ROAS_VALUE_RE = ROAS_VALUE_RE
_same_number = same_number
_current_roas = current_roas
_visible_placeholders = visible_placeholders
_bidding_section_text = bidding_section_text
select_target_roas_drama = set_target_roas_shared


def _audience_section_text(page, limit=500):
    """「受众定向」区块的可见文字。读不到返回 None。"""
    try:
        sec = page.get_by_text("受众定向", exact=True)
        if sec.count() == 0:
            return None
        return sec.first.evaluate("""(el, lim) => {
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            n = n.parentElement;
            if (!n) break;
            const t = (n.innerText || '').replace(/\\s+/g, ' ').trim();
            if (t.length > 80) return t.slice(0, lim);
          }
          return null;
        }""", limit)
    except Exception:
        return None


def _regions_already_set(page, region_pairs):
    """要选的地区是不是【本来就已经选好了】。

    地域和 TikTok Mini、目标 ROAS 一样是「共享设置」：新建广告组时会从账号/计划层
    带过来。实测新建的广告组里「地域: 美国」已经填好，这时候去点那个框【根本不会
    展开下拉】——诊断日志是「搜索输入框 30 秒没出现」，看起来像点不中，其实是
    不需要点。使用者也确认：选完剧集后 Mini / 价值类型 / ROAS / 地域都不用重新选，
    直接点「继续」去广告层就行，广告层的东西才要重新填。

    这里不写成「无条件跳过」而是「已经对了才跳过」：万一表格里的地区和页面上带过来的
    不一样（换国家投放），还是要真的去选。判据是要选的每个地区名都出现在
    「受众定向」区块里。
    """
    txt = _audience_section_text(page)
    if not txt:
        return False
    return all(str(name).strip() and str(name).strip() in txt
               for _rid, name in region_pairs)


def set_regions_drama(page, region_pairs):
    """选地域。已经选好了就跳过；确实要改才走小游戏那套 set_regions。

    多这一层的原因见 _regions_already_set：地域是共享设置，新建广告组时通常已经
    填好，此时那个框点不开——我为此改了三轮「滚动」都是修错了方向，而答案就在
    自己打印的诊断里（受众定向区块文字里明明白白写着已选的国家）。

    真要改时才滚动+点击：地域在页面很下面，而且不能依赖上一步「填 ROAS」顺带把
    页面滚下去（ROAS 现在已是目标值就跳过了）。
    """
    from src.pages.adgroup_page import _wait_for_region_field, set_regions

    if _regions_already_set(page, region_pairs):
        names = "、".join(str(n) for _r, n in region_pairs)
        print(f"          [地域] 已经是「{names}」（共享设置带过来的），不用改",
              flush=True)
        return []

    field = _wait_for_region_field(page, timeout_seconds=60)
    if field:
        _scroll_into_comfortable_view(page, field, label="地域")
        page.wait_for_timeout(600)
    return set_regions(page, region_pairs)
