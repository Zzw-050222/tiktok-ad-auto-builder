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
    """已经是「剧集」了吗。读不出来返回 None。

    展开状态下【绝不能读文字】：三个选项名那时都在页面上，
    _current_value 会把第一个选项名（小游戏）当成当前值返回——
    第一次真机跑的报错信息里「当前值: '小游戏'」就是这么来的，完全是假的。
    展开时唯一可信的是单选圈自己的状态（在 shadow DOM 里）。
    """
    if _options_expanded(page):
        return None if selected_option(page) is None else (
            selected_option(page) == OPT_EPISODE)
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


# 三个选项的真实结构（2026-08-26 真机探针实测，不是猜的）：
#
#   <div class="lego-hybrid-section-item__interactive__...">
#     <ks-radio-group-1-1-23 class="KsRadioGroup">
#       <ks-radio-1-1-23 role="radio" class="KsRadio" style="cursor:pointer">   ← 一行=一个选项
#         #shadow-root
#           <div class="radio radio--size-md radio--checked ...">              ← 选中标记在这里
#             <div class="radio__control"><input class="radio__display" type="radio">
#         <span slot="description">让受众发现并观看剧集中的单集内容。</span>
#
# 三条实测出来的要害：
#
#  1) 选中状态【只存在 shadow DOM 里】——宿主 ks-radio 上的属性点前点后一模一样，
#     没有 aria-checked、没有 is-checked、什么都没有。所以共用的 is_selected
#     （读宿主属性那套）在这里【永远读不出来】，必须进 shadowRoot 看 radio--checked。
#
#  2) 点【中心】点不上。行是 308x38，中心落在说明文字上；圆圈在最左边，
#     点 x≈10 才生效。实测点中心之后「优化位置」纹丝不动。
#
#  3) 别用「往上找一个祖先再 querySelector('[role=radio]')」——ks-radio 自己
#     就带 role="radio"，而 querySelector 不会匹配元素自身，于是一路走到
#     ks-radio-group，再 querySelector 拿到的是【组里第一个】也就是「小游戏」。
#     第一次真机跑就是这么把小游戏选上的。这和价值类型那次是同一类错误：
#     宁可往里，不要往外。
#
# 另外必须【限定在优化位置这个字段里】找：页面上「排期」那块也有两个 role=radio
# （持续投放广告组 / 设置开始时间和结束时间），全局找会串。
_RADIO_SCAN_JS = """
() => {
  document.querySelectorAll('[data-ep-r]').forEach(e => e.removeAttribute('data-ep-r'));
  const secs = document.querySelectorAll(
    '[data-testid="lego-section-item"],[data-testid="lego-hybrid-section-item"]');
  for (const sec of secs) {
    const h = sec.querySelector('[data-testid="lego-section-item-header"]')
           || sec.querySelector('[data-testid="lego-hybrid-section-item-header"]');
    if (!h || !(h.innerText || '').trim().startsWith('优化位置')) continue;
    const out = [];
    [...sec.querySelectorAll('[role="radio"]')].forEach((n, i) => {
      const r = n.getBoundingClientRect();
      if (r.width <= 0 || r.height <= 0) return;
      n.setAttribute('data-ep-r', String(i));
      const base = n.shadowRoot && n.shadowRoot.querySelector('.radio');
      out.push({
        i: String(i),
        text: (n.innerText || '').replace(/\\s+/g, ' ').trim(),
        checked: !!(base && (base.className || '').includes('radio--checked')),
      });
    });
    return out;
  }
  return null;
}
"""


def _radios(page):
    """优化位置里的三个单选圈：[{i, text, checked}]。没展开就返回空列表。"""
    try:
        return page.evaluate(_RADIO_SCAN_JS) or []
    except Exception:
        return []


def _name_of(text):
    for name in (OPT_MINIGAME, OPT_DRAMA, OPT_EPISODE):
        if text.startswith(name):
            return name
    return None


def selected_option(page):
    """展开状态下，当前选中的是哪个选项。读不出返回 None。"""
    for r in _radios(page):
        if r.get("checked"):
            return _name_of(r.get("text", ""))
    return None


