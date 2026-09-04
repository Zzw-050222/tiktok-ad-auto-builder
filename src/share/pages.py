"""自动共享素材 —— 创意素材库页面上的每一步操作。

使用者演示的完整流程（2026-09-04）：

    ① 打开源账号的素材库
    ② 右下角「20/页」-> 选「100/页」-> 等它刷新几秒
    ③ 点搜索框，输入剧名
    ④ 搜索框下面弹出的小列表里，点【视频名称 包含每一项: 剧名】
       （不是回车、也不是别的三项：推广系列名称 / 广告组名称 / 广告名称）
    ⑤ 点表头「视频」左边那个小方框 = 全选当前页
    ⑥ 点「共享」按钮 -> 弹出「共享视频」窗口
    ⑦ 在窗口【里面】滚到底，找到「与选定的广告账号共享」下面那个搜索框
    ⑧ 输入目标账号名 -> 点搜索结果左边的方框勾上
    ⑨ 要share给多个账号：把输入框里的字【删掉】，输下一个，再勾一个
    ⑩ 全部勾完，点窗口【内】任意位置把下拉收起来
       —— 使用者特意强调：不能点窗口外面，那样下拉会收回（弹窗也可能关掉）
    ⑪ 点「确认」

素材超过 100 条时怎么办，使用者说解决办法在这之后，还没给 —— 见 share_one_drama
里那段说明，接口留好了。

写这个模块时照搬的、这个项目已经踩过的规矩：
  * 一律不用 .first —— 用 common.visible_only 挑可见的
  * 验证看【结果】不看【动作】
  * 失败时把现场（可见按钮、弹层文字）打出来，别只报一句「没找到」
"""

from src.pages.common import robust_click, visible_only, wait_until

# 页面上的固定文案
PAGE_SIZE_100 = "100/页"
SEARCH_PLACEHOLDER = "按名称、ID、设置、指标或其他筛选条件搜索"
# 搜索建议里那一项。四项里只有这一项是按【视频名称】筛的，
# 另外三项是 推广系列名称 / 广告组名称 / 广告名称，点错了搜出来的东西完全不同。
VIDEO_NAME_OPTION = "视频名称"
SHARE_BUTTON = "共享"
SHARE_MODAL_TITLE = "共享视频"
ACCOUNT_SECTION = "与选定的广告账号共享"
# 弹窗底部那个控件【折叠】时显示的字。注意它不是 input 的 placeholder 属性，
# 是一个 div 的文字内容 —— 所以 get_by_placeholder 找不到它（第一版就栽在这）。
ACCOUNT_FIELD_HINT = "按广告账号名称或 ID 搜索"
# 点开那个下拉之后，悬浮面板里才有真正的 <input>，它的 placeholder 是「搜索」。
ACCOUNT_SEARCH_PLACEHOLDER = "搜索"
CONFIRM_BUTTON = "确认"


# ---------------------------------------------------------------------------
# 这个平台的列表和弹窗都渲染在 shadow DOM 里，document.querySelectorAll
# 【穿不过 shadow root】。探针实测（2026-09-04，素材库列表页）：
#     平铺 document.querySelectorAll('*') -> 4344 个元素
#     穿透 shadow 遍历                    -> 15687 个元素
# 整张表格都在后面那一万多个里。
#
# 更坑的是它不报错，只会静默地找不到 —— 或者更糟，匹配到页面上同名的【别的】东西。
# 第一版找全选框就是这样：平铺查询找「视频」两个字，匹配到的是顶部那个
# 「视频」标签页，顺着它往上找行、找复选框，当然永远找不到，
# 报出来的却是一句干巴巴的「没找到全选方框」。
#
# 所以这个模块里凡是要在页面上找东西的 JS，一律用 deepAll，不用 querySelectorAll。
# ---------------------------------------------------------------------------
_DEEP_JS = r"""
  function deepAll(root) {
    const out = [];
    const stack = [root];
    while (stack.length) {
      const n = stack.pop();
      if (!n) continue;
      if (n.nodeType === 1) out.push(n);
      if (n.shadowRoot) stack.push(...n.shadowRoot.children);
      if (n.children) stack.push(...n.children);
    }
    return out;
  }
  function deepClearMark(attr) {
    deepAll(document.documentElement).forEach(e => {
      if (e.removeAttribute) e.removeAttribute(attr);
    });
  }
  // 复选框宿主：<ks-checkbox-1-1-1g class="KsCheckbox">。
  // 标签名带版本后缀（同页面上还有 ks-thumbnail-93nwixv3、ks-text-ptiwde8b），
  // 平台一发版后缀就变，所以按前缀 + class 两个特征认，不写死整个标签名。
  function isKsCheckbox(e) {
    const tag = e.tagName.toLowerCase();
    const cls = e.getAttribute('class') || '';
    if (!(tag.startsWith('ks-checkbox') || /(^|\s)KsCheckbox(\s|$)/.test(cls))) {
      return false;
    }
    const r = e.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  }
  // 选没选中：两个信号哪个成立都算。缺一不可 —— 实测这两种框行为【不一样】：
  //   * 素材表格里的行框：原生 input.checked 会变 True
  //   * 账号下拉里的选项框：原生 input.checked 【永远是 False】，
  //     选中只体现在 shadow 里那个 checkbox--checked 的 class 上
  // 只读原生 input 的话，账号勾上了也读成没勾上；这个项目在 ks-radio 上
  // 已经栽过一次同样的坑（选中状态只活在 shadow DOM 里）。
  // 而且这里读错的代价不是「报个错」：外层看到「没勾上」会再点一次，
  // 那一下正好把已经勾上的取消掉，最后什么都没共享。
  function ksChecked(host) {
    const sr = host.shadowRoot;
    if (!sr) return false;
    const inp = sr.querySelector('input');
    if (inp && inp.checked) return true;
    return [...sr.querySelectorAll('*')].some(
      e => /checkbox--checked/.test(e.getAttribute('class') || ''));
  }
"""


