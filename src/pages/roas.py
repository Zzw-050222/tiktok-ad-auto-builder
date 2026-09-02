"""目标 ROAS ——「短剧」和「短剧端计划」两个模式共用。

原来叫 select_target_roas_drama，长在 src/drama/pages/adgroup_page.py 里。
「短剧端计划」的出价区块结构和它一模一样（竞价策略=目标 ROAS 且标着共享设置、
下面是「第 0 天 ROAS」+「请输入一个值」），所以提到这里共用，不复制第二份。

仍然刻意【不】复用小游戏那套 set_target_roas —— 两页结构不同，见下面函数的说明。

drama 那边保留同名别名（select_target_roas_drama 等），调用点一个字都不用改。
"""

import re

from src.pages.viewport import on_screen, scroll_into_comfortable_view


def first_visible(loc, limit=200):
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


# 短剧的 ROAS 输入框。实测 placeholder 是「请您输入广告花费回报（ROAS）下限值」，
# 但小游戏那边同一个框还出现过「请输入一个值」（TikTok 在做文案灰度），所以用正则
# 兼容两种，只要带 ROAS 字样或是那句老文案都认。
ROAS_PLACEHOLDER_RE = re.compile(r"ROAS|请输入一个值")


ROAS_VALUE_RE = re.compile(r"ROAS[:：]\s*([0-9]+(?:\.[0-9]+)?)")


def same_number(a, b):
    """数值相等就算相等：页面显示 '1.000'，表格里是 1，两者应当视为一致。"""
    try:
        return abs(float(a) - float(b)) < 1e-9
    except (TypeError, ValueError):
        return str(a).strip() == str(b).strip()


def current_roas(page):
    """读「优化和出价」区块里当前显示的目标 ROAS。读不到返回 None。

    页面上是「第 0 天 ROAS: 1.000」这样的文本（不是输入框），所以按文字抠。
    """
    txt = bidding_section_text(page, limit=600)
    if not isinstance(txt, str):
        return None
    m = ROAS_VALUE_RE.search(txt)
    return m.group(1) if m else None


def visible_placeholders(page, limit=25):
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


def bidding_section_text(page, limit=300):
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


def set_target_roas_shared(page, roas_value, timeout_seconds=150):
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
        loc = page.get_by_placeholder(ROAS_PLACEHOLDER_RE)
        return first_visible(loc)

    # 先看是不是【已经就是要的值】。竞价策略这几项标着「共享设置」，值会从同账号
    # 上一个计划带过来：实测新建计划时「第 0 天 ROAS: 1.000」已经填好了，那个位置
    # 根本不是输入框而是文本，程序会一直等一个永远不出现的空框，白等 150 秒。
    # 和选 Mini、选价值类型一样：已经对了就别动它。
    already = current_roas(page)
    if already is not None and same_number(already, roas_value):
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
            f"页面上可见的输入框占位文字: {visible_placeholders(page)}\n"
            f"「优化和出价」区块当前内容: {bidding_section_text(page)!r}"
        )

    # 使用者演示：点「请输入广告花费…」这段文字就能输入。先滚过去再点再填——
    # 这一块在页面很下面，不主动滚可能点不到实处。
    if not on_screen(page, box):
        scroll_into_comfortable_view(page, box, label="ROAS")
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
