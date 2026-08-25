"""视口和滚动 —— 「把目标滚到看得见的位置」这件事的唯一实现。

原来这套代码长在 src/drama/pages/adgroup_page.py 里。加「短剧端计划」这个模式时
它同样要用（选优化位置的三个选项显示不全时要往下滑一点），与其复制一份，
不如提到这里共用 —— 这几个函数是踩了好几轮坑才对的，两份一定会走散。

drama 那边保留同名的私有别名（_viewport_h 等），所以它的调用点和已有的测试
一个字都不用改。
"""

import time

def viewport_h(page):
    """视口【真实】高度。

    必须问浏览器要 window.innerHeight，不能用 page.viewport_size ——
    后者返回的是【启动时要求的】值（drama/main.py 里写的 1600x1000），
    而 headless=False 时窗口能有多高由屏幕说话：使用者的屏幕是 1470x956（CSS 像素），
    减掉标签栏/地址栏/书签栏和程序坞，真实视口只有 700 上下。
    拿 1000 去算「舒适区」，bottom_safe = 1000-230 = 770 已经在屏幕外了，
    于是一个根本看不见的元素也会被判成「到位」。
    """
    try:
        h = page.evaluate("() => window.innerHeight")
        if isinstance(h, (int, float)) and h > 200:
            return int(h)
    except Exception:
        pass
    try:
        return page.viewport_size["height"]
    except Exception:
        return 1000


# 量一个元素在视口里的位置：{y, h, tag}。量不到返回 null。
#
# 自己没有盒子时往上找祖先（shadow DOM 里的 <slot> 就没有，slot 自身不渲染），
# 但要求那个祖先【不比视口高】。这一条是【防御】，不是已确诊的病因：
# 只要求「盒子非零」的话，理论上可能一路走到几千像素高的表单容器上，
# 那时候「把它的中心滚到视口中间」等于滚到表单中段，目标反而被滚出屏幕。
# 我用本地 fixture 试过复现这一幕（shadow DOM + 3200px 容器 + 吸顶吸底），
# 复现【不出来】——占位文字那个 span 自己就有盒子，老写法也是一次到位。
# 所以这里如实记一笔：这条限制加着没坏处，但它不是「滚轮上下滑十几秒」的答案。
MEASURE_JS = """
(el, vh) => {
  let n = el;
  for (let k = 0; k < 8 && n; k++) {
    const r = n.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.height <= vh) {
      return {y: r.y, h: r.height, tag: (n.tagName || '').toLowerCase()};
    }
    n = n.parentElement;      // slot 之类自身没有盒子，往上找
  }
  return null;
}
"""

# 同样的「找一个大小合适的盒子」逻辑，找到就让浏览器自己滚过去。
#
# behavior:'instant' 是特意写的：页面若设了 CSS scroll-behavior: smooth，
# scrollIntoView 会做动画，而调用方只等 350ms，量到的就是【动画中途】的位置，
# 于是修正量算错、下一轮再修正——这是滚轮来回滑的一种可能来源。
# 写死 instant 就不用赌页面的 CSS。
SCROLL_CENTER_JS = """
(el, vh) => {
  let n = el;
  for (let k = 0; k < 8 && n; k++) {
    const r = n.getBoundingClientRect();
    if (r.width > 0 && r.height > 0 && r.height <= vh) {
      n.scrollIntoView({block: 'center', inline: 'nearest', behavior: 'instant'});
      return true;
    }
    n = n.parentElement;
  }
  return false;
}
"""

# 补位移：滚最近那个可滚动祖先。
#
# 两点故意的写法：
#   * 不用 mouse.wheel —— 滚轮滚的是【鼠标底下那个容器】，鼠标停在哪、哪一层把
#     滚动吃掉了都不确定；老写法为此还得先 mouse.move(800,500) 赌一把。
#   * 用 scrollTo({behavior:'instant'}) 而不是 scrollTop += dy —— 页面设了
#     scroll-behavior: smooth 时，直接改 scrollTop 在 Chrome 里也会走动画。
SCROLL_BY_JS = """
(el, dy) => {
  let n = el;
  while (n) {
    const st = getComputedStyle(n);
    if (n.scrollHeight > n.clientHeight + 4 && /auto|scroll/.test(st.overflowY)) {
      n.scrollTo({top: n.scrollTop + dy, behavior: 'instant'});
      return;
    }
    n = n.parentElement;
  }
  window.scrollTo({top: window.scrollY + dy, behavior: 'instant'});
}
"""