def _deep(body):
    """把 deepAll 那几个工具函数塞进一段 JS 的开头。"""
    return "() => {" + _DEEP_JS + body + "}"


def _deep_el(body):
    """同上，但收一个参数 —— locator.evaluate 传进来的元素，或 page.evaluate 传的值。"""
    return "(el) => {" + _DEEP_JS + body + "}"


def _vis(loc):
    """只留可见的匹配。"""
    return visible_only(loc)


def _first_vis(loc):
    v = _vis(loc)
    try:
        return v.first if v.count() > 0 else None
    except Exception:
        return None


def set_page_size_100(page, timeout_seconds=60):
    """把右下角的每页条数从 20 改成 100。

    为什么要改：全选那个方框只选【当前页】。默认 20/页，一次只能共享 20 条；
    改成 100/页 一次能共享 100 条，是使用者演示里的第一步。
    """
    # 已经是 100 就不动它
    if _first_vis(page.get_by_text(PAGE_SIZE_100, exact=True)) is not None:
        # 「100/页」既可能是收起态显示的当前值，也可能是展开后的选项。
        # 收起态就显示 100 说明已经是了。
        trigger = _first_vis(page.get_by_text(PAGE_SIZE_100, exact=True))
        try:
            if trigger.is_visible():
                print("      [素材库] 每页条数已经是 100", flush=True)
                return True
        except Exception:
            pass

    trigger = wait_until(
        page,
        lambda: _first_vis(page.get_by_text("20/页", exact=True)),
        timeout_seconds=timeout_seconds,
    )
    if trigger is None:
        return False

    robust_click(page, trigger, timeout=6000)
    page.wait_for_timeout(800)

    opt = wait_until(
        page,
        lambda: _first_vis(page.get_by_text(PAGE_SIZE_100, exact=True)),
        timeout_seconds=15,
    )
    if opt is None:
        return False
    robust_click(page, opt, timeout=6000)

    # 换页大小之后列表要重新拉，使用者说「等他刷新几秒」。
    # 不固定 sleep：等到行数稳定下来。
    page.wait_for_timeout(2000)
    _wait_rows_settled(page)
    print("      [素材库] 每页条数已改成 100", flush=True)
    return True


def _row_count(page):
    """当前列表里有多少行（用视频 ID 那一列的长数字认）。"""
    try:
        return _vis(page.locator(r"text=/^\d{15,}$/")).count()
    except Exception:
        return 0


def _wait_rows_settled(page, timeout_seconds=40):
    """等列表加载完：行数连续两次不变就算稳了。

    和商品库那边等价值类型渲染是同一个套路 —— 这个后台的列表会先出一批、
    再刷一批，一看到有行就动手会点在马上被替换掉的元素上。
    """
    stable, last = 0, None
    rounds = max(1, int(timeout_seconds * 1000 / 500))
    for _ in range(rounds):
        n = _row_count(page)
        if n > 0 and n == last:
            stable += 1
            if stable >= 2:
                return n
        else:
            stable = 0
        last = n
        page.wait_for_timeout(500)
    return _row_count(page)


