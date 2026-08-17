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



def _scroll_into_comfortable_view(page, locator, tries=14, label=""):
    """真的把元素滚进视口中部；滚不动就换 JS 滚它最近的可滚动祖先。

    踩过的两个坑，都会表现为【页面根本不动】：
      1) bounding_box() 对 shadow DOM 里的 <slot> 返回 None。slot 自身不渲染，
         只有被它分配的节点才有盒子。拿不到坐标就 return，滚动一次都没发生——
         使用者在旁边看着浏览器说「每次选完剧集都没看到页面滚动」，就是这个。
         所以这里拿不到盒子时，往上找有真实盒子的祖先。
      2) _first_visible 只看 getBoundingClientRect 非零，【屏幕外的元素照样算可见】，
         于是「找不到才滚」的写法永远不触发滚动。调用方必须无条件调用本函数。

    另外 mouse.wheel 是滚【鼠标底下】那个容器，所以先把鼠标移到表单区域中间；
    真滚不动（内层容器吃掉滚动）时退回直接设最近可滚动祖先的 scrollTop。
    """
    try:
        vh = page.viewport_size["height"]
    except Exception:
        vh = 1000
    top_safe, bottom_safe = 170, vh - 230      # 避开顶部导航和底部固定操作栏
    target_y = (top_safe + bottom_safe) // 2

    def rect():
        """取真实盒子：自己没有（slot）就往上找祖先。"""
        try:
            return locator.evaluate("""el => {
              let n = el;
              for (let k = 0; k < 6 && n; k++) {
                const r = n.getBoundingClientRect();
                if (r.width > 0 && r.height > 0)
                  return {y: r.y, h: r.height, x: r.x, w: r.width};
                n = n.parentElement;
              }
              return null;
            }""")
        except Exception:
            return None

    try:
        page.mouse.move(800, 500)              # wheel 滚的是鼠标底下的容器
    except Exception:
        pass

    last_y = None
    for _ in range(tries):
        r = rect()
        if not r:
            return False
        y = r["y"] + r["h"] / 2
        if top_safe <= y <= bottom_safe:
            return True

        if last_y is not None and abs(y - last_y) < 3:
            # 滚了但没动 —— 内层可滚动容器吃掉了滚轮，改成直接设 scrollTop
            try:
                locator.evaluate("""(el, dy) => {
                  let n = el;
                  while (n) {
                    const st = getComputedStyle(n);
                    if (n.scrollHeight > n.clientHeight + 4 &&
                        /auto|scroll/.test(st.overflowY)) { n.scrollTop += dy; return; }
                    n = n.parentElement;
                  }
                  window.scrollBy(0, dy);
                }""", int(y - target_y))
                page.wait_for_timeout(400)
            except Exception:
                pass
            last_y = None
            continue

        last_y = y
        page.mouse.wheel(0, int(y - target_y))
        page.wait_for_timeout(350)

    r = rect()
    return bool(r and top_safe <= r["y"] <= bottom_safe)


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
        # 不能只说「没有可见的商品库」——那句话看不出是「下拉没展开」、
        # 「展开了但还在转圈」还是「TikTok 改了选项渲染方式、不再带 ID 了」。
        # 把下拉里实际有什么打出来。
        try:
            box = page.locator('[class*="dropdown"]:visible, [class*="popover"]:visible')
            texts = []
            for i in range(min(box.count(), 4)):
                try:
                    t = (box.nth(i).inner_text() or "").replace("\n", " ").strip()
                    if t:
                        texts.append(t[:200])
                except Exception:
                    continue
            raise ValueError(
                "下拉展开后，没有任何可见的商品库（等了 45 秒）。"
                f"当前下拉/弹层里的文字: {texts or '（空——下拉可能压根没展开）'}"
            )
        except ValueError:
            raise
        except Exception:
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


