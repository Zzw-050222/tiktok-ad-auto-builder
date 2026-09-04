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
ACCOUNT_SEARCH_PLACEHOLDER = "按广告账号名称或 ID 搜索"
CONFIRM_BUTTON = "确认"


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
        marked = el.evaluate("""el => {
          document.querySelectorAll('[data-sh-opt]').forEach(
            e => e.removeAttribute('data-sh-opt'));
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            const r = n.getBoundingClientRect();
            const st = getComputedStyle(n);
            if (r.width > 120 && r.height >= 24 && r.height < 140
                && st.pointerEvents !== 'none') {
              n.setAttribute('data-sh-opt', '1');
              return true;
            }
            n = n.parentElement;
          }
          return false;
        }""")
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
    """点表头「视频」左边那个小方框 = 全选当前页。

    验证看结果：全选之后「共享」按钮会从禁用变可点。
    """
    cb = wait_until(page, lambda: _header_checkbox(page), timeout_seconds=timeout_seconds)
    if cb is None:
        raise ValueError("没找到表头「视频」左边的全选方框")
    robust_click(page, cb, timeout=8000)
    page.wait_for_timeout(1200)
    return True


def _header_checkbox(page):
    """表头那一行里、「视频」左边的复选框。

    按结构找：先定位表头里的「视频」两个字，再在它所在的表头行里找复选框。
    不能全页面找复选框 —— 每一行数据前面都有一个。
    """
    marked = page.evaluate("""() => {
      document.querySelectorAll('[data-sh-all]').forEach(
        e => e.removeAttribute('data-sh-all'));
      // 找到文字恰好是「视频」的那个表头单元格
      const all = [...document.querySelectorAll('*')];
      for (const el of all) {
        if (el.children.length) continue;
        if ((el.textContent || '').trim() !== '视频') continue;
        const r = el.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0) continue;
        // 往上找到整行，再在行里找复选框
        let row = el;
        for (let k = 0; k < 6 && row; k++) {
          row = row.parentElement;
          if (!row) break;
          const rr = row.getBoundingClientRect();
          if (rr.width < 300) continue;
          const cb = row.querySelector(
            'input[type="checkbox"], [role="checkbox"], [class*="checkbox" i]');
          if (cb) {
            const cr = cb.getBoundingClientRect();
            if (cr.width > 0 && cr.height > 0) {
              cb.setAttribute('data-sh-all', '1');
              return true;
            }
          }
        }
      }
      return false;
    }""")
    if not marked:
        return None
    loc = page.locator('[data-sh-all="1"]')
    try:
        return loc.first if loc.count() > 0 else None
    except Exception:
        return None


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


def _account_search_box(page):
    return _first_vis(page.get_by_placeholder(ACCOUNT_SEARCH_PLACEHOLDER))


def scroll_modal_to_account_section(page, timeout_seconds=30):
    """在弹窗【里面】往下滚，直到「与选定的广告账号共享」那一块露出来。

    使用者原话：「你需要在这个小窗口里滚轮滚到底就出现按名称搜索框」。
    滚的是弹窗内部的滚动容器，不是整个页面 —— 所以用 scrollTop 直接推那个容器，
    不用 mouse.wheel（滚轮滚的是鼠标底下那层，不确定是哪个）。
    """
    for _ in range(int(timeout_seconds * 2)):
        if _account_search_box(page) is not None:
            return True
        page.evaluate("""() => {
          // 找到弹窗里那个能滚的容器，往下推
          const title = [...document.querySelectorAll('*')].find(
            e => !e.children.length && (e.textContent || '').trim() === '共享视频');
          let n = title;
          for (let k = 0; k < 10 && n; k++) {
            n = n.parentElement;
            if (!n) break;
            const st = getComputedStyle(n);
            if (n.scrollHeight > n.clientHeight + 4 && /auto|scroll/.test(st.overflowY)) {
              n.scrollTop = n.scrollHeight;
              return;
            }
          }
          // 退路：弹窗里所有可滚的都推到底
          document.querySelectorAll('*').forEach(e => {
            const st = getComputedStyle(e);
            if (e.scrollHeight > e.clientHeight + 4 && /auto|scroll/.test(st.overflowY)) {
              e.scrollTop = e.scrollHeight;
            }
          });
        }""")
        page.wait_for_timeout(500)
    return _account_search_box(page) is not None


def add_target_accounts(page, account_names, timeout_seconds=25):
    """在弹窗里把要共享到的账号一个个勾上。返回 (勾上的名字列表, 警告列表)。

    使用者演示的做法，一个字都别改：
        输入账号名 -> 点搜索结果左边的方框 -> 【把输入的字删掉】-> 输下一个 -> 再勾
    删干净很关键：不删的话第二次搜索是在上一次的词后面接着打，搜不到东西。
    """
    picked, warnings = [], []
    box = _account_search_box(page)
    if box is None:
        raise ValueError(
            f"弹窗里没找到账号搜索框（占位文字「{ACCOUNT_SEARCH_PLACEHOLDER}」）。"
            "可能是没滚到底。"
        )

    for name in account_names:
        name = str(name).strip()
        if not name:
            continue
        box = _account_search_box(page)
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
        robust_click(page, row, timeout=8000)
        page.wait_for_timeout(900)
        picked.append(name)
        print(f"      [共享] 已勾选目标账号「{name}」", flush=True)

    return picked, warnings


def _account_result_row(page, name):
    """账号搜索结果里那一行的【复选框】。

    从账号名往上走到行，再取行里的复选框 —— 直接点名字未必落在可点区域上。
    """
    cands = _vis(page.get_by_text(name, exact=False))
    try:
        n = cands.count()
    except Exception:
        return None
    for i in range(min(n, 12)):
        el = cands.nth(i)
        marked = el.evaluate("""el => {
          document.querySelectorAll('[data-sh-acct]').forEach(
            e => e.removeAttribute('data-sh-acct'));
          let n = el;
          for (let k = 0; k < 6 && n; k++) {
            const r = n.getBoundingClientRect();
            if (r.width > 150 && r.height >= 24 && r.height < 120) {
              const cb = n.querySelector(
                'input[type="checkbox"], [role="checkbox"], [class*="checkbox" i]');
              const target = cb || n;
              const tr = target.getBoundingClientRect();
              if (tr.width > 0 && tr.height > 0) {
                target.setAttribute('data-sh-acct', '1');
                return true;
              }
            }
            n = n.parentElement;
          }
          return false;
        }""")
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
