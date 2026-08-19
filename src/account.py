"""登录状态、广告主权限、换账号 —— 小游戏和短剧共用。

为什么单独写这个文件：这套工具原来只有作者一个人用，浏览器 profile 里永远是同一份
登录态、表格里永远是同一批自己有权限的广告主 ID，于是代码里从来没区分过下面三件事——

    ① profile 里根本没登录
    ② 登录了，但这个账号看不到表格里那个广告主（TikTok 显示「无权限操作」）
    ③ 登录了、也有权限，只是页面还没加载出来

它们原来全都表现成同一句话：「等了 45 秒没看到创建广告按钮」，后面并列三种猜测。
自己用的时候几乎只可能是 ③，所以够用；换成别人用之后 ① ② 才是常态——
新用户拿到的是一个空 profile（profile 目录在 .gitignore 里，不会跟着代码走），
表格里填的是他自己 BC 下的广告主 ID。这时候还报那句含糊的话，使用者只会看到
「无权限操作」，不知道该去登录、该换账号，还是该改表格。

所以这里把三件事拆开判断，并且给出【下一步该做什么】的提示。

另外收了两件同源的事：
  * 判断浏览器是不是被人关掉了（原来会甩一个 Playwright 的 TargetClosedError 堆栈）
  * 换账号 —— 把 profile 目录挪走，下次跑就是全新登录
"""

import shutil

# TikTok 广告后台的几个固定地址
DASHBOARD_URL = "https://ads.tiktok.com/i18n/dashboard"
LOGIN_URL = "https://ads.tiktok.com/i18n/login"

# 判断「有没有登录」只认一件事：**地址最后停没停在登录页**。
#
# 2026-08-19 用一个全新的空 profile（必定未登录）实测，三个地址无一例外：
#     /i18n/home                 ->  /i18n/login?redirect=…%2Fi18n%2Fhome
#     /i18n/login                ->  /i18n/login
#     /i18n/dashboard?aadvid=…   ->  /i18n/login/?redirect=…%2Fdashboard%3Faadvid…
# 而登录之后 dashboard 就停在 dashboard 自己（同一天实测）。
#
# 【不要】改成用「页面上有没有 .ac-lang-avater__lang-btn（右上角语言按钮）」判断。
# 同一次实测里，登录页上也有这个按钮而且可见（count=2、可见 1 个）——拿它当判据会把
# 「没登录」判成「已登录」，然后一路跑到后面某一步莫名其妙地超时。
# 这个选择器只能用来切语言（set_language.py 的用途），不能用来判断登录状态。
LANG_BUTTON_CSS = ".ac-lang-avater__lang-btn"

# 停在这些地址上就等于没登录（登录流程中途可能跳到 passport / oauth 域）
_LOGIN_URL_MARKERS = ("/i18n/login", "/passport", "/oauth", "/signup")

# 后台真正加载出来才会有的按钮，顺带把界面语言也读出来
_CREATE_AD = (("创建广告", "zh"), ("Create ad", "en"))

# TikTok 没权限时给的提示。使用者报的原话就是「无权限操作」。
# 中英文都列上：新用户的账号很可能一上来就是英文界面，而权限判断发生在切语言之前。
_NO_PERMISSION_TEXTS = (
    "无权限操作",
    "无权限",
    "没有权限",
    "无权访问",
    "暂无权限",
    "No permission",
    "Permission denied",
    "Access denied",
    "don't have permission",
    "do not have access",
)

# 登录页上才有的东西
_LOGIN_PAGE_TEXTS = ("登录", "Log in", "Sign in", "登入")


# ---------------------------------------------------------------- 浏览器被关掉

_CLOSED_MARKERS = (
    "target page, context or browser has been closed",
    "browser has been closed",
    "target closed",
    "connection closed",
    "browser closed",
)


class BrowserClosedError(RuntimeError):
    """浏览器窗口被关掉了（多半是使用者手动关的）。

    单独一个类型，是为了让上层能把它翻译成一句人话，而不是甩一整个 Playwright
    堆栈。使用者看到 `TargetClosedError: Locator.count` 那种东西只会以为程序坏了，
    实际上就是窗口被关了而已。
    """


def is_browser_closed_error(exc):
    """判断一个异常是不是「浏览器/页面已经关了」。

    不 import playwright 的私有异常类（_impl._errors.TargetClosedError 不在公开
    API 里，版本一变就 ImportError），改成认类名 + 认消息，两条都能命中。
    """
    if isinstance(exc, BrowserClosedError):
        return True
    if type(exc).__name__ in ("TargetClosedError", "TargetClosedException"):
        return True
    msg = str(exc).lower()
    return any(m in msg for m in _CLOSED_MARKERS)