def _radio_of(page, name):
    """某个选项那一行的 locator。找不到返回 None。"""
    for r in _radios(page):
        if _name_of(r.get("text", "")) == name:
            loc = page.locator(f'[data-ep-r="{r["i"]}"]')
            try:
                return loc.first if loc.count() > 0 else None
            except Exception:
                return None
    return None


def _click_radio(page, radio):
    """点单选圈。必须点最左边那个圈，不能点中心（中心是说明文字，点了没反应）。"""
    if not on_screen(page, radio):
        scroll_into_comfortable_view(page, radio, label="剧集选项")
    try:
        box = radio.bounding_box()
    except Exception:
        box = None
    y = 19 if not box else min(19, max(6, box["height"] / 2))
    try:
        radio.click(timeout=8000, position={"x": 10, "y": y})
        return "点左侧圆圈"
    except Exception:
        pass
    # 退路：直接点 shadow DOM 里那个 input
    try:
        radio.evaluate("""el => {
          const i = el.shadowRoot && el.shadowRoot.querySelector('input.radio__display');
          (i || el).click();
        }""")
        return "点 shadow 里的 input"
    except Exception:
        return "都没点上"


def series_field_present(page):
    """「剧集」这个字段在不在。

    这是选中「剧集」之后的【真实结果】：优化位置选成剧集，页面才会渲染出
    身份 / 剧集 两个字段（实测 False -> True）。比读任何文字都可靠，
    所以拿它当验证的主证据。
    """
    return _named_field(page, SERIES_FIELD_TITLE) is not None