def search_by_video_name(page, drama_name, timeout_seconds=60):
    """在搜索框输入剧名，然后点【视频名称 包含每一项】那一项。

    必须点那一项，不能回车：弹出的小列表有四项（推广系列名称 / 广告组名称 /
    广告名称 / 视频名称），只有最后一项是按视频名筛的。

    返回筛完之后的行数。
    """
    box = wait_until(
        page,
        lambda: _first_vis(page.get_by_placeholder(SEARCH_PLACEHOLDER)),
        timeout_seconds=timeout_seconds,
    )
    if box is None:
        raise ValueError(
            f"没找到素材库的搜索框（占位文字「{SEARCH_PLACEHOLDER}」）"
        )
    box.click(timeout=8000)
    box.fill("")
    page.keyboard.type(str(drama_name))
    page.wait_for_timeout(1200)

    # 在弹出的建议列表里找「视频名称」那一行。
    # 用 get_by_text 找到「视频名称」这几个字，再往上走到可点的那一行 ——
    # 这四项的文字结构是「视频名称 包含每一项: <剧名>」。
    opt = wait_until(page, lambda: _video_name_option(page), timeout_seconds=20)
    if opt is None:
        raise ValueError(
            f"输入「{drama_name}」之后，搜索建议里没找到「{VIDEO_NAME_OPTION}」那一项。"
            f"\n当前可见的建议项：{_suggestion_texts(page)}"
        )
    robust_click(page, opt, timeout=8000)
    page.wait_for_timeout(1500)

    n = _wait_rows_settled(page)
    print(f"      [素材库] 按视频名称搜「{drama_name}」，筛出 {n} 条", flush=True)
    return n


def _video_name_option(page):
    """搜索建议里「视频名称 包含每一项: xxx」那一行（可点的那一层）。"""
    cands = _vis(page.get_by_text(VIDEO_NAME_OPTION, exact=False))
    try:
        n = cands.count()
    except Exception:
        return None
    for i in range(min(n, 12)):
        el = cands.nth(i)
        try:
            txt = (el.inner_text(timeout=1500) or "").strip()
        except Exception:
            continue
        # 只认建议项那一条：它同时含「视频名称」和「包含」
        if VIDEO_NAME_OPTION not in txt or "包含" not in txt:
            continue
        marked = el.evaluate(_deep_el(r"""
          deepClearMark('data-sh-opt');
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            const r = n.getBoundingClientRect();
            const st = getComputedStyle(n);
            if (r.width > 120 && r.height >= 24 && r.height < 140
                && st.pointerEvents !== 'none') {
              n.setAttribute('data-sh-opt', '1');
              return true;
            }
            n = n.parentElement || (n.getRootNode() && n.getRootNode().host);
          }
          return false;
        """))
        if marked:
            loc = page.locator('[data-sh-opt="1"]')
            try:
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass
        return el
    return None


def _suggestion_texts(page, limit=8):
    """当前可见的搜索建议项文字，报错时用。"""
    out = []
    try:
        loc = _vis(page.get_by_text("包含", exact=False))
        for i in range(min(loc.count(), limit)):
            t = (loc.nth(i).inner_text(timeout=1000) or "").replace("\n", " ").strip()
            if t:
                out.append(t[:60])
    except Exception:
        pass
    return out


def select_all_on_page(page, timeout_seconds=30):
    """点表头「视频」左边那个小方框 = 全选当前页。返回【勾上了几条】。

    验证看【结果】：数据行的复选框真的勾上了没有，勾上了几条。
    不看「点了没点到」—— 这个项目已经因为「验证动作而不是验证结果」吃过亏。
    """
    cb = wait_until(page, lambda: _header_checkbox(page), timeout_seconds=timeout_seconds)
    if cb is None:
        raise ValueError(
            "没找到表头「视频」左边的全选方框。\n现场：" + str(_checkbox_debug(page))
        )
    robust_click(page, cb, timeout=8000)

    n = wait_until(page, lambda: _checked_row_count(page) or None, timeout_seconds=15)
    if not n:
        raise ValueError(
            "点了表头的全选方框，但一条数据行都没被勾上。\n现场："
            + str(_checkbox_debug(page))
        )
    print(f"      [素材库] 全选当前页，勾上 {n} 条", flush=True)
    return n