def _option_row_of(page, text_locator):
    """给定下拉选项里的某个文字元素，往上找到整行（可点击的那一层）。

    和剧集那边 _episode_row_radio 同一个套路：这个后台的下拉项，文字节点本身往往
    不是可点击的目标，点它不会落到选项上。
    """
    js = """
    el => {
      document.querySelectorAll('[data-drama-opt]').forEach(e => e.removeAttribute('data-drama-opt'));
      let n = el;
      for (let k = 0; k < 8 && n; k++) {
        n = n.parentElement;
        if (!n) break;
        const r = n.getBoundingClientRect();
        // 选项整行：足够宽、且不是整个下拉容器
        if (r.width > 200 && r.height >= 30 && r.height < 140) {
          n.setAttribute('data-drama-opt', '1');
          return true;
        }
      }
      return false;
    }
    """
    try:
        ok = text_locator.evaluate(js)
    except Exception:
        ok = False
    if not ok:
        return None
    loc = page.locator('[data-drama-opt="1"]')
    return loc.first if loc.count() > 0 else None



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

        # ② 无条件滚进视野。屏幕外的元素在 _first_visible 眼里也算「可见」，
        #    所以绝不能写成「找不到才滚」——那样一次都不会滚。
        ok = _scroll_into_comfortable_view(page, anchor)
        print(f"          [mini] 第{attempt + 1}轮：滚动到位={ok}", flush=True)
        page.wait_for_timeout(400)

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


# 「选择价值类型」的两个选项。默认是「应用内购价值」，短剧要改成「广告收入价值」。
VALUE_TYPE_IAP = "应用内购价值"
VALUE_TYPE_AD_REVENUE = "广告收入价值"