def on_screen(page, locator):
    """元素现在是不是【真的在视口里】。

    和 _first_visible 分工要分清：那个只看盒子非零，屏幕外的元素照样算「可见」；
    这个才是「看得见」。所以「已经在屏幕上就别再滚」要用本函数判断。
    """
    try:
        m = locator.evaluate(MEASURE_JS, viewport_h(page))
    except Exception:
        return False
    if not m:
        return False
    vh = viewport_h(page)
    center = m["y"] + m["h"] / 2
    return 120 <= center <= vh - 150


def scroll_into_comfortable_view(page, locator, tries=2, label=""):
    """把元素滚进视口中部：一次算准，不做滚轮试探。

    改这个函数的起因：使用者两次反馈同一个现象——选 TikTok Mini、选价值类型时
    【滚轮一直上下滑动，十几秒才定位到】。

    老写法是「scrollIntoView 之后接一个 14 轮的 mouse.wheel 修正循环」，每轮等
    350ms、走 JS 兜底那支还要再等 400ms。所以单次调用最坏就是 5～6 秒，而选 Mini
    和选价值类型外面都套着 3 轮重试 —— 一步花掉十几秒完全对得上。

    我没能确诊【为什么它收敛不了】：拿本地 fixture 复现过 shadow DOM 占位文字、
    3200px 高的表单容器、吸顶吸底、CSS smooth 滚动，四种情况下老写法都是 421ms
    一次到位。所以这里不写死一个病因，改成让它【不可能慢】，并且把量到的位置打进
    日志——下次真机上还慢，日志会直接说出是哪一步、y 在怎么跳。

    现在只做两件事，最坏一秒出头：
      ① scrollIntoView({block:'center', behavior:'instant'})，浏览器一次算准
      ② 只有被顶部导航 / 底部操作栏挡住时，用 JS 补最多 tries 次位移

    顺手修掉的一个真问题：舒适区以前按 page.viewport_size 算，那是【要求的】视口
    高度，不是真的（见 _viewport_h）。1000 减 230 得 770，而真实视口只有 700 上下，
    于是屏幕外的元素也会被判「到位」。

    还留着的老经验：
      * bounding_box() 对 shadow DOM 的 <slot> 返回 None，要往上找有盒子的祖先
      * _first_visible 认为屏幕外的元素也「可见」，所以不能写成「找不到才滚」；
        要判断「在不在屏幕上」用 _on_screen
    """
    vh = viewport_h(page)
    top_safe, bottom_safe = 170, vh - 200      # 避开顶部导航和底部固定操作栏
    target_y = (top_safe + bottom_safe) // 2
    t0 = time.monotonic()
    trace = []

    def measure():
        try:
            return locator.evaluate(MEASURE_JS, vh)
        except Exception:
            return None

    def in_band(m):
        center = m["y"] + m["h"] / 2
        return top_safe <= center <= bottom_safe

    def done(ok):
        if label:
            ys = "→".join("?" if y is None else str(y) for y in trace) or "?"
            ms = int((time.monotonic() - t0) * 1000)
            print(f"          [{label}] 定位用了 {ms}ms，到位={ok}（y: {ys}）",
                  flush=True)
        return ok

    try:
        locator.evaluate(SCROLL_CENTER_JS, vh)
    except Exception:
        pass
    page.wait_for_timeout(350)

    m = measure()
    trace.append(None if not m else round(m["y"]))
    if m and in_band(m):
        return done(True)

    for _ in range(max(1, int(tries))):
        m = measure()
        if not m:
            break
        if in_band(m):
            return done(True)
        dy = int(m["y"] + m["h"] / 2 - target_y)
        if abs(dy) < 8:
            break
        try:
            locator.evaluate(SCROLL_BY_JS, dy)
        except Exception:
            break
        page.wait_for_timeout(300)
        m2 = measure()
        trace.append(None if not m2 else round(m2["y"]))

    m = measure()
    return done(bool(m and in_band(m)))