def _guard(fn, default=None):
    """跑一个可能碰页面的小函数；页面已经关掉就抛 BrowserClosedError。

    其余异常一律吞掉返回 default —— 这个文件里的探测函数本来就是「看一眼页面上
    有没有某个东西」，元素不在、还在导航中都属于正常情况，不该往上抛。
    但「浏览器关了」必须往上抛：继续轮询下去只会把同一个错误重复 90 次。
    """
    try:
        return fn()
    except Exception as e:
        if is_browser_closed_error(e):
            raise BrowserClosedError(
                "浏览器窗口已经关掉了，脚本没法继续。跑的过程中请不要关那个窗口。"
            ) from e
        return default


# ---------------------------------------------------------------- 页面状态探测


def _any_visible_text(page, needles, limit=4):
    """页面上有没有可见的、包含 needles 里任一片段的文字。命中就返回那个片段。

    用 Playwright 的 get_by_text 而不是 document.querySelectorAll：
    后者穿不透 shadow DOM，这个后台大量用 shadow DOM（项目里已经踩过一次）。
    """
    for needle in needles:
        def probe(needle=needle):
            loc = page.get_by_text(needle, exact=False)
            for i in range(min(loc.count(), limit)):
                if loc.nth(i).is_visible():
                    return needle
            return None

        hit = _guard(probe)
        if hit:
            return hit
    return None


def ui_language(page):
    """后台界面是中文还是英文；都没加载出来返回 None。"""
    for name, lang in _CREATE_AD:
        def probe(name=name):
            btn = page.get_by_role("button", name=name)
            for i in range(min(btn.count(), 6)):
                if btn.nth(i).is_visible():
                    return True
            return False

        if _guard(probe, False):
            return lang
    return None


def on_login_page(url):
    """这个地址算不算「登录页」。见 _LOGIN_URL_MARKERS 上面那段实测记录。"""
    u = (url or "").lower()
    return any(m in u for m in _LOGIN_URL_MARKERS)


def is_logged_in(page, advertiser_id, timeout_seconds=60):
    """这个 profile 登没登录。**必须给一个广告主 ID**，原因见下。

    2026-08-19 实测（逐 2 秒采样，登录/未登录两个 profile 各跑一遍）：

        地址                          未登录            已登录
        /i18n/home                    跳登录页          跳登录页   ← 一样，没法用
        /i18n/dashboard （不带 ID）    跳登录页          跳登录页   ← 一样，没法用
        /i18n/dashboard?aadvid=<ID>   跳登录页          正常打开   ← 只有这个能分辨

    也就是说 TikTok 【没有】一个「与广告主无关的登录状态页」：不带 aadvid 的地址
    登录了也照样踢回登录页（真实 profile 上 t=4s 还渲染着中文后台，t=6s 就跳走了）。
    所以判断登录必须挑一个具体广告主去开，没有 ID 就无从判断。

    这也解释了一个很容易吓到人的现象：手动打开 ads.tiktok.com 看到登录界面，
    不代表登录态没了，可能只是那个地址本来就要带 aadvid。
    """
    return check_advertiser_access(
        page, advertiser_id, timeout_seconds=timeout_seconds
    ).get("state") != "logged_out"