def _header_checkbox(page):
    """表头那一行里、「视频」左边的全选方框。

    探针实测（2026-09-04）：它是 <ks-checkbox-1-1-1g class="KsCheckbox">，20x20，
    在 tr.table__thead-row 里，和「视频」两个字同一条基线（y 都是 314，
    它在 x=256，「视频」在 x=308）。整张表在 shadow DOM 里，见文件开头那段说明。

    按表头行来找，不能全页面找复选框 —— 100 行数据每行前面都有一个一模一样的。
    """
    marked = page.evaluate(_deep(r"""
      deepClearMark('data-sh-all');
      const all = deepAll(document.documentElement);
      // 表头行：class 里带 thead 的 tr（实测 table__thead-row）
      const heads = all.filter(e =>
        e.tagName === 'TR'
        && /thead/i.test(e.getAttribute('class') || '')
        && e.getBoundingClientRect().width > 300);
      for (const row of heads) {
        const cb = deepAll(row).find(isKsCheckbox);
        if (cb) { cb.setAttribute('data-sh-all', '1'); return 'thead'; }
      }
      // 退路：表头行的 class 万一改了名，就取整页最靠上的那个方框
      // —— 数据行的方框都在表头下面。要求至少有两个，避免页面上只剩一个
      // 孤零零的复选框时把它当成全选框点下去。
      const boxes = all.filter(isKsCheckbox)
        .sort((a, b) => a.getBoundingClientRect().y - b.getBoundingClientRect().y);
      if (boxes.length >= 2) { boxes[0].setAttribute('data-sh-all', '1'); return 'topmost'; }
      return null;
    """))
    if not marked:
        return None
    if marked == "topmost":
        print("      [素材库] 注意：表头行没认出来，按「最靠上的方框」当全选框用了",
              flush=True)
    loc = page.locator('[data-sh-all="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def _checked_row_count(page):
    """数据行里已经勾上的条数（不含表头那个全选框本身）。"""
    try:
        return page.evaluate(_deep(r"""
          return deepAll(document.documentElement)
            .filter(isKsCheckbox)
            .filter(e => !e.hasAttribute('data-sh-all'))
            .filter(ksChecked).length;
        """))
    except Exception:
        return 0


def _checkbox_debug(page):
    """找不到 / 点不动时的现场：页面上到底有几个方框、勾上几个、表头行认出来没有。"""
    try:
        return page.evaluate(_deep(r"""
          const all = deepAll(document.documentElement);
          const boxes = all.filter(isKsCheckbox);
          return {
            可见方框数: boxes.length,
            已勾选: boxes.filter(ksChecked).length,
            表头行数: all.filter(e => e.tagName === 'TR'
              && /thead/i.test(e.getAttribute('class') || '')).length,
            数据行数: all.filter(e => e.tagName === 'TR'
              && !/thead/i.test(e.getAttribute('class') || '')).length,
            穿透元素数: all.length,
            平铺元素数: document.querySelectorAll('*').length,
          };
        """))
    except Exception as e:
        return f"现场也读不出来: {e}"


def open_share_modal(page, timeout_seconds=30):
    """点「共享」，等「共享视频」弹窗出来。"""
    btn = wait_until(
        page,
        lambda: _first_vis(page.get_by_role("button", name=SHARE_BUTTON, exact=True))
        or _first_vis(page.get_by_text(SHARE_BUTTON, exact=True)),
        timeout_seconds=timeout_seconds,
    )
    if btn is None:
        raise ValueError("没找到「共享」按钮（要先全选才会变成可点）")
    robust_click(page, btn, timeout=8000)

    ok = wait_until(page, lambda: share_modal_open(page), timeout_seconds=20)
    if not ok:
        raise ValueError(
            f"点了「{SHARE_BUTTON}」但「{SHARE_MODAL_TITLE}」弹窗没出来。"
            f"\n当前可见按钮：{_visible_button_names(page)}"
        )
    return True


def share_modal_open(page):
    return _first_vis(page.get_by_text(SHARE_MODAL_TITLE, exact=True)) is not None


def _visible_button_names(page, limit=20):
    out = []
    try:
        loc = _vis(page.get_by_role("button"))
        for i in range(min(loc.count(), limit)):
            t = (loc.nth(i).inner_text(timeout=800) or "").strip()
            if t:
                out.append(t[:24])
    except Exception:
        pass
    return out


def _account_select(page):
    """弹窗底部「与选定的广告账号共享」下面那个下拉控件（折叠状态）。

    探针实测（2026-09-04）：
        ks-select-1-1-1g.KsSelect  @(924,1222) 552x36
          └ ks-value-field-1-1-1g.KsValueField
              └ div.value-field__tagged__input   文字 = 「按广告账号名称或 ID 搜索」

    它是个【多选带标签】的下拉，不是输入框。那句「按广告账号名称或 ID 搜索」
    是 div 的文字内容而不是 placeholder 属性，所以 get_by_placeholder 找不到 ——
    第一版就是在这里死的，报「弹窗里没找到账号搜索框」。
    """
    marked = page.evaluate(_deep(r"""
      deepClearMark('data-sh-sel');
      const all = deepAll(document.documentElement);
      const label = all.find(e => !e.children.length
        && (e.textContent || '').trim() === '与选定的广告账号共享');
      if (!label) return false;
      // 从标签往上找它那个小容器，再在容器里找 KsSelect
      let box = label;
      for (let k = 0; k < 5 && box; k++) {
        box = box.parentElement || (box.getRootNode() && box.getRootNode().host);
        if (!box) break;
        const sel = deepAll(box).find(e => {
          const tag = e.tagName.toLowerCase();
          const cls = e.getAttribute('class') || '';
          if (!(tag.startsWith('ks-select') || /(^|\s)KsSelect(\s|$)/.test(cls))) {
            return false;
          }
          const r = e.getBoundingClientRect();
          return r.width > 100 && r.height > 10;
        });
        if (sel) { sel.setAttribute('data-sh-sel', '1'); return true; }
      }
      return false;
    """))
    if not marked:
        return None
    loc = page.locator('[data-sh-sel="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def _account_search_input(page):
    """点开下拉之后，悬浮面板里那个真正的输入框（placeholder=「搜索」）。"""
    return _first_vis(page.get_by_placeholder(ACCOUNT_SEARCH_PLACEHOLDER, exact=True))


def _open_account_dropdown(page, timeout_seconds=15):
    """点开账号下拉，等面板里的搜索框出来。已经开着就直接返回。"""
    if _account_search_input(page) is not None:
        return True
    sel = _account_select(page)
    if sel is None:
        return False
    robust_click(page, sel, timeout=8000)
    return bool(wait_until(page, lambda: _account_search_input(page) is not None,
                           timeout_seconds=timeout_seconds))


def scroll_modal_to_account_section(page, timeout_seconds=30):
    """在弹窗【里面】往下滚，直到「与选定的广告账号共享」那一块露出来。

    使用者原话：「你需要在这个小窗口里滚轮滚到底就出现按名称搜索框」。
    滚的是弹窗内部的滚动容器，不是整个页面 —— 所以用 scrollTop 直接推那个容器，
    不用 mouse.wheel（滚轮滚的是鼠标底下那层，不确定是哪个）。
    """
    for _ in range(int(timeout_seconds * 2)):
        if _account_select(page) is not None:
            return True
        page.evaluate(_deep(r"""
          const all = deepAll(document.documentElement);
          // 找到弹窗里那个能滚的容器，往下推（实测 div.modal__body）
          const title = all.find(
            e => !e.children.length && (e.textContent || '').trim() === '共享视频');
          let n = title;
          for (let k = 0; k < 10 && n; k++) {
            n = n.parentElement || (n.getRootNode() && n.getRootNode().host);
            if (!n) break;
            const st = getComputedStyle(n);
            if (n.scrollHeight > n.clientHeight + 4 && /auto|scroll/.test(st.overflowY)) {
              n.scrollTop = n.scrollHeight;
              return;
            }
          }
          // 退路：只推弹窗里的滚动容器。
          // 不能「页面上所有能滚的都推到底」—— 那会把弹窗背后那张 100 行的表
          // 也一起滚到底（实测 table__wrapper 被推到 scrollTop=4614），
          // 白白改动背景页面的状态。
          all.forEach(e => {
            const cls = e.getAttribute('class') || '';
            if (!/modal/i.test(cls)) return;
            const st = getComputedStyle(e);
            if (e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(st.overflowY)) {
              e.scrollTop = e.scrollHeight;
            }
          });
        """))
        page.wait_for_timeout(500)
    return _account_select(page) is not None


def add_target_accounts(page, account_names, timeout_seconds=25):
    """在弹窗里把要共享到的账号一个个勾上。返回 (勾上的名字列表, 警告列表)。

    使用者演示的做法，一个字都别改：
        输入账号名 -> 点搜索结果左边的方框 -> 【把输入的字删掉】-> 输下一个 -> 再勾
    删干净很关键：不删的话第二次搜索是在上一次的词后面接着打，搜不到东西。
    """
    picked, warnings = [], []
    if not _open_account_dropdown(page):
        raise ValueError(
            f"点不开「{ACCOUNT_SECTION}」下面那个下拉（也没等到 placeholder="
            f"「{ACCOUNT_SEARCH_PLACEHOLDER}」的输入框）。可能是没滚到底。"
        )

    for name in account_names:
        name = str(name).strip()
        if not name:
            continue
        # 每一轮都重新确认下拉是开的：勾完一个之后面板有可能收起来
        if not _open_account_dropdown(page):
            warnings.append(f"要勾「{name}」时账号下拉打不开了")
            break
        box = _account_search_input(page)
        if box is None:
            warnings.append(f"要勾「{name}」时账号搜索框不见了")
            break
        box.click(timeout=8000)
        box.fill("")                    # 上一个账号名必须先删干净
        page.keyboard.type(name)
        page.wait_for_timeout(1500)

        row = wait_until(page, lambda n=name: _account_result_row(page, n),
                         timeout_seconds=timeout_seconds)
        if row is None:
            warnings.append(
                f"搜「{name}」在账号列表里没找到（平台显示「暂无数据」的话，"
                "确认账号名有没有写错、或者这个账号在不在你的可共享范围里）"
            )
            continue

        if not _tick_on(page, row, lambda n=name: _account_row_checked(page, n) is True):
            warnings.append(f"点了「{name}」那一行，但方框没有变成勾选状态，没算数")
            continue
        picked.append(name)
        print(f"      [共享] 已勾选目标账号「{name}」", flush=True)

    # 收尾再验一次【总账】：字段里应该给每个勾上的账号挂一个标签。
    # 这是和逐个回读互相独立的证据，也是点「确认」之前最后一道确认。
    field = _account_field_text(page)
    if field is not None:
        missing = [n for n in picked if n not in field]
        if missing:
            warnings.append(
                f"这些账号逐个看是勾上了，但最后在选择框里没看到它们的标签：{missing}"
            )
    return picked, warnings


def _tick_on(page, locator, is_on, tries=2):
    """把一个开关型控件点到【开】。已经是开的就不点。

    先看状态再决定点不点，是这里的关键：不能用 robust_click。
    robust_click 点不动会升级成 force 点击、再升级成 JS 派发，而复选框是开关 ——
    第一下其实已经生效、只是 Playwright 报了超时的话，第二下就把它关回去了。
    实测就是这么丢的：账号明明勾上了，回读读错以为没勾上，再点一次给取消了。
    """
    for _ in range(tries):
        if is_on():
            return True
        try:
            locator.click(timeout=6000)
        except Exception:
            pass
        page.wait_for_timeout(1000)
    return bool(is_on())


def _account_field_text(page):
    """账号选择框里现在显示的文字（勾上的账号会在里面挂成标签）。读不到返回 None。"""
    try:
        return page.evaluate(_deep(r"""
          const f = deepAll(document.documentElement).find(
            e => /value-field__tagged(\s|$)/.test(e.getAttribute('class') || ''));
          return f ? (f.textContent || '').trim() : null;
        """))
    except Exception:
        return None


def _account_row_checked(page, name):
    """「name」那一行的方框勾上了没有。读不出来返回 None（不当成失败）。"""
    try:
        return page.evaluate(_deep_el(r"""
          const want = el;
          const rows = deepAll(document.documentElement).filter(isKsCheckbox);
          for (const cb of rows) {
            let n = cb, txt = '';
            for (let k = 0; k < 6 && n; k++) {
              n = n.parentElement || (n.getRootNode() && n.getRootNode().host);
              if (!n) break;
              const t = (n.textContent || '').trim();
              if (t && t.length < 120) { txt = t; break; }
            }
            if (txt === want) return ksChecked(cb);
          }
          return null;
        """), name)
    except Exception:
        return None


def _account_result_row(page, name):
    """账号搜索结果里那一行的【复选框】。

    从账号名往上走到行，再取行里的复选框 —— 直接点名字未必落在可点区域上。
    """
    # 先按【完全相同】找，找不到再放宽到包含。
    # 实测这个账号列表里的名字是 '余禾-We shorts-US-GF-Light-yutong-0827-01'、
    # '...-0827-02'、'...-0827-03' 这种成串的，前缀彼此重叠：
    # 只按「包含」找，写 -01 会先撞上 -011 之类的行，勾错账号还看不出来。
    cands = _vis(page.get_by_text(name, exact=True))
    try:
        if cands.count() == 0:
            cands = _vis(page.get_by_text(name, exact=False))
        n = cands.count()
    except Exception:
        return None
    for i in range(min(n, 12)):
        el = cands.nth(i)
        marked = el.evaluate(_deep_el(r"""
          deepClearMark('data-sh-acct');
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            const r = n.getBoundingClientRect();
            if (r.width > 150 && r.height >= 24 && r.height < 120) {
              // 行里的方框和表头那个是同一种自定义元素，也在 shadow 里
              const cb = deepAll(n).find(isKsCheckbox);
              const target = cb || n;
              const tr = target.getBoundingClientRect();
              if (tr.width > 0 && tr.height > 0) {
                target.setAttribute('data-sh-acct', '1');
                return true;
              }
            }
            n = n.parentElement || (n.getRootNode() && n.getRootNode().host);
          }
          return false;
        """))
        if marked:
            loc = page.locator('[data-sh-acct="1"]')
            try:
                if loc.count() > 0:
                    return loc.first
            except Exception:
                pass
    return None


def collapse_account_dropdown(page):
    """点弹窗【内】的空白处，把账号下拉收起来。

    使用者特意强调：不能点弹窗外面 —— 点外面下拉会收回（弹窗也可能一起关掉）。
    所以这里点的是弹窗标题「共享视频」那一行，它在弹窗里、又不是任何控件。
    """
    title = _first_vis(page.get_by_text(SHARE_MODAL_TITLE, exact=True))
    if title is None:
        return False
    try:
        title.click(timeout=5000)
    except Exception:
        return False
    page.wait_for_timeout(800)
    return True


def confirm_share(page, timeout_seconds=30):
    """点「确认」，等弹窗关掉。"""
    btn = _first_vis(page.get_by_role("button", name=CONFIRM_BUTTON, exact=True))
    if btn is None:
        btn = _first_vis(page.get_by_text(CONFIRM_BUTTON, exact=True))
    if btn is None:
        raise ValueError(
            f"弹窗里没找到「{CONFIRM_BUTTON}」按钮。"
            f"\n当前可见按钮：{_visible_button_names(page)}"
        )
    robust_click(page, btn, timeout=8000)

    # 验证看结果：弹窗关掉才算共享提交了
    closed = wait_until(page, lambda: not share_modal_open(page),
                        timeout_seconds=timeout_seconds)
    if not closed:
        raise ValueError(
            f"点了「{CONFIRM_BUTTON}」但弹窗没关，共享可能没提交成功。"
            f"\n当前可见按钮：{_visible_button_names(page)}"
        )
    return True


# ---------------------------------------------------------------------------
# 分页
#
# 使用者：「假如超过一百条并且你也共享完前一百条…点击右下角的下一个页码，
# 然后回去再重复一遍全选然后共享的操作，直到没有多余的页码为止」。
#
# 换页之后勾选会清空（截图里第 2 页所有方框都是空的），所以每一页都要
# 重新全选一次。
# ---------------------------------------------------------------------------

FILTER_CLEAR = "清除"


def filter_active(page):
    """筛选条件还在不在。

    这是一道【安全闸】，不是可有可无的检查：
    翻页共享是「每页全选 -> 共享」的循环，一旦筛选没生效，列表就是【整个素材库】
    （使用者截图里是 68 页 × 100 条 ≈ 6800 条），循环下去会把全库共享给目标账号，
    而且很难收回。所以每一页动手之前都确认一次。

    判据：应用了筛选之后，搜索框旁边会出现「清除」（和「保存」）。
    """
    return _first_vis(page.get_by_text(FILTER_CLEAR, exact=True)) is not None


def _pager_numbers(page):
    """分页条上的页码：{"current": 当前页, "last": 能看到的最大页码}。读不出返回 None。

    探针实测（2026-09-04）分页条的真实结构：
        div.pager.pager--full                      文字 '12345'
          ├ ks-button-1-1-1g.pager__item             '1'  <- 当前页还带 pager__item--active
          ├ ks-button-1-1-1g.pager__item             '2' …
          ├ ks-icon-button-1-1-1g.pager__button      右边那个 > 箭头
          └ ks-select-1-1-1g.pager__select           每页条数

    第一版是「找页面上所有纯数字的小方块，取最靠下的那一排」，
    结果把表格里那些数值为 0 的单元格当成了页码，读出来是
    {current: None, last: 0, all: [0,0,0,0,0]} —— 于是 5 页的剧只共享了第 1 页
    就当作跑完了，而且一声不吭。分页读错在这里是【会丢数据】的错，
    所以现在只认 pager__item 这个类名，认不出来宁可返回 None 让上层报出来。
    """
    try:
        return page.evaluate(_deep(r"""
          const items = deepAll(document.documentElement).filter(e => {
            const cls = e.getAttribute('class') || '';
            if (!/(^|\s)pager__item(\s|$)/.test(cls)) return false;
            const t = (e.textContent || '').trim();
            if (!/^\d{1,4}$/.test(t)) return false;
            const r = e.getBoundingClientRect();
            return r.width > 0 && r.height > 0;
          });
          if (!items.length) return null;
          const vals = items.map(e => parseInt((e.textContent || '').trim(), 10));
          let cur = null;
          for (const e of items) {
            if (/pager__item--active/.test(e.getAttribute('class') || '')) {
              cur = parseInt((e.textContent || '').trim(), 10);
              break;
            }
          }
          return {current: cur, last: Math.max(...vals), all: vals};
        """))
    except Exception:
        return None


def current_page(page):
    info = _pager_numbers(page)
    if not info:
        return None
    return info.get("current")


def go_to_next_page(page, timeout_seconds=40):
    """翻到下一页。已经是最后一页返回 False。

    优先点【下一个页码】那个数字（使用者说的就是这个），点不到再退回右边那个
    「>」箭头。换完页要等列表重新加载完，而且勾选会被清空 —— 下一轮要重新全选。
    """
    info = _pager_numbers(page)
    if not info:
        return False
    cur = info.get("current")
    last = info.get("last")
    if cur is None or last is None or cur >= last:
        return False

    # 只在分页条【里面】点。不能全页面找文字是「2」的元素 ——
    # 这张表里到处都是 0/1/2 这样的数值单元格，随便点一个既翻不了页，
    # 还可能点进某个素材的详情页去。
    target = _pager_item(page, cur + 1)
    if target is not None:
        robust_click(page, target, timeout=6000)
    else:
        # 退路：点分页条右边那个「>」箭头
        nxt = _pager_next_arrow(page)
        if nxt is None:
            return False
        robust_click(page, nxt, timeout=6000)

    ok = wait_until(page, lambda: current_page(page) == cur + 1,
                    timeout_seconds=timeout_seconds)
    if not ok:
        return False
    _wait_rows_settled(page)
    print(f"      [素材库] 翻到第 {cur + 1}/{last} 页", flush=True)
    return True


def _pager_item(page, number):
    """分页条上写着这个数字的那个页码按钮（ks-button.pager__item）。"""
    marked = page.evaluate(_deep_el(r"""
      deepClearMark('data-sh-page');
      const want = String(el);
      const hit = deepAll(document.documentElement).find(e => {
        const cls = e.getAttribute('class') || '';
        if (!/(^|\s)pager__item(\s|$)/.test(cls)) return false;
        if ((e.textContent || '').trim() !== want) return false;
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (!hit) return false;
      hit.setAttribute('data-sh-page', '1');
      return true;
    """), str(number))
    if not marked:
        return None
    loc = page.locator('[data-sh-page="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def _pager_next_arrow(page):
    """分页条右边那个「>」按钮（ks-icon-button.pager__button，里面是 chevron-right）。"""
    marked = page.evaluate(_deep(r"""
      deepClearMark('data-sh-next');
      const hit = deepAll(document.documentElement).find(e => {
        const cls = e.getAttribute('class') || '';
        if (!/(^|\s)pager__button(\s|$)/.test(cls)) return false;
        if (!deepAll(e).some(c => /chevron-right/.test(c.tagName.toLowerCase()
                                   + ' ' + (c.getAttribute('class') || '')))) return false;
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0;
      });
      if (!hit) return false;
      hit.setAttribute('data-sh-next', '1');
      return true;
    """))
    if not marked:
        return None
    loc = page.locator('[data-sh-next="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


def _iter_visible(loc, limit=20):
    v = _vis(loc)
    try:
        n = v.count()
    except Exception:
        return
    for i in range(min(n, limit)):
        yield v.nth(i)


def total_pages(page):
    info = _pager_numbers(page)
    return None if not info else info.get("last")
