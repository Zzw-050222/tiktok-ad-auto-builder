"""短剧端计划 —— 广告组层。

和另外两个模式的分界线就在这里：
  * 小游戏  ：优化位置 = 小游戏
  * 商品库  ：计划层打开「设置商品库推广系列」，优化位置 = 短剧
  * 短剧端  ：计划层【不】打开那个开关（计划页完全复刻小游戏），
              到广告组层把优化位置【改成「剧集」】

使用者口述的操作：填完广告组名称之后，点「优化位置」下面那个值右边的铅笔图标
（那是修改按钮），会展开三个选项（小游戏 / 短剧 / 剧集），显示不全就往下滑一点，
然后点「剧集」左边的小圆圈。
"""

from src.pages.common import is_selected, robust_click, wait_until
from src.pages.viewport import (
    MEASURE_JS,
    on_screen,
    scroll_into_comfortable_view,
    viewport_h,
)

# 优化位置的三个选项。名字都很短，而且互相包含（「短剧」的说明里就有「完整剧集内容」，
# 「剧集」的说明里有「剧集中的单集内容」），所以：
#   * 匹配选项名一律 exact=True
#   * 判断「三个选项是不是展开了」用【说明文字】，那几句是页面上独一无二的
OPT_MINIGAME = "小游戏"
OPT_DRAMA = "短剧"
OPT_EPISODE = "剧集"

# 每个选项的说明文字。用它来确认下拉真的展开了，比数「页面上有几个『剧集』」可靠得多。
_OPT_DESCS = {
    OPT_MINIGAME: "让受众发现并游玩小游戏。",
    OPT_DRAMA: "让受众发现并通过观看或购买来解锁完整剧集内容。",
    OPT_EPISODE: "让受众发现并观看剧集中的单集内容。",
}

# 「优化位置」这个字段。标题里还跟着一个「共享设置」标签，所以是 startsWith 而不是相等。
_FIELD_TITLE = "优化位置"

# 铅笔（修改）图标的候选选择器，按可信度排序。
#
# 这个后台的图标是 <ks-icon name="xxx" class="KsIconXxx">，标签名就是 ks-icon
# ——不是 ks-icon-xxx。这条是 duplicate.py 里踩出来的（复制图标那次），照搬过来。
# 真机上到底是哪一个命中会打进日志，第一次跑完就知道该留哪条。
_PENCIL_SELECTORS = (
    '[name="edit"]',
    '[name="pencil"]',
    '[name*="edit"]',
    '[name*="pencil"]',
    ".KsIconEdit",
    ".KsIconPencil",
    'svg[class*="edit" i]',
)

# 明确要排除的图标：每个选项名后面都跟着一个 ⓘ 帮助图标，点它只会弹说明气泡。
_PENCIL_EXCLUDE = ("question", "help", "info", "tips", "explain")


def _first_visible(loc, limit=12):
    """一批匹配里挑真正可见的那一个。这个后台到处是同文本的隐藏副本，盲取 .first 会踩坑。"""
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


# 找到「优化位置」那个字段区块，打个标记好让 Playwright 抓。
#
# 按【区块结构】定位而不是按文字：「优化位置」这四个字在页面上不止一处
# （字段标题、右侧建议采纳情况里的「优化和出价」条目附近）。
_MARK_FIELD_JS = """
() => {
  document.querySelectorAll('[data-ep-optloc]').forEach(
    e => e.removeAttribute('data-ep-optloc'));
  const secs = document.querySelectorAll(
    '[data-testid="lego-section-item"], [data-testid="lego-hybrid-section-item"]');
  for (const sec of secs) {
    const h = sec.querySelector('[data-testid="lego-section-item-header"]')
           || sec.querySelector('[data-testid="lego-hybrid-section-item-header"]');
    if (!h) continue;
    // 标题是「优化位置」，后面可能跟着「共享设置」标签，所以用 startsWith
    const t = (h.innerText || '').trim();
    if (!t.startsWith('优化位置')) continue;
    const r = sec.getBoundingClientRect();
    if (r.width <= 0 || r.height <= 0) continue;
    sec.setAttribute('data-ep-optloc', '1');
    return true;
  }
  return false;
}
"""