def select_optimization_location_episode(page, timeout_seconds=90):
    """把「优化位置」改成「剧集」。这是短剧端计划和另外两个模式的分界步骤。

    顺序（使用者口述）：
        点值右边的铅笔 -> 展开三个选项（不全就往下滑一点）-> 点「剧集」左边的小圆圈

    验证看【结果】不看【动作】，而且主证据是【「剧集」字段出没出现】：
    优化位置选成剧集，页面才会渲染出身份/剧集两个字段（真机实测 False -> True）。
    单选圈自己的选中状态藏在 shadow DOM 里，也读，但只当第二证据 ——
    读文字是绝对不行的，见 already_episode 的说明。
    """
    if already_episode(page) is True and series_field_present(page):
        print("          [优化位置] 已经是「剧集」，不用改", flush=True)
        return

    if not _open_options(page):
        raise ValueError(
            "展开「优化位置」的三个选项失败：点了铅笔图标，"
            f"但页面上没出现那几句选项说明。\n现场：{_section_debug(page)}"
        )

    print(f"          [优化位置] 展开后当前选中：{selected_option(page)!r}", flush=True)

    for attempt in range(3):
        radio = _radio_of(page, OPT_EPISODE)
        if radio is None:
            print(f"          [优化位置] 第{attempt + 1}轮：没找到「{OPT_EPISODE}」那个圆圈",
                  flush=True)
            page.wait_for_timeout(1200)
            continue

        if selected_option(page) == OPT_EPISODE and series_field_present(page):
            print(f"          [优化位置] 已选中「{OPT_EPISODE}」", flush=True)
            return

        how = _click_radio(page, radio)
        print(f"          [优化位置] 第{attempt + 1}轮：{how}", flush=True)
        page.wait_for_timeout(1500)

        def picked():
            # 主证据：选对了才会冒出「剧集」这个字段
            if series_field_present(page):
                return True
            # 第二证据：圆圈自己的状态（shadow DOM 里的 radio--checked）
            return selected_option(page) == OPT_EPISODE

        if wait_until(page, picked, timeout_seconds=20):
            print(f"          [优化位置] 已选中「{OPT_EPISODE}」"
                  f"（剧集字段已出现={series_field_present(page)}）", flush=True)
            return
        print(f"          [优化位置] 第{attempt + 1}轮点完还是没选上，"
              f"当前选中={selected_option(page)!r}", flush=True)

    raise ValueError(
        f"把「优化位置」改成「{OPT_EPISODE}」失败：三个选项已经展开，"
        f"但点了 3 轮「{OPT_EPISODE}」的圆圈都没选上。\n"
        f"当前选中: {selected_option(page)!r}；「剧集」字段出现了吗: "
        f"{series_field_present(page)}\n"
        f"三个圆圈现在的状态: {_radios(page)}"
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
# 广告层那个身份的字段标题不一样（而且是【另一个东西】，见 builder 的说明）
IDENTITY_AD_FIELD_TITLE = "身份（TikTok 账号）"
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
        // 先精确，再退到「以它开头」—— 广告层的身份标题后面还跟着一行
        // 「选择你希望接收私信的账号。」，精确匹配会漏掉
        const want = %s;
        if (t !== want && !t.startsWith(want)) continue;
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


def _click_row_containing(page, text, exclude_texts=(), found=None):
    """在展开的下拉里点包含 text 的那一行。

    下拉开着的时候【绝对不要滚页面，也不要用 robust_click】：
      * 滚页面会把下拉一起挪走（它锚在字段上），算好的坐标当场失效；
      * robust_click 点不到就升级成 JS 派发 el.click()，那是无视遮挡的 ——
        下拉正好盖在「优化位置」那三个单选圈上面，穿过去就把已经选好的
        「剧集」改回了别的，于是下一轮「剧集」字段整个消失。
        真机日志里连着两轮「没找到『剧集』字段」就是这么来的。
    交给 Playwright 自己点：它会把元素滚进【它所在的那个滚动容器】（下拉内部的
    滚动条），并且做可点性检查，被遮挡就报错而不是硬点。

    排掉搜索框那一层 —— 我刚把名字敲进搜索框，那几个字当然也匹配。
    """
    row = found if found is not None else _option_row_visible(page, text)
    if row is None:
        return False

    # 从文字往上找到「一行」。最内层优先：点行里面的子元素会冒泡到行上照样生效，
    # 点行外面的容器才可能落到别的行去。
    try:
        marked = row.evaluate("""el => {
          document.querySelectorAll('[data-ep-row]').forEach(
            e => e.removeAttribute('data-ep-row'));
          let n = el;
          for (let k = 0; k < 8 && n; k++) {
            const r = n.getBoundingClientRect();
            const st = getComputedStyle(n);
            if (r.width > 200 && r.height >= 28 && r.height < 160
                && st.pointerEvents !== 'none') {
              n.setAttribute('data-ep-row', '1');
              return true;
            }
            n = n.parentElement;
          }
          return false;
        }""")
    except Exception:
        marked = False

    targets = []
    if marked:
        loc = page.locator('[data-ep-row="1"]')
        try:
            if loc.count() > 0:
                targets.append(loc.first)
        except Exception:
            pass
    targets.append(row)

    for t in targets:
        try:
            t.click(timeout=8000)
            return True
        except Exception:
            continue
    return False


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


# 下拉搜完之后，平台明确告诉你「这个账号里没有这部剧」时的文案。
_SERIES_EMPTY_MARKERS = ("未找到剧集", "短剧创作者平台")


def _series_not_found_showing(page):
    """下拉里是不是明明白白写着「未找到剧集」。"""
    for m in _SERIES_EMPTY_MARKERS:
        if _first_visible(page.get_by_text(m, exact=False)) is not None:
            return True
    return False


def _option_row_visible(page, want):
    """下拉列表里【真的有】叫这个名字的选项行吗（身份用的就是这一版）。

    只排掉搜索框和输入框 —— 我刚把名字敲进搜索框，那几个字当然也匹配。
    身份这一步用它是安全的：身份名（WeShorts_US）不会出现在计划名里。
    剧集【不能】用这一版，剧名来自计划名开头，页面上到处都是，
    见 _series_option_row。
    """
    loc = page.get_by_text(str(want), exact=False)
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(min(n, 20)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            bad = el.evaluate("""el => {
              const tag = el.tagName.toLowerCase();
              if (tag === 'input' || tag === 'textarea') return true;
              if (el.closest && el.closest('input,textarea')) return true;
              let n = el;
              for (let k = 0; k < 4 && n; k++) {
                if (n.getAttribute && n.getAttribute('placeholder')) return true;
                n = n.parentElement;
              }
              return false;
            }""")
            if not bad:
                return el
        except Exception:
            continue
    return None


# 剧集列表的行长这样（真机实测）：缩略图 + 剧名 + 「31 视频 · 22m」。
# 「视频」这两个字就是最好的判据 —— 左侧计划树那一行只有计划名，没有它。
_SERIES_ROW_MARK = "视频"


def _series_option_row(page, want):
    """剧集下拉里那一行。比身份严格得多，因为剧名到处都是。

    真机上花了很久才定位到的一个坑（使用者一眼看出来的）：
    剧名是从【计划名开头】取的，所以左侧计划树里那行计划名、广告组名称输入框里，
    都含这几个字。原来在整页范围里取第一个匹配，命中的就是【左侧那一列】，
    点下去直接跳回计划层级（URL 变成 create/campaign），广告组页整个没了，
    后面才会报「优化位置字段不在了」。

    判据：候选往上找到的那一行，文字里必须带「视频」——
    那是剧集行独有的（「31 视频 · 22m」）。左侧计划树的行不会有。
    """
    loc = page.get_by_text(str(want), exact=False)
    try:
        n = loc.count()
    except Exception:
        return None
    for i in range(min(n, 25)):
        el = loc.nth(i)
        try:
            if not el.is_visible():
                continue
            ok = el.evaluate("""(el, mark) => {
              const tag = el.tagName.toLowerCase();
              if (tag === 'input' || tag === 'textarea') return false;
              if (el.closest && el.closest('input,textarea')) return false;
              let n = el;
              for (let k = 0; k < 4 && n; k++) {
                if (n.getAttribute && n.getAttribute('placeholder')) return false;
                n = n.parentElement;
              }
              // 往上找到「一行」，看那一行有没有「视频」字样
              n = el;
              for (let k = 0; k < 8 && n; k++) {
                const r = n.getBoundingClientRect();
                if (r.width > 200 && r.height >= 28 && r.height < 160) {
                  return (n.innerText || '').includes(mark);
                }
                n = n.parentElement;
              }
              return false;
            }""", _SERIES_ROW_MARK)
            if ok:
                return el
        except Exception:
            continue
    return None


# 当前展开的那个下拉浮层。用【搜索框】反推：搜索框在哪个浮层里，那个就是。
#
# 为什么必须限定在浮层里找选项 —— 这是真机上最贵的一个教训：
# 剧名是从【计划名开头】取的，所以左边那一列的计划名、广告组名里当然都有这几个字。
# 原来在整个页面范围里 get_by_text(剧名)，DOM 顺序上第一个命中的就是
# 【左侧计划树里那一行】，点下去直接跳回计划层级（URL 变成 create/campaign），
# 广告组页整个没了 —— 于是后面报「优化位置字段不在了」，看着像优化位置被改回去，

def _wait_row_settled(page, want, timeout_seconds=30, finder=None):
    """等下拉里那一行出现【并且位置不再动】，然后才把它交出去。

    为什么非要等「不动」：搜索是异步过滤的，列表会重排。
    探针里搜完固定等 6 秒再点，一次就成；正式代码一发现行就点，连点 3 轮都失败 ——
    点到的是马上要被替换掉的那一行。这个坑在这个项目里已经是第三次
    （价值类型、商品库的 Mini / 价值类型都是它），所以按「位置连续两次不变」判，
    不用固定 sleep：快的时候不白等，慢的时候固定值又不够。

    finder 让调用方指定用哪个查找器 —— 身份用宽松的 _option_row_visible，
    剧集必须用严格的 _series_option_row（剧名到处都是）。
    """
    find = finder or _option_row_visible
    vh = viewport_h(page)
    stable, last = 0, None
    rounds = max(1, int(timeout_seconds * 1000 / 500))
    for _ in range(rounds):
        row = find(page, want)
        if row is None:
            stable, last = 0, None
        else:
            try:
                m = row.evaluate(MEASURE_JS, vh)
                y = None if not m else round(m["y"])
            except Exception:
                y = None
            if y is not None and last is not None and abs(y - last) <= 2:
                stable += 1
                if stable >= 2:
                    return row
            else:
                stable = 0
            last = y
        page.wait_for_timeout(500)
    return find(page, want)


def _picked_by_locator(page, want, title):
    """选中了没 —— 只用 Playwright 定位器判断，而且【限定在那个字段里面找】。

    为什么不读字段文字：这两个框是 ks-select，显示值在 shadow DOM 里，
    我写的那个「读字段值」的 JS 一直读成 None（试过修 nodeType 11 那一处，
    还是读不出来），于是明明选上了也判成失败、一轮轮重试，反而把前面选好的
    东西点乱（真机日志里「第2轮：没找到「剧集」字段」就是被自己retry搞没的）。

    换成一个不依赖读值的判据，两条同时成立才算数：
      ① 下拉关上了（搜索框不见了）
      ② 页面上还能看到这个名字 —— 此时它只可能在【收起的框】里
    选之前：名字只在展开的下拉里（①不成立）；
    没选中：下拉关了但框里是别的名字（②不成立）。两种都能正确判负。

    Playwright 的定位器能穿透 shadow DOM，这是这个项目一开始就记下来的
    （「找元素一律用定位器，不要用 document.querySelectorAll」）。
    """
    if _visible_search_input(page) is not None:
        return False
    fld = _named_field(page, title)
    if fld is None:
        return False
    # 【必须限定在字段内】。第一版是全页面找这个名字，结果剧集那边直接假阳性：
    # 剧名同时出现在计划名和广告组名里（计划就叫「The Don's Secret Heir-zzw-...」），
    # 于是一开始就判成「已经选好了，不用改」，整个选剧集的步骤被跳过。
    # locator 链式调用同样能穿透 shadow DOM，所以限定作用域不会漏掉 ks-select 的显示值。
    try:
        return _first_visible(fld.get_by_text(str(want), exact=False)) is not None
    except Exception:
        return False


def _network_error_showing(page):
    """页面上有没有「网络错误。请稍后重试。」那个提示。"""
    try:
        return _first_visible(page.get_by_text("网络错误", exact=False)) is not None
    except Exception:
        return False


def _click_refresh(page):
    """点下拉底部那个「刷新」按钮。"""
    btn = _first_visible(page.get_by_text("刷新", exact=True))
    if btn is None:
        return False
    try:
        robust_click(page, btn, timeout=5000)
        return True
    except Exception:
        return False


def select_identity_episode(page, identity_name, timeout_seconds=60,
                            title=IDENTITY_FIELD_TITLE):
    """选身份。

    使用者口述：点身份下面那个【写了身份名字】的框，出现列表（带「按账号名搜索」
    搜索框、「由商务中心共享」下面几个账号），点表格里那个身份就选中了。

    已经就是要的那个就不动它 —— 身份标着「共享设置」，会从同账号上一个计划带过来。
    这条规矩在商品库那边（Mini / 价值类型 / ROAS / 地域）反复踩过五次，这里一开始就写上。
    """
    want = str(identity_name or "").strip()
    if not want:
        return "表格没给身份，跳过"

    cur = _field_value(page, title)
    if cur and want.lower() in cur.lower():
        return f"身份已经是「{cur}」，不用改"

    for attempt in range(3):
        box, fld = _field_box(page, title)
        if box is None:
            print(f"          [身份] 第{attempt + 1}轮：没找到「{title}」字段", flush=True)
            page.wait_for_timeout(1500)
            continue
        if not on_screen(page, box):
            scroll_into_comfortable_view(page, box, label="身份框")
        how = _click_box(page, box)
        page.wait_for_timeout(900)

        # 【不要搜索】。真机实测：往「按账号名搜索」里输入显示名（WeShorts_US）
        # 会把三行全过滤掉，一个都不剩 —— 它多半是按下面那行小写的 handle
        # （weshorts_us）匹配的。不搜的时候三行好好地列在那儿。
        # 小游戏那边的身份选择器注释里早就写了同一件事：
        # 「只有几个身份共享给这个账号，不用搜，直接点匹配的那一个」。
        #
        # 列表是异步加载的，等它把那一行渲染出来再点，别一开就点。
        got = _wait_row_settled(page, want, timeout_seconds=20)
        print(f"          [身份] 第{attempt + 1}轮：{how}，列表里出现「{want}」={got is not None}",
              flush=True)

        # 排掉收起态那个框里的同名文字（点它只会把下拉关掉）
        if _click_row_containing(page, want, exclude_texts=(title,)):
            page.wait_for_timeout(1200)
            _close_dropdown_if_open(page)
            if wait_until(page, lambda: _picked_by_locator(page, want, title),
                          timeout_seconds=12):
                print(f"          [身份] 已选中「{want}」", flush=True)
                return None
        print(f"          [身份] 第{attempt + 1}轮没选上"
              f"（下拉还开着={_visible_search_input(page) is not None}）", flush=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(800)

    raise ValueError(
        f"选身份「{want}」失败：点了 3 轮。"
        "如果这个身份不在「由商务中心共享」列表里，需要先在后台把它共享给这个广告账号。"
    )


def select_series_episode(page, series_name, timeout_seconds=90):
    """选剧集。

    使用者口述：点剧集下面那个框（写着「选择剧集」，点那几个字就行），出现小列表，
    上面可以搜索，搜到再点就选中了。剧目很多，要投的那部可能在很下面，所以一定要搜。

    重试策略是使用者定的：「你搜到了，他只是没刷新出来，你直接关了，等五秒刷新一下」。
    所以失败一轮就【关掉下拉、等 5 秒、重新打开再搜】，而不是在开着的下拉里反复点。

    另外带一道自愈：真机日志里第 1 轮失败之后，「剧集」这个字段会整个消失 ——
    说明那一次点击落到了下拉底下的「优化位置」单选圈上，把它从「剧集」改回去了。
    所以每轮开头先确认字段还在，不在就把优化位置重新选回剧集。
    不做这个的话，后面两轮只会一直报「没找到剧集字段」，白跑。
    """
    want = str(series_name or "").strip()
    if not want:
        raise ValueError("表格里没给剧集名，没法选剧集")

    def picked():
        return _picked_by_locator(page, want, SERIES_FIELD_TITLE)

    if picked():
        print(f"          [剧集] 已经是「{want}」，不用改", flush=True)
        return

    for attempt in range(4):
        # 自愈：字段没了说明优化位置被点回去了，先修回来
        if not series_field_present(page):
            print(f"          [剧集] 第{attempt + 1}轮：「剧集」字段不在了"
                  "（优化位置被改回去了），先重新选回剧集", flush=True)
            try:
                select_optimization_location_episode(page)
                wait_fields_settled(page)
                page.wait_for_timeout(1500)
            except Exception as e:
                raise ValueError(
                    f"想把「优化位置」修回「剧集」再选剧集，但修不回来: "
                    f"{str(e).splitlines()[0][:140]}"
                )

        box, fld = _field_box(page, SERIES_FIELD_TITLE)
        if box is None:
            print(f"          [剧集] 第{attempt + 1}轮：没找到「剧集」字段", flush=True)
            page.wait_for_timeout(1500)
            continue
        if not on_screen(page, box):
            scroll_into_comfortable_view(page, box, label="剧集框")
        how = _click_box(page, box)
        page.wait_for_timeout(1500)

        searched = _type_search(page, want)
        found = _wait_row_settled(page, want, finder=_series_option_row)

        # 列表报网络错误 / 干脆没加载出来时，点一下下拉底部那个「刷新」
        if found is None and (_network_error_showing(page) or not searched):
            if _click_refresh(page):
                print("          [剧集] 点了下拉里的「刷新」", flush=True)
                page.wait_for_timeout(3000)
                _type_search(page, want)
                found = _wait_row_settled(page, want, finder=_series_option_row)

        # 平台直说「未找到剧集」：这是数据问题不是定位问题，别再点了
        if found is None and _series_not_found_showing(page):
            raise ValueError(
                f"这个广告账号的「剧集」列表里没有《{want}》。\n"
                "下拉里平台的原话是「未找到剧集 —— 请先在 TikTok 短剧创作者平台创建剧集，"
                "然后返回此处并刷新」。\n"
                "注意剧集列表是【跟着身份变的】，先确认表里 Identity_drama 那一列"
                "填的是拥有这部剧的那个身份。"
            )

        print(f"          [剧集] 第{attempt + 1}轮：{how}，搜索={'有' if searched else '无'}，"
              f"列表里出现「{want}」={found is not None}", flush=True)

        if found is not None and _click_row_containing(page, want, found=found):
            page.wait_for_timeout(1500)
            if wait_until(page, picked, timeout_seconds=15):
                print(f"          [剧集] 已选中「{want}」", flush=True)
                return

        # 失败时把现场截下来。选剧集这一步坑最多（下拉盖在优化位置上面、
        # 列表跟着身份变、还会重排），光看日志猜不出点到哪儿去了。
        try:
            from src.config import LOGS_DIR

            shot = LOGS_DIR / f"episode_series_FAIL_{attempt + 1}.png"
            page.screenshot(path=str(shot))
            print(f"          [剧集] 现场截图: {shot}", flush=True)
            print(f"          [剧集] 当前 URL: {page.url[:110]}", flush=True)
        except Exception:
            pass

        # 使用者说的：关掉、等五秒、再刷新重来
        print(f"          [剧集] 第{attempt + 1}轮没选上，关掉下拉等 5 秒再重开", flush=True)
        try:
            page.keyboard.press("Escape")
        except Exception:
            pass
        page.wait_for_timeout(5000)

    raise ValueError(
        f"选剧集「{want}」失败：关掉重开搜了 4 轮都没选上。\n"
        f"「剧集」字段还在吗: {series_field_present(page)}；"
        f"下拉还开着吗: {_visible_search_input(page) is not None}\n"
        "剧集列表是跟着身份变的 —— 确认表里 Identity_drama 填的是拥有这部剧的身份。"
    )


def fill_adgroup_core(page, rec, identity_name, series_name, region_pairs):
    """短剧端计划的广告组层，一整条走完。

    使用者口述的完整顺序：
        广告组名称
        -> 优化位置改成「剧集」
        -> （等三四秒重新渲染，往下滑到能看到身份框和剧集框）
        -> 身份
        -> 剧集
        -> 选择价值类型（= 广告收入价值）
        -> 目标 ROAS
        -> 地域
        -> 继续

    哪些是复用、哪些是新写的，写在这里省得以后翻：
      * 广告组名称   复用小游戏 src/pages/adgroup_page.fill_ad_group_name
      * 优化位置     本文件新写（三个模式的分界点）
      * 身份 / 剧集  本文件新写（商品库那边没有这两个字段）
      * 价值类型     复用 src/pages/value_type.select_ad_revenue_value_type
                     —— 使用者确认要「广告收入价值」，和商品库同一个要求
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
    #
    # 选完身份【必须先等它安定】再碰剧集：剧集列表是【跟着身份变的】——
    # 身份是 DreamStarComicTheater 时列表是一批日文剧，换成 WeShorts_US 才是
    # 要投的那批英文剧。也就是说选完身份平台会重新拉一次剧集列表。
    # 不等的话，搜索会和这次重新加载撞上：行确实出现过（旧列表或加载中间态），
    # 点下去却已经被替换掉了，于是「点了但没选上」，连着 3 轮都这样。
    # 同一个探针改成选完身份等 2.5 秒就一次成功 —— 这里用等位置站稳，
    # 比固定 sleep 靠得住。
    if not wait_fields_settled(page):
        warnings.append("选完身份之后「剧集」字段一直没安定下来，选剧集可能失败")
    page.wait_for_timeout(1500)

    select_series_episode(page, series_name)

    # ---- 选择价值类型 = 广告收入价值 ----
    # 使用者确认过这一项要的是「广告收入价值」。
    #
    # 截图上它显示成【纯文本 + 共享设置】而不是下拉，说明是从同账号上一个计划
    # 带过来的、这个账号上本来就对。但「已经对了」不等于「每个账号都对」——
    # 带过来的要是「应用内购价值」，这条计划就会按错的目标去优化、花错的钱。
    # 所以还是走一遍：已经对了会立刻返回（函数自己有这个判断），不对才去改。
    #
    # 这一步【是关键项】，改不了就停。和身份不同：身份选错只是发布者显示不对，
    # 价值类型错了是优化目标错了。
    from src.pages.value_type import select_ad_revenue_value_type

    select_ad_revenue_value_type(page)

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