def select_ad_revenue_value_type(page, timeout_seconds=90):
    """把「选择价值类型」从默认的「应用内购价值」改成「广告收入价值」。

    位置：选完 TikTok Mini 之后、填目标 ROAS 之前。操作就是点那个框展开下拉、
    点「广告收入价值」。

    沿用选 Mini 那一节踩出来的三条：
      * 找元素用 Playwright 定位器（能穿透 shadow DOM），不用 document.querySelectorAll
      * 无条件把目标滚进视野——_first_visible 只看盒子非零，【屏幕外的元素也算可见】，
        写成「找不到才滚」的话一次都不会滚
      * 验证要看【结果】不是【动作】：判据是「应用内购价值」这几个字从页面上消失
        且「广告收入价值」出现。不能只看后者出现——下拉展开时两个选项【同时】
        在页面上，那时候「广告收入价值」也是可见的。

    已经是「广告收入价值」就直接返回，不去点它——这是个下拉不是开关，多点一次
    虽然不会切回去，但没必要冒险。
    """
    from src.pages.common import robust_click, wait_until

    def picked():
        gone = _first_visible(page.get_by_text(VALUE_TYPE_IAP, exact=True)) is None
        shown = _first_visible(page.get_by_text(VALUE_TYPE_AD_REVENUE, exact=True)) is not None
        return gone and shown

    if picked():
        return

    for attempt in range(3):
        box = wait_until(
            page,
            lambda: _first_visible(page.get_by_text(VALUE_TYPE_IAP, exact=True)),
            timeout_seconds=25,
        )
        if box is None:
            if picked():
                return
            page.wait_for_timeout(1500)
            continue

        ok = _scroll_into_comfortable_view(page, box)
        print(f"          [价值类型] 第{attempt + 1}轮：滚动到位={ok}", flush=True)
        page.wait_for_timeout(400)

        robust_click(page, box, timeout=8000)
        page.wait_for_timeout(1500)

        opt = wait_until(
            page,
            lambda: _first_visible(page.get_by_text(VALUE_TYPE_AD_REVENUE, exact=True)),
            timeout_seconds=15,
        )
        if opt is None:
            print("          [价值类型] 下拉里没找到「广告收入价值」，重试", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            continue

        row = _option_row_of(page, opt) or opt
        robust_click(page, row, timeout=8000)
        page.wait_for_timeout(2000)

        if wait_until(page, picked, timeout_seconds=20):
            print("          [价值类型] 已选中「广告收入价值」", flush=True)
            return
        page.wait_for_timeout(1200)

    raise ValueError(
        "选「广告收入价值」失败：点了 3 轮，「应用内购价值」这几个字仍在页面上。"
        "这一步在选完 TikTok Mini 之后、填目标 ROAS 之前。"
    )


# 短剧的 ROAS 输入框。实测 placeholder 是「请您输入广告花费回报（ROAS）下限值」，
# 但小游戏那边同一个框还出现过「请输入一个值」（TikTok 在做文案灰度），所以用正则
# 兼容两种，只要带 ROAS 字样或是那句老文案都认。
_DRAMA_ROAS_PLACEHOLDER_RE = re.compile(r"ROAS|请输入一个值")


_ROAS_VALUE_RE = re.compile(r"ROAS[:：]\s*([0-9]+(?:\.[0-9]+)?)")


def _same_number(a, b):
    """数值相等就算相等：页面显示 '1.000'，表格里是 1，两者应当视为一致。"""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def _current_roas(page):
    """读「优化和出价」区块里当前显示的目标 ROAS。读不到返回 None。

    页面上是「第 0 天 ROAS: 1.000」这样的文本（不是输入框），所以按文字抠。
    """
    txt = _bidding_section_text(page, limit=600)
    if not isinstance(txt, str):
        return None
    m = _ROAS_VALUE_RE.search(txt)
    return m.group(1) if m else None


def _visible_placeholders(page, limit=25):
    """页面上所有可见输入框的 placeholder，用于「没找到目标输入框」时看清实际有什么。"""
    out = []
    try:
        loc = page.locator("input:visible, textarea:visible")
        for i in range(min(loc.count(), limit)):
            el = loc.nth(i)
            try:
                ph = el.get_attribute("placeholder")
                val = el.input_value(timeout=1000)
                if ph or val:
                    out.append(f"[{ph or ''}]={val or ''}")
            except Exception:
                continue
    except Exception:
        pass
    return out


def _bidding_section_text(page, limit=300):
    """「优化和出价」区块的可见文字，用于诊断 ROAS 那一块到底渲染成了什么样。"""
    try:
        sec = page.get_by_text("优化和出价", exact=True)
        if sec.count() == 0:
            return "（页面上没有「优化和出价」这个标题）"
        return sec.first.evaluate("""(el, lim) => {
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            n = n.parentElement;
            if (!n) break;
            const t = (n.innerText || '').replace(/\s+/g, ' ').trim();
            if (t.length > 60) return t.slice(0, lim);
          }
          return '(读不到)';
        }""", limit)
    except Exception as e:
        return f"(读取出错: {str(e)[:60]})"


def select_target_roas_drama(page, roas_value, timeout_seconds=150):
    """填短剧广告组的目标 ROAS。

    刻意【不】复用小游戏那套 set_target_roas。两页的出价区块结构不同：
      * 小游戏：竞价策略可选，找不到 ROAS 输入框时要点开下拉去选「目标 ROAS」
      * 短剧  ：竞价策略是「最高价值」且标着【共享设置】，页面上根本没有
                「目标 ROAS」这个选项——小游戏那套会一路走到「点开竞价策略下拉框后
                没有找到'目标ROAS'这个选项」然后报错
    使用者的说法也印证了：默认界面上就有那个框，点一下填进去就行。

    等待时间给到 150 秒（而不是常用的 60 秒）：这个框是【选完 TikTok Mini 之后才
    出现】的，实测从选完到出现可能要一分半。等不够就会误判成「没有这个框」。
    """
    from src.pages.common import wait_until

    def roas_input():
        loc = page.get_by_placeholder(_DRAMA_ROAS_PLACEHOLDER_RE)
        return _first_visible(loc)

    # 先看是不是【已经就是要的值】。竞价策略这几项标着「共享设置」，值会从同账号
    # 上一个计划带过来：实测新建计划时「第 0 天 ROAS: 1.000」已经填好了，那个位置
    # 根本不是输入框而是文本，程序会一直等一个永远不出现的空框，白等 150 秒。
    # 和选 Mini、选价值类型一样：已经对了就别动它。
    already = _current_roas(page)
    if already is not None and _same_number(already, roas_value):
        print(f"          [ROAS] 已经是 {already}（共享设置带过来的），不用改",
              flush=True)
        return

    box = wait_until(page, roas_input, timeout_seconds=timeout_seconds)
    if not box:
        # 没有可编辑的框，但页面上显示的值和表格要的不一样——必须让人知道，
        # 不能默默用着别的值往下跑。
        if already is not None:
            raise ValueError(
                f"页面上的目标 ROAS 是 {already}，但表格要的是 {roas_value}，"
                "而且这里没有可编辑的输入框（竞价策略是「共享设置」，值从上一个计划"
                "带过来的）。请先在后台把这个计划的目标 ROAS 改成表格里的值，"
                "或者把表格改成和页面一致。带着不对的出价往下跑会投错钱。"
            )
        # 等不到就把那块区域【实际有什么】打出来，而不是只报一句「没等到」。
        # 这个项目的规律：靠猜写定位基本都要返工，先看真实 DOM 的一次就对。
        raise ValueError(
            f"等了 {timeout_seconds} 秒没等到 ROAS 输入框。\n"
            f"页面上可见的输入框占位文字: {_visible_placeholders(page)}\n"
            f"「优化和出价」区块当前内容: {_bidding_section_text(page)!r}"
        )

    # 使用者演示：点「请输入广告花费…」这段文字就能输入。先滚过去再点再填——
    # 这一块在页面很下面，不主动滚可能点不到实处。
    _scroll_into_comfortable_view(page, box)
    page.wait_for_timeout(400)
    try:
        from src.pages.common import robust_click as _rc
        _rc(page, box, timeout=8000)
    except Exception:
        pass
    box.fill("")
    box.fill(str(roas_value))
    page.wait_for_timeout(600)

    # 回读确认。这个页面上输入框不止一个，填错地方不会报错。
    try:
        got = (box.input_value(timeout=3000) or "").strip()
        if got != str(roas_value).strip():
            raise ValueError(f"ROAS 填完读回的是 {got!r}，期望 {roas_value!r}")
    except ValueError:
        raise
    except Exception:
        pass


def set_regions_drama(page, region_pairs):
    """选地域。逻辑完全复用小游戏的 set_regions，只在调用前【显式把地域框滚进视野】。

    为什么要多这一步：地域在页面很下面（优化和出价 -> 预算和排期 -> 受众定向）。
    以前能成，是因为上一步「填 ROAS」会顺带把页面滚下去；后来 ROAS 变成共享设置、
    已经是目标值就跳过不填，页面就停在上面，地域框留在视口外，于是点不中——
    实测失败截图里正好停在「受众定向」刚露头的位置。

    这是同一类老毛病：【依赖上一步的副作用把页面滚到位】。上一步一改，这一步就坏。
    所以这里自己滚，不指望别人。

    注意 _wait_for_region_field 返回的「可见」并不代表在视口内：
    getBoundingClientRect 非零就算可见，屏幕外的元素照样算。
    """
    from src.pages.adgroup_page import _wait_for_region_field, set_regions

    field = _wait_for_region_field(page, timeout_seconds=60)
    if not field:
        print("          [地域] 预滚动：没找到地域框，交给 set_regions 自己再等",
              flush=True)
    else:
        box_before = None
        try:
            box_before = field.bounding_box()
        except Exception:
            pass
        ok = _scroll_into_comfortable_view(page, field)
        page.wait_for_timeout(600)
        box_after = None
        try:
            box_after = field.bounding_box()
        except Exception:
            pass
        vh = (page.viewport_size or {}).get("height")
        print(f"          [地域] 预滚动: 到位={ok} 视口高={vh} "
              f"y {round(box_before['y']) if box_before else '?'} -> "
              f"{round(box_after['y']) if box_after else '?'}", flush=True)
    # 点不开下拉时最需要知道的是：这个框是不是【只读】的。
    # 这一页所有出价项都标着「共享设置」，目标 ROAS 已经变成不可编辑的文本，
    # 地域很可能也一样——那就不是「点不中」而是「不该在这里点」。
    if field:
        try:
            info = field.evaluate("""el => {
              const attrs = {};
              for (const a of el.attributes || []) attrs[a.name] = (a.value || '').slice(0, 70);
              const st = getComputedStyle(el);
              return {tag: el.tagName.toLowerCase(), attrs: attrs,
                      pointerEvents: st.pointerEvents, opacity: st.opacity,
                      disabled: !!el.disabled};
            }""")
            print(f"          [地域] 框属性: {info}", flush=True)
        except Exception as e:
            print(f"          [地域] 读框属性出错: {str(e)[:60]}", flush=True)
    try:
        sec = page.get_by_text("受众定向", exact=True)
        if sec.count():
            txt = sec.first.evaluate("""el => {
              let n = el;
              for (let k = 0; k < 6 && n; k++) {
                n = n.parentElement;
                if (!n) break;
                const t = (n.innerText || '').replace(/\s+/g, ' ').trim();
                if (t.length > 80) return t.slice(0, 400);
              }
              return '(读不到)';
            }""")
            print(f"          [地域] 受众定向区块: {txt!r}", flush=True)
    except Exception:
        pass
    return set_regions(page, region_pairs)