def _field(page):
    """「优化位置」字段区块的 locator，找不到返回 None。"""
    try:
        if not page.evaluate(_MARK_FIELD_JS):
            return None
    except Exception:
        return None
    loc = page.locator('[data-ep-optloc="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def _options_expanded(page):
    """三个选项是不是已经展开了。

    判据用【说明文字】而不是选项名：选项名只有两三个字且互相包含，
    收起状态下值本身就写着「短剧」，靠它判断会一直以为已经展开。
    只要有两句说明同时可见就算展开——三句里万一某句被平台改了文案，
    也不至于整步失败。
    """
    seen = 0
    for desc in _OPT_DESCS.values():
        if _first_visible(page.get_by_text(desc, exact=True)) is not None:
            seen += 1
    return seen >= 2


def _current_value(page):
    """「优化位置」当前的值（收起态显示的那几个字）。读不出返回 None。"""
    fld = _field(page)
    if fld is None:
        return None
    try:
        txt = fld.evaluate("""el => {
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
          return deep(el);
        }""")
    except Exception:
        return None
    if not txt:
        return None
    # 去掉标题和「共享设置」标签
    rest = txt.replace(_FIELD_TITLE, "", 1).replace("共享设置", "").strip()
    if not rest:
        return None

    # 只认三个已知选项名，别把整段文字原样返回。
    # 两个原因，都是测出来的：
    #   * 值后面紧跟着一个 ⓘ 帮助图标，它也可能带文字，于是读出来是「短剧 ?」
    #   * 展开状态下整个字段的文字包含三行选项和说明，读出来是一大段
    # 所以按「开头是哪个选项名」来判定；一个都不匹配就返回原文（截断），
    # 好让报错信息里能看到实际是什么。
    for name in (OPT_MINIGAME, OPT_DRAMA, OPT_EPISODE):
        if rest.startswith(name):
            return name
    return rest[:60]


def displayed_option(page):
    """收起状态下显示的是哪个选项。展开状态或读不出来时返回 None。"""
    if _options_expanded(page):
        return None
    val = _current_value(page)
    return val if val in (OPT_MINIGAME, OPT_DRAMA, OPT_EPISODE) else None


def already_episode(page):
    """已经是「剧集」了吗。

    展开状态下【不作判断】返回 None —— 那时候三个选项名都在页面上，
    靠读文字判断一定会误判。这种情况交给调用方去读那三个圆圈的选中状态。
    """
    if _options_expanded(page):
        return None
    val = _current_value(page)
    if val is None:
        return None
    return val == OPT_EPISODE


def _find_pencil(page, fld):
    """在「优化位置」字段里找那个铅笔（修改）图标。返回 (locator, 命中的选择器)。

    刻意【不要求图标有尺寸】：这个后台的行内操作图标在 hover 之前常常是 0x0，
    bounding_box() 返回 None——复制广告组那次就是因为「没尺寸就当没找到」而卡住的。
    所以只要在 DOM 里就先拿着，点之前再 hover。
    """
    for sel in _PENCIL_SELECTORS:
        try:
            loc = fld.locator(sel)
            n = loc.count()
        except Exception:
            continue
        for i in range(min(n, 6)):
            el = loc.nth(i)
            try:
                name = (el.get_attribute("name") or "").lower()
                cls = (el.get_attribute("class") or "").lower()
            except Exception:
                name, cls = "", ""
            blob = name + " " + cls
            if any(bad in blob for bad in _PENCIL_EXCLUDE):
                continue          # ⓘ 帮助图标，点它只会弹气泡
            return el, sel
    return None, None


def _section_debug(page, limit=400):
    """展开失败时把「优化位置」这一块【实际有什么】打出来，而不是只报一句「没找到」。

    这个项目的规律：靠猜写定位基本都要返工，看一次真实 DOM 的一次就对。
    """
    fld = _field(page)
    info = {"字段找到": fld is not None}
    if fld is None:
        return info
    try:
        info["字段文字"] = (fld.inner_text(timeout=2000) or "")[:limit]
    except Exception:
        info["字段文字"] = "(读不到)"
    try:
        info["字段里的图标"] = fld.evaluate("""el => {
          const out = [];
          el.querySelectorAll('ks-icon, [name], svg, i, button').forEach(n => {
            const r = n.getBoundingClientRect();
            out.push({
              tag: n.tagName.toLowerCase(),
              name: n.getAttribute('name') || '',
              cls: (n.getAttribute('class') || '').slice(0, 50),
              w: Math.round(r.width), h: Math.round(r.height),
            });
          });
          return out.slice(0, 15);
        }""")
    except Exception:
        info["字段里的图标"] = "(读不到)"
    return info


def _open_options(page, tries=3):
    """点铅笔展开三个选项。已经展开就直接返回 True。"""
    for attempt in range(tries):
        if _options_expanded(page):
            return True

        fld = _field(page)
        if fld is None:
            print(f"          [优化位置] 第{attempt + 1}轮：没找到「{_FIELD_TITLE}」字段",
                  flush=True)
            page.wait_for_timeout(1500)
            continue

        # 先滚到字段上再 hover —— 图标 hover 之前可能是 0x0
        if not on_screen(page, fld):
            scroll_into_comfortable_view(page, fld, label="优化位置")
        try:
            fld.hover(timeout=5000)
            page.wait_for_timeout(400)
        except Exception:
            pass

        pencil, sel = _find_pencil(page, fld)
        if pencil is None:
            print(f"          [优化位置] 第{attempt + 1}轮：字段里没找到铅笔图标",
                  flush=True)
            page.wait_for_timeout(1200)
            continue

        print(f"          [优化位置] 铅笔命中选择器 {sel}", flush=True)
        robust_click(page, pencil, timeout=6000)

        # 展开是【结果】，靠轮询确认，不要固定 sleep 一段就往下走
        if wait_until(page, lambda: _options_expanded(page), timeout_seconds=10):
            return True
        print(f"          [优化位置] 第{attempt + 1}轮：点了铅笔但选项没展开", flush=True)
        page.wait_for_timeout(1000)

    return _options_expanded(page)


def _option_radio(page, name):
    """给定选项名，找到它那一行左边的小圆圈。

    和商品库那边选剧集同一个套路：文字节点本身往往不是可点的目标，
    要从文字往上走到「行」，再在行里找圆圈。
    这里【从说明文字往上找】而不是从选项名往上找——选项名太短且互相包含，
    说明文字是唯一的。
    """
    desc = _OPT_DESCS.get(name)
    anchor = None
    if desc:
        anchor = _first_visible(page.get_by_text(desc, exact=True))
    if anchor is None:
        anchor = _first_visible(page.get_by_text(name, exact=True))
    if anchor is None:
        return None, None

    js = """
    el => {
      document.querySelectorAll('[data-ep-opt]').forEach(
        e => e.removeAttribute('data-ep-opt'));
      document.querySelectorAll('[data-ep-radio]').forEach(
        e => e.removeAttribute('data-ep-radio'));
      let row = el;
      for (let k = 0; k < 8 && row; k++) {
        row = row.parentElement;
        if (!row) break;
        const r = row.getBoundingClientRect();
        if (r.width < 150) continue;
        // 这一行里得有个单选圈才算找对了行
        const radio = row.querySelector(
          '[role="radio"], input[type="radio"], [class*="radio" i], [class*="Radio"]');
        if (radio) {
          row.setAttribute('data-ep-opt', '1');
          radio.setAttribute('data-ep-radio', '1');
          return true;
        }
      }
      return false;
    }
    """
    try:
        ok = anchor.evaluate(js)
    except Exception:
        ok = False
    if not ok:
        return None, anchor
    radio = page.locator('[data-ep-radio="1"]')
    try:
        return (radio.first if radio.count() > 0 else None), anchor
    except Exception:
        return None, anchor


def select_optimization_location_episode(page, timeout_seconds=90):
    """把「优化位置」改成「剧集」。这是短剧端计划和另外两个模式的分界步骤。

    顺序（使用者口述）：
        点值右边的铅笔 -> 展开三个选项（不全就往下滑一点）-> 点「剧集」左边的小圆圈

    三条从别处踩出来、这里直接照搬的规矩：
      * 找元素用 Playwright 定位器（能穿透 shadow DOM），不用 document.querySelectorAll
      * 图标在 hover 之前可能是 0x0，别拿「有没有尺寸」当「有没有找到」
      * 验证看【结果】不看【动作】：判据是「剧集」那个圈读出来是选中，
        而不是「我点过了」
    """
    if already_episode(page) is True:
        print("          [优化位置] 已经是「剧集」，不用改", flush=True)
        return

    if not _open_options(page):
        raise ValueError(
            "展开「优化位置」的三个选项失败：点了铅笔图标，"
            f"但页面上没出现那几句选项说明。\n现场：{_section_debug(page)}"
        )

    for attempt in range(3):
        radio, anchor = _option_radio(page, OPT_EPISODE)
        if radio is None:
            # 选项展开了但找不到「剧集」那一行 —— 可能是被视口裁掉了（使用者说的
            # 「显示不完整就滚轮往下滑一点点」），先把说明文字滚进来再找一次。
            if anchor is not None and not on_screen(page, anchor):
                scroll_into_comfortable_view(page, anchor, label="剧集选项")
                page.wait_for_timeout(400)
                radio, anchor = _option_radio(page, OPT_EPISODE)
        if radio is None:
            print(f"          [优化位置] 第{attempt + 1}轮：没找到「{OPT_EPISODE}」那一行的圆圈",
                  flush=True)
            page.wait_for_timeout(1200)
            continue

        state = is_selected(radio)
        if state is True:
            print(f"          [优化位置] 已选中「{OPT_EPISODE}」", flush=True)
            return
        # state 为 None 表示【读不出】。这时候也点一下：本函数一开始已经确认过
        # 当前值不是「剧集」，所以点它只会是「选上」，不会把已选的取消掉。
        if not on_screen(page, radio):
            scroll_into_comfortable_view(page, radio, label="剧集圆圈")
        robust_click(page, radio, timeout=6000)
        page.wait_for_timeout(1200)

        def picked():
            r, _ = _option_radio(page, OPT_EPISODE)
            if r is not None and is_selected(r) is True:
                return True
            # 选完平台可能把三个选项收起来，只剩值 —— 那就看值
            return already_episode(page) is True

        if wait_until(page, picked, timeout_seconds=15):
            print(f"          [优化位置] 已选中「{OPT_EPISODE}」", flush=True)
            return
        print(f"          [优化位置] 第{attempt + 1}轮：点完还是没选上", flush=True)

    raise ValueError(
        f"把「优化位置」改成「{OPT_EPISODE}」失败：三个选项已经展开，"
        f"但点了 3 轮「{OPT_EPISODE}」的圆圈都没选上。\n"
        f"当前值: {_current_value(page)!r}\n现场：{_section_debug(page)}"
    )


# ---------------------------------------------------------------------------
# 选完「剧集」之后：身份 -> 剧集 -> 目标 ROAS -> 地域 -> 继续
#
# 使用者口述：「选完剧集之后可能要刷新个三四秒往下滑到可以看到身份框和剧集框」。
# 所以这一整块是【选完优化位置才渲染出来】的，和商品库那边「选完 Mini 才出现
# 价值类型」是同一个现象 —— 那次的教训是：一看到字就去点，会点在还在重排的元素上，
# 下拉不展开，然后重试、再滚一遍，使用者看到的就是一直上下滚动。
# 这里从一开始就写成「等它出现【并且位置不再动】再动手」。
# ---------------------------------------------------------------------------

IDENTITY_FIELD_TITLE = "身份"
SERIES_FIELD_TITLE = "剧集"
SERIES_PLACEHOLDER = "选择剧集"


def _mark_field_js(title):
    """按区块结构找标题恰好是 title 的字段（后面可能跟「共享设置」标签）。"""
    return """
    () => {
      document.querySelectorAll('[data-ep-fld]').forEach(
        e => e.removeAttribute('data-ep-fld'));
      const secs = document.querySelectorAll(
        '[data-testid="lego-section-item"], [data-testid="lego-hybrid-section-item"]');
      for (const sec of secs) {
        const h = sec.querySelector('[data-testid="lego-section-item-header"]')
               || sec.querySelector('[data-testid="lego-hybrid-section-item-header"]');
        if (!h) continue;
        const t = (h.innerText || '').replace('共享设置', '').trim();
        if (t !== %s) continue;
        const r = sec.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        sec.setAttribute('data-ep-fld', '1');
        return true;
      }
      return false;
    }
    """ % repr(title)


def _named_field(page, title):
    """标题为 title 的字段区块，找不到返回 None。"""
    try:
        if not page.evaluate(_mark_field_js(title)):
            return None
    except Exception:
        return None
    loc = page.locator('[data-ep-fld="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def wait_fields_settled(page, timeout_seconds=60):
    """等「身份」和「剧集」两个字段都渲染出来【并且位置不再动】。

    使用者说「选完剧集之后可能要刷新个三四秒」。不用固定 sleep：快的时候不该白等，
    慢的时候固定值又不够。判据是两个字段都在、且位置连续两次没变（约 1 秒）。
    """
    stable = 0
    last = None
    rounds = max(1, int(timeout_seconds * 1000 / 500))
    for _ in range(rounds):
        ident = _named_field(page, IDENTITY_FIELD_TITLE)
        # 注意顺序：_named_field 会清掉上一次的标记，所以要分别取、分别量
        y1 = None
        if ident is not None:
            try:
                m = ident.evaluate(MEASURE_JS, viewport_h(page))
                y1 = None if not m else round(m["y"])
            except Exception:
                y1 = None
        series = _named_field(page, SERIES_FIELD_TITLE)
        y2 = None
        if series is not None:
            try:
                m = series.evaluate(MEASURE_JS, viewport_h(page))
                y2 = None if not m else round(m["y"])
            except Exception:
                y2 = None

        if y1 is not None and y2 is not None:
            cur = (y1, y2)
            if last is not None and abs(cur[0] - last[0]) <= 2 and abs(cur[1] - last[1]) <= 2:
                stable += 1
                if stable >= 2:
                    return True
            else:
                stable = 0
            last = cur
        else:
            stable, last = 0, None
        page.wait_for_timeout(500)
    return _named_field(page, SERIES_FIELD_TITLE) is not None


def _field_box(page, title):
    """字段里那个可点的框（收起态的下拉/选择器）。

    返回【框本身】而不是里面的文字：这个后台的占位文字往往
    pointer-events: none，点它等于没点，下拉一动不动 —— 商品库那边为这件事
    绕了很久（见 drama 的 select_product_catalog 注释）。所以这里取框，
    点的时候还会退到「点坐标」。
    """
    fld = _named_field(page, title)
    if fld is None:
        return None, None
    for sel in ('ks-input-selector', '[data-testid^="KsSelect"]', 'div.vi-select',
                '[class*="select" i]'):
        box = _first_visible(fld.locator(sel))
        if box is not None:
            return box, fld

    # 退路：字段里【最后一个】有实际尺寸的直接子元素。
    # 不能退到整个字段就点它中心 —— 字段 = 标题 + 值框，中心可能落在两者之间的
    # 空白上，点了没反应；而值框总是在标题下面，所以取最后一个子元素。
    try:
        ok = fld.evaluate("""el => {
          document.querySelectorAll('[data-ep-box]').forEach(
            e => e.removeAttribute('data-ep-box'));
          const kids = Array.from(el.children).filter(k => {
            const r = k.getBoundingClientRect();
            return r.width > 40 && r.height > 10;
          });
          if (!kids.length) return false;
          kids[kids.length - 1].setAttribute('data-ep-box', '1');
          return true;
        }""")
    except Exception:
        ok = False
    if ok:
        loc = page.locator('[data-ep-box="1"]')
        try:
            if loc.count() > 0:
                return loc.first, fld
        except Exception:
            pass
    return fld, fld


def _click_box(page, box):
    """点开一个下拉框。

    优先【点真实坐标】：占位文字那一层常常 pointer-events: none，
    直接 click 元素会被吞掉。拿不到坐标才退回 robust_click。
    """
    try:
        box.scroll_into_view_if_needed(timeout=5000)
    except Exception:
        pass
    page.wait_for_timeout(300)
    try:
        r = box.bounding_box()
    except Exception:
        r = None
    if r and r.get("width") and r.get("height"):
        page.mouse.click(r["x"] + r["width"] / 2, r["y"] + r["height"] / 2)
        return "点坐标"
    robust_click(page, box, timeout=6000)
    return "robust_click"


def _visible_search_input(page):
    """下拉里那个搜索框。身份的占位是「按账号名搜索」，剧集的是「搜索」。"""
    for ph in ("按账号名搜索", "搜索"):
        box = _first_visible(page.get_by_placeholder(ph))
        if box is not None:
            return box
    return None


def _type_search(page, text):
    """在下拉的搜索框里输入关键词。没有搜索框就返回 False（那就只能靠翻列表）。"""
    box = _visible_search_input(page)
    if box is None:
        return False
    try:
        box.fill("")
        box.fill(str(text))
    except Exception:
        return False
    page.wait_for_timeout(1200)     # 搜索是异步的，给它一点时间出结果
    return True


def _click_row_containing(page, text, exclude_texts=()):
    """在展开的下拉里点包含 text 的那一行。

    从文字往上走到「行」再点：这个后台的下拉项，文字节点本身经常不是可点的目标
    （商品库选剧集、选 Mini 都是这个套路）。
    exclude_texts 用来排掉下拉外面的同名文字 —— 比如身份下拉展开时，
    收起态那个框里【也】写着当前身份名，点它只会把下拉关掉。
    """
    cands = page.get_by_text(str(text), exact=False)
    try:
        n = cands.count()
    except Exception:
        return False
    for i in range(min(n, 20)):
        el = cands.nth(i)
        try:
            if not el.is_visible():
                continue
            txt = (el.inner_text(timeout=1500) or "").strip()
        except Exception:
            continue
        if any(bad and bad in txt for bad in exclude_texts):
            continue
        marked = el.evaluate("""el => {
          document.querySelectorAll('[data-ep-row]').forEach(
            e => e.removeAttribute('data-ep-row'));
          let n = el;
          for (let k = 0; k < 8 && n; k++) {
            n = n.parentElement;
            if (!n) break;
            const r = n.getBoundingClientRect();
            // 选项整行：够宽、但不是整个下拉容器
            if (r.width > 200 && r.height >= 28 && r.height < 160) {
              n.setAttribute('data-ep-row', '1');
              return true;
            }
          }
          return false;
        }""")
        row = page.locator('[data-ep-row="1"]').first if marked else el
        if not on_screen(page, row):
            scroll_into_comfortable_view(page, row)
        robust_click(page, row, timeout=6000)
        return True
    return False


# 读字段当前显示的值时，必须【跳过展开着的下拉】。
#
# 这是测出来的一个真 bug，而且是最坏的那种：下拉是字段的子元素，
# inner_text 会把下拉里所有选项一起读进来，于是「要选的名字在不在当前值里」
# 永远成立 —— 明明还没选上，程序却宣布「已选中」。
# 「验证要看结果不看动作」这条又差点被自己绕过去。
#
# 判据是 position: absolute/fixed：这类浮层一定是定位出来的，而字段里正常的
# 标题/值都是静态流。顺便也盖住了下拉渲染在 body 上（portal）的情况——
# 那时候字段里本来就没有下拉内容，这个过滤不会误伤。
_FIELD_VALUE_JS = """
el => {
  let out = '';
  const walk = (n) => {
    if (!n) return;
    if (n.nodeType === 3) { out += n.textContent + ' '; return; }
    if (n.nodeType !== 1) return;
    const st = getComputedStyle(n);
    if (st.position === 'absolute' || st.position === 'fixed') return;  // 展开的下拉
    if (st.display === 'none' || st.visibility === 'hidden') return;
    if (n.tagName === 'SLOT') { for (const a of n.assignedNodes()) walk(a); return; }
    if (n.shadowRoot) { walk(n.shadowRoot); return; }
    for (const c of n.childNodes || []) walk(c);
  };
  walk(el);
  return out.replace(/\\s+/g, ' ').trim();
}
"""


def _field_value(page, title, strip_words=()):
    """字段当前显示的值（去掉标题和「共享设置」）。读不出返回 None。"""
    fld = _named_field(page, title)
    if fld is None:
        return None
    try:
        txt = fld.evaluate(_FIELD_VALUE_JS)
    except Exception:
        return None
    if not txt:
        return None
    txt = " ".join(txt.split())
    for w in (title, "共享设置") + tuple(strip_words):
        txt = txt.replace(w, " ")
    return " ".join(txt.split()) or None


def _close_dropdown_if_open(page):
    """选完之后如果下拉还开着，关掉它。

    为什么需要：选项点下去之后，点击【会冒泡到触发框】，有些实现会因此把下拉
    又打开一次（fixture 里就复现出来了）。下拉开着会盖住下面的字段，
    下一步（选剧集、填 ROAS）就可能点不到。
    只在搜索框还可见时按一次 Esc —— 已经关了的话按 Esc 是无害的，
    但没必要每次都按。按完还要【重新验证值】，确认 Esc 没把刚选的撤掉。
    """
    if _visible_search_input(page) is None:
        return True                      # 本来就没开
    try:
        page.keyboard.press("Escape")
    except Exception:
        pass
    page.wait_for_timeout(500)
    if _visible_search_input(page) is None:
        return True
    # 关不掉就【说出来】，别假装关掉了 —— 下拉盖着的话下一步会点不到。
    print("          [下拉] 按了 Esc 还是没关掉，下一步可能被它盖住", flush=True)
    return False


def select_identity_episode(page, identity_name, timeout_seconds=60):
    """选身份。

    使用者口述：点身份下面那个【写了身份名字】的框，出现列表（带「按账号名搜索」
    搜索框、「由商务中心共享」下面几个账号），点表格里那个身份就选中了。

    已经就是要的那个就不动它 —— 身份标着「共享设置」，会从同账号上一个计划带过来。
    这条规矩在商品库那边（Mini / 价值类型 / ROAS / 地域）反复踩过五次，这里一开始就写上。
    """
    want = str(identity_name or "").strip()
    if not want:
        return "表格没给身份，跳过"

    cur = _field_value(page, IDENTITY_FIELD_TITLE)
    if cur and want.lower() in cur.lower():
        return f"身份已经是「{cur}」，不用改"

    for attempt in range(3):
        box, fld = _field_box(page, IDENTITY_FIELD_TITLE)
        if box is None:
            print(f"          [身份] 第{attempt + 1}轮：没找到「身份」字段", flush=True)
            page.wait_for_timeout(1500)
            continue
        if not on_screen(page, box):
            scroll_into_comfortable_view(page, box, label="身份框")
        how = _click_box(page, box)
        page.wait_for_timeout(900)

        # 搜一下更稳：商务中心共享的账号可能有很多，列表里不一定一眼就有
        searched = _type_search(page, want)
        print(f"          [身份] 第{attempt + 1}轮：{how}，搜索框={'有' if searched else '无'}",
              flush=True)

        # 排掉收起态那个框里的同名文字（点它只会把下拉关掉）
        if _click_row_containing(page, want, exclude_texts=(IDENTITY_FIELD_TITLE,)):
            page.wait_for_timeout(1200)
            _close_dropdown_if_open(page)
            cur = _field_value(page, IDENTITY_FIELD_TITLE)
            if cur and want.lower() in cur.lower():
                print(f"          [身份] 已选中「{cur}」", flush=True)
                return None
        print(f"          [身份] 第{attempt + 1}轮没选上，当前值={_field_value(page, IDENTITY_FIELD_TITLE)!r}",
              flush=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(800)

    raise ValueError(
        f"选身份「{want}」失败：点了 3 轮。当前值={_field_value(page, IDENTITY_FIELD_TITLE)!r}。"
        "如果这个身份不在「由商务中心共享」列表里，需要先在后台把它共享给这个广告账号。"
    )


def select_series_episode(page, series_name, timeout_seconds=90):
    """选剧集。

    使用者口述：点剧集下面那个框（写着「选择剧集」，点那几个字就行），出现小列表，
    上面可以搜索，搜到再点就选中了。

    列表每行是「缩略图 + 剧名 + N 视频 · X.Xm」，所以按剧名匹配、从剧名往上走到行。
    """
    want = str(series_name or "").strip()
    if not want:
        raise ValueError("表格里没给剧集名，没法选剧集")

    def picked():
        val = _field_value(page, SERIES_FIELD_TITLE, strip_words=(SERIES_PLACEHOLDER,))
        return bool(val and want.lower() in val.lower())

    if picked():
        print(f"          [剧集] 已经是「{want}」，不用改", flush=True)
        return

    for attempt in range(3):
        box, fld = _field_box(page, SERIES_FIELD_TITLE)
        if box is None:
            print(f"          [剧集] 第{attempt + 1}轮：没找到「剧集」字段", flush=True)
            page.wait_for_timeout(1500)
            continue
        if not on_screen(page, box):
            scroll_into_comfortable_view(page, box, label="剧集框")
        how = _click_box(page, box)
        page.wait_for_timeout(900)

        searched = _type_search(page, want)
        print(f"          [剧集] 第{attempt + 1}轮：{how}，搜索={'有' if searched else '无'}",
              flush=True)

        if _click_row_containing(page, want,
                                 exclude_texts=(SERIES_PLACEHOLDER, SERIES_FIELD_TITLE)):
            if wait_until(page, picked, timeout_seconds=15):
                _close_dropdown_if_open(page)
                if picked():
                    print(f"          [剧集] 已选中「{want}」", flush=True)
                    return
                print("          [剧集] 关下拉之后值又没了，重试", flush=True)
        print(f"          [剧集] 第{attempt + 1}轮没选上，当前值="
              f"{_field_value(page, SERIES_FIELD_TITLE, strip_words=(SERIES_PLACEHOLDER,))!r}",
              flush=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(800)

    raise ValueError(
        f"选剧集「{want}」失败：点了 3 轮，搜索也搜过了。"
        f"当前值={_field_value(page, SERIES_FIELD_TITLE, strip_words=(SERIES_PLACEHOLDER,))!r}。"
        "确认这个剧名和后台列表里显示的完全一致（列表里每行是「剧名 + N 视频 · 时长」）。"
    )


def fill_adgroup_core(page, rec, identity_name, series_name, region_pairs):
    """短剧端计划的广告组层，一整条走完。

    使用者口述的完整顺序：
        广告组名称
        -> 优化位置改成「剧集」
        -> （等三四秒重新渲染，往下滑到能看到身份框和剧集框）
        -> 身份
        -> 剧集
        -> 目标 ROAS
        -> 地域
        -> 继续

    哪些是复用、哪些是新写的，写在这里省得以后翻：
      * 广告组名称   复用小游戏 src/pages/adgroup_page.fill_ad_group_name
      * 优化位置     本文件新写（三个模式的分界点）
      * 身份 / 剧集  本文件新写（商品库那边没有这两个字段）
      * 目标 ROAS    复用 src/pages/roas.set_target_roas_shared
                     —— 出价区块结构和商品库一模一样（竞价策略=目标 ROAS 且共享设置、
                        下面是「第 0 天 ROAS」+「请输入一个值」）
      * 地域         复用小游戏 src/pages/adgroup_page.set_regions
                     —— 使用者原话「这个地方的操作步骤和小游戏一模一样」

    返回 warnings 列表（非致命的问题），致命的直接抛异常。
    """
    from src.pages.adgroup_page import (
        fill_ad_group_name,
        set_regions,
        _wait_for_region_field,
    )

    warnings = []

    fill_ad_group_name(page, str(rec["Ad Group Name"]))

    # ---- 优化位置 -> 剧集 ----
    select_optimization_location_episode(page)

    # ---- 等身份/剧集这一块渲染完 ----
    # 使用者：「选完剧集之后可能要刷新个三四秒往下滑到可以看到身份框和剧集框」。
    # 不在这里 sleep 三四秒，而是等到「两个字段都在且位置不再动」。
    if not wait_fields_settled(page):
        warnings.append(
            "选完「剧集」之后，等了 60 秒没等到「身份」和「剧集」两个字段稳定下来，"
            "后面几步可能会失败"
        )

    # ---- 身份 ----
    # 身份不是关键项：它标着「共享设置」，平台会带一个过来，选不上也能继续。
    # 所以这里失败只记警告，不把整条计划弄挂 —— 这条规矩是小游戏那边踩出来的
    # （见 src/builder.py fill_ad_identity_copy_url 里那段说明）。
    try:
        note = select_identity_episode(page, identity_name)
        if note:
            warnings.append(f"身份：{note}")
    except Exception as e:
        warnings.append(f"选身份失败（不影响其它步骤）: {str(e).splitlines()[0][:160]}")

    # ---- 剧集 ----（这个是关键项，选不上必须停）
    select_series_episode(page, series_name)

    # ---- 目标 ROAS ----
    from src.pages.roas import set_target_roas_shared

    set_target_roas_shared(page, rec["roas_bid"])

    # ---- 地域 ----
    field = _wait_for_region_field(page, timeout_seconds=60)
    if field:
        if not on_screen(page, field):
            scroll_into_comfortable_view(page, field, label="地域")
        page.wait_for_timeout(400)
    failed = set_regions(page, region_pairs)
    for rid, name in failed or []:
        warnings.append(f"地区 {name}({rid}) 没能在页面上选中")

    return warnings