def wait_for_login(page, timeout_seconds=600, on_progress=None, off_login_seconds=6):
    """打开登录页，被动等使用者登录完成。登录成功返回命中的标志，超时返回 None。

    关键是【不导航】：使用者正在这个窗口里输密码或者扫码，中途 goto 一下就把他
    打断了。所以只反复看当前页面上有没有「已经登进去」的痕迹。

    三个标志，任一命中即成功：
      * 后台的「创建广告 / Create ad」按钮出现（进到 Ads Manager 了）
      * 「推广系列 / Campaigns」出现
      * 地址【离开登录页并持续 off_login_seconds 秒】——登录成功后 TikTok 会从
        /i18n/login 跳到 /i18n/home（账户选择页），那个页面上没有前两个标志，
        只能靠地址判断。要求持续几秒是因为登录流程中间会在几个域之间来回跳。

    中英文都收：别人的账号一上来很可能是英文界面，而这一步发生在切语言之前，
    只认中文会永远等不到。

    【不要】把「页面上有 .ac-lang-avater__lang-btn」加回成功标志。实测登录页上
    也有那个按钮而且可见，加回去等于窗口一打开就报「登录成功」——
    src/drama/login_setup.py 的老注释里记的「窗口一闪就没了」就是这个坑的另一种版本。
    """
    import time

    _guard(lambda: page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60000))

    deadline = time.monotonic() + timeout_seconds
    last_report = 0
    off_since = None
    while time.monotonic() < deadline:
        lang = ui_language(page)
        if lang:
            return "创建广告按钮" if lang == "zh" else "Create ad 按钮"

        hit = _any_visible_text(page, ("推广系列", "Campaigns"))
        if hit:
            return hit

        cur = _guard(lambda: page.url, "") or ""
        if cur and not on_login_page(cur):
            if off_since is None:
                off_since = time.monotonic()
            elif time.monotonic() - off_since >= off_login_seconds:
                return "已离开登录页"
        else:
            off_since = None

        waited = int(timeout_seconds - (deadline - time.monotonic()))
        if on_progress and waited - last_report >= 15:
            last_report = waited
            on_progress(waited, cur)
        _guard(lambda: page.wait_for_timeout(2000))
    return None


def check_advertiser_access(page, advertiser_id, timeout_seconds=60):
    """打开某个广告主的后台，判断当前登录账号能不能用它。

    返回 {"state": ..., "url": ..., "lang": ..., "seen": ...}，state 取值：

        "ok"         后台正常打开了（lang 里是 'zh' 或 'en'）
        "forbidden"  登录了，但这个账号没有这个广告主的权限
        "logged_out" 压根没登录
        "unknown"    等到超时也没看出是哪种，seen 里带上页面上能读到的文字

    为什么必须区分：这三种情况使用者要做的事完全不同——去登录 / 换个账号登录 /
    改表格里的 ID / 单纯再等等。原来的代码把它们并成一句话，等于什么也没说。
    """
    import time

    url = f"{DASHBOARD_URL}?aadvid={advertiser_id}"
    _guard(lambda: page.goto(url, wait_until="domcontentloaded", timeout=60000))

    # 「没登录」和「没权限」在页面上长得几乎一样，而且出现的先后顺序会骗人：
    # 2026-08-19 实测，未登录时 dashboard 会先闪一段 "don't have permission"
    # （t≈2s），过一两秒才跳去登录页（t≈4s）。谁先看到就信谁的话，就会把
    # 「没登录」判成「没权限」——两者要做的事完全不同（一个去登录，一个换账号或
    # 改表格），判错等于把人指到反方向。
    #
    # 所以两种否定结论都要求【持续一段时间】才作数，而且登录页优先：
    #   看到登录页  -> 作废刚才的无权限计时（跳转还没走完）
    #   看到无权限  -> 再盯 FORBIDDEN_HOLD 秒，期间没跳去登录页，才算真的没权限
    LOGIN_HOLD = 8
    FORBIDDEN_HOLD = 15

    login_since = None
    forbidden_since = None
    forbidden_seen = None
    deadline = time.monotonic() + timeout_seconds

    while time.monotonic() < deadline:
        lang = ui_language(page)
        if lang:
            # 已知的漏网情形（2026-08-19 实测）：拿一个【根本不存在】的广告主 ID
            # 去开 dashboard，TikTok 照样把壳渲染出来，「创建广告」按钮也在，
            # 这里会判成 ok。所以 ok 的含义是「后台开起来了」，不等于
            # 「这个 ID 一定有效且有权限」——真正填错 ID 还是会在后面某一步炸。
            # 想彻底堵上得看接口返回（实测无权限时接口返 code 40002「权限错误」），
            # 但那个码在【没登录】时也一样会返，光靠它分不开两种情况，
            # 而误报「没权限」会把能跑的账号直接挡下来，比漏报更糟，所以先不用。
            return {"state": "ok", "lang": lang,
                    "url": _guard(lambda: page.url, "") or ""}

        cur = _guard(lambda: page.url, "") or ""

        if cur and on_login_page(cur):
            forbidden_since = None
            if login_since is None:
                login_since = time.monotonic()
            elif time.monotonic() - login_since >= LOGIN_HOLD:
                return {"state": "logged_out", "lang": None, "url": cur}
        else:
            login_since = None
            hit = "forbidden" if "forbidden" in cur else _any_visible_text(
                page, _NO_PERMISSION_TEXTS
            )
            if hit:
                forbidden_seen = hit
                if forbidden_since is None:
                    forbidden_since = time.monotonic()
                elif time.monotonic() - forbidden_since >= FORBIDDEN_HOLD:
                    return {"state": "forbidden", "lang": None,
                            "url": cur, "seen": forbidden_seen}
            else:
                forbidden_since = None

        _guard(lambda: page.wait_for_timeout(500))

    cur = _guard(lambda: page.url, "") or ""
    if cur and on_login_page(cur):
        return {"state": "logged_out", "lang": None, "url": cur}
    if forbidden_seen:
        return {"state": "forbidden", "lang": None, "url": cur,
                "seen": forbidden_seen}
    return {
        "state": "unknown",
        "lang": None,
        "url": cur,
        "seen": _visible_snippets(page),
    }


