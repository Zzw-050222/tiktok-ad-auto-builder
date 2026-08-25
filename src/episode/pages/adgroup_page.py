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
from src.pages.viewport import on_screen, scroll_into_comfortable_view

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
