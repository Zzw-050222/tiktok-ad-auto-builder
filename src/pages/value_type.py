"""选择价值类型 ——「短剧」和「短剧端计划」两个模式共用。

原来长在 src/drama/pages/adgroup_page.py 里。两个模式都要求这一项是
「广告收入价值」，而这一块的行为（选完上一项才渲染出来、渲染中高度还在变）
一模一样，所以提到这里共用，不复制第二份。

drama 那边保留同名私有别名，调用点一个字都不用改。
"""

from src.pages.common import robust_click, wait_until
from src.pages.viewport import (
    MEASURE_JS,
    on_screen,
    scroll_into_comfortable_view,
    viewport_h,
)


def first_visible(loc, limit=12):
    """一批匹配里挑真正可见的那一个。这个后台到处是同文本的隐藏副本。"""
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


def option_row_of(page, text_locator):
    """给定下拉选项里的某个文字元素，往上找到整行（可点击的那一层）。

    和剧集那边 _episode_row_radio 同一个套路：这个后台的下拉项，文字节点本身往往
    不是可点击的目标，点它不会落到选项上。
    """
    # 从【自己】开始往上找，找到第一个「像一行」的元素就停 —— 也就是取最内层的那个。
    #
    # 老写法上来就 n = n.parentElement，跳过了自己。这在选 Mini 那边碰巧是对的
    # （匹配到的是行里更深的一个文字节点），但价值类型这边匹配到的元素【本身就是那一行】，
    # 于是往上多走一层命中了整个下拉容器（宽 300、高 78，也满足那个尺寸条件），
    # 点它的中心就落在了两行之间 / 第一行上 —— 结果每次都选中「应用内购价值」，
    # 然后判定失败、重试三轮报错。测试就是这么抓出来的。
    #
    # 为什么「最内层」是安全的方向：点行【里面】的子元素，事件会冒泡到行上，照样生效；
    # 点行【外面】的容器，就可能落到别的行去。所以宁可往里、不要往外。
    #
    # 但也不能无脑用自己：这个后台的占位/文字层常常是 pointer-events: none，
    # 点它等于没点（商品库选商品库那次的坑）。所以要跳过收不到点击的层。
    js = """
    el => {
      document.querySelectorAll('[data-drama-opt]').forEach(e => e.removeAttribute('data-drama-opt'));
      let n = el;
      for (let k = 0; k < 9 && n; k++) {
        const r = n.getBoundingClientRect();
        const st = getComputedStyle(n);
        if (r.width > 200 && r.height >= 30 && r.height < 140
            && st.pointerEvents !== 'none') {
          n.setAttribute('data-drama-opt', '1');
          return true;
        }
        n = n.parentElement;
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


# 「选择价值类型」的两个选项。默认是「应用内购价值」，短剧要改成「广告收入价值」。
VALUE_TYPE_IAP = "应用内购价值"
VALUE_TYPE_AD_REVENUE = "广告收入价值"


def value_type_box(page):
    """「选择价值类型」当前那个框（收起时显示「应用内购价值」）。"""
    return first_visible(page.get_by_text(VALUE_TYPE_IAP, exact=True))


def wait_value_type_settled(page, timeout_seconds=40):
    """等「选择价值类型」这块【出现，并且不再动】，然后才把那个框交出去。

    为什么要等「不再动」——这是使用者反馈「选完 mini 之后又定位了很久、一直上下
    滚动」的真正原因，他自己的猜测也是对的：
      优化目标 / 选择价值类型 / 竞价策略 / 目标 ROAS 这一整块，是【选完 TikTok
      Mini 之后才渲染出来】的（选之前优化目标那里只有一个「-」），实测要两三秒，
      而且渲染过程中区块高度一直在变。
    老写法一看到「应用内购价值」这几个字就去滚、去点，点在还在重排的元素上，
    下拉没展开 → Escape → 重试 → 再滚一遍。三轮下来就是十几秒的上下滚动。

    判据是【位置连续两次没变】（约 1 秒）。不用固定 sleep：加载快的时候不该白等，
    慢的时候固定值又不够。
    """
    vh = viewport_h(page)
    stable = 0
    last_y = None
    rounds = max(1, int(timeout_seconds * 1000 / 500))
    for _ in range(rounds):
        box = value_type_box(page)
        if box is None:
            stable, last_y = 0, None          # 还没渲染出来，安静等着，别滚
        else:
            try:
                m = box.evaluate(MEASURE_JS, vh)
            except Exception:
                m = None
            y = None if not m else round(m["y"])
            if y is not None and last_y is not None and abs(y - last_y) <= 2:
                stable += 1
                if stable >= 2:
                    return box
            else:
                stable = 0
            last_y = y
        page.wait_for_timeout(500)
    return value_type_box(page)


def _dropdown_still_open(page):
    """两个选项【同时】可见 —— 只有下拉展开时才会这样。"""
    return (first_visible(page.get_by_text(VALUE_TYPE_IAP, exact=True)) is not None
            and first_visible(page.get_by_text(VALUE_TYPE_AD_REVENUE, exact=True))
            is not None)


def select_ad_revenue_value_type(page, timeout_seconds=90):
    """把「选择价值类型」从默认的「应用内购价值」改成「广告收入价值」。

    位置：选完 TikTok Mini 之后、填目标 ROAS 之前。操作就是点那个框展开下拉、
    点「广告收入价值」。这一块要等它渲染完再动手，见 wait_value_type_settled。

    沿用选 Mini 那一节踩出来的三条：
      * 找元素用 Playwright 定位器（能穿透 shadow DOM），不用 document.querySelectorAll
      * 无条件把目标滚进视野——first_visible 只看盒子非零，【屏幕外的元素也算可见】，
        写成「找不到才滚」的话一次都不会滚
      * 验证要看【结果】不是【动作】：判据是「应用内购价值」这几个字从页面上消失
        且「广告收入价值」出现。不能只看后者出现——下拉展开时两个选项【同时】
        在页面上，那时候「广告收入价值」也是可见的。

    已经是「广告收入价值」就直接返回，不去点它——这是个下拉不是开关，多点一次
    虽然不会切回去，但没必要冒险。
    """
    def picked():
        gone = first_visible(page.get_by_text(VALUE_TYPE_IAP, exact=True)) is None
        shown = first_visible(page.get_by_text(VALUE_TYPE_AD_REVENUE, exact=True)) is not None
        return gone and shown

    if picked():
        return

    for attempt in range(3):
        # 等这一块渲染出来并站稳。这期间【不滚动】——它还在重排，滚了也白滚。
        box = wait_value_type_settled(page, timeout_seconds=40)
        if box is None:
            if picked():
                return
            print(f"          [价值类型] 第{attempt + 1}轮：这一块还没渲染出来",
                  flush=True)
            page.wait_for_timeout(1500)
            continue

        # 已经在屏幕上就别动页面。滚动只是为了让它可点，不是为了摆得好看。
        if not on_screen(page, box):
            scroll_into_comfortable_view(page, box, label="价值类型")
            page.wait_for_timeout(300)

        robust_click(page, box, timeout=8000)
        page.wait_for_timeout(1500)

        opt = wait_until(
            page,
            lambda: first_visible(page.get_by_text(VALUE_TYPE_AD_REVENUE, exact=True)),
            timeout_seconds=15,
        )
        if opt is None:
            print("          [价值类型] 下拉里没找到「广告收入价值」，重试", flush=True)
            page.keyboard.press("Escape")
            page.wait_for_timeout(1000)
            continue

        row = option_row_of(page, opt) or opt
        robust_click(page, row, timeout=8000)
        page.wait_for_timeout(2000)

        # 选完先把下拉关掉再验证。
        #
        # picked() 的判据是「『应用内购价值』这几个字从页面上消失」，而下拉展开时
        # 两个选项【同时】在页面上 —— 所以下拉只要还开着，picked() 就永远是 False，
        # 明明选对了也会判成失败，三轮之后报错、把整条计划弄挂。
        # 而下拉确实可能还开着：选项的点击会冒泡回触发框，有些实现因此又打开一次
        # （身份和剧集那两个下拉也踩到同一件事，处理方式一致）。
        if _dropdown_still_open(page):
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            page.wait_for_timeout(600)

        if wait_until(page, picked, timeout_seconds=20):
            print("          [价值类型] 已选中「广告收入价值」", flush=True)
            return
        page.wait_for_timeout(1200)

    raise ValueError(
        "选「广告收入价值」失败：点了 3 轮，「应用内购价值」这几个字仍在页面上。\n"
        "这一步的位置：商品库是选完 TikTok Mini 之后、短剧端计划是选完剧集之后，"
        "都在填目标 ROAS 之前。\n"
        "如果页面上这一项显示成【纯文本而不是下拉】，说明它是账号层「共享设置」带下来的、"
        "在这里改不了 —— 需要先去后台把这个账号的价值类型改成「广告收入价值」。"
    )