def _visible_snippets(page, limit=25):
    """页面上能读到的可见短文字，用来在 unknown 时给人一点线索。

    穿不透 shadow DOM，所以只当参考、不当判据 —— 真正的判断都走 get_by_text。
    """
    def probe():
        return page.evaluate(
            """(n) => {
              const out = [];
              for (const el of document.querySelectorAll('*')) {
                const r = el.getBoundingClientRect();
                if (r.width <= 0 || r.height <= 0) continue;
                const t = Array.from(el.childNodes).filter(x => x.nodeType === 3)
                  .map(x => x.textContent.trim()).join('').trim();
                if (t && t.length <= 40) out.push(t);
              }
              return [...new Set(out)].slice(0, n);
            }""",
            limit,
        )

    return _guard(probe, []) or []


def describe_access(result, advertiser_id, mode_label="", login_hint=True):
    """把 check_advertiser_access 的结果翻成一句能照着做的话。"""
    state = result.get("state")
    who = f"广告主 {advertiser_id}"
    where = f"（{mode_label}）" if mode_label else ""

    if state == "ok":
        return f"{who} 可以正常打开{where}。"

    if state == "logged_out":
        msg = f"浏览器里还没有登录 TikTok 广告后台{where}，所以打不开{who}。"
        if login_hint:
            msg += "\n请先在网页上点【登录 / 换账号】，用你自己的 BC 账号登录，再重新跑。"
        return msg

    if state == "forbidden":
        seen = result.get("seen")
        msg = (
            f"当前登录的账号没有{who}的权限"
            + (f"（页面上写着「{seen}」）" if seen else "")
            + "。\n可能是：①表格里的 Advertiser ID 填错了；"
            "②这个广告主不在你登录的那个 BC 下面；"
            "③你的 BC 账号还没被授权到这个广告主。"
        )
        if login_hint:
            msg += "\n确认 ID 没错的话，点【登录 / 换账号】换成有权限的账号再跑。"
        return msg

    seen = result.get("seen") or []
    return (
        f"打开{who}的后台之后，既没看到「创建广告」按钮，也没看到无权限提示，"
        f"页面可能没加载出来。\n当前地址: {(result.get('url') or '')[:120]}\n"
        f"页面上能读到的文字: {seen[:15]}"
    )


# ---------------------------------------------------------------- 换账号


def profile_has_login(profile_dir):
    """粗判这个 profile 目录里有没有登录过的痕迹。

    只是给界面显示用的弱判断（Cookies 文件在不在），不能替代 is_logged_in ——
    登录过但已经过期的 profile 这里也会返回 True。真正要确认得开浏览器看。
    """
    from pathlib import Path

    p = Path(profile_dir)
    return (p / "Default" / "Cookies").exists() or (p / "Default" / "Network" /
                                                    "Cookies").exists()


def clear_profile(profile_dir):
    """把当前登录态挪走，下次开浏览器就是全新未登录状态（= 换账号）。

    挪走而不是直接删：留一份上一次的，万一新账号登不进去还能改回来。
    只留一份（挪之前先把旧备份删掉），不然反复换账号会堆一堆几百 MB 的目录。

    调用前必须确认【没有浏览器正在用这个 profile】—— Chromium 会锁住 user_data_dir，
    跑到一半换账号会把正在跑的那次搞坏。app.py 里用 run_state 挡了这一层。
    """
    from pathlib import Path

    p = Path(profile_dir)
    backup = p.with_name(p.name + "__previous")
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)
    if p.exists():
        p.rename(backup)
    p.mkdir(parents=True, exist_ok=True)
    return str(backup)
