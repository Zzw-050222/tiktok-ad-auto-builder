"""网页版入口：上传表格 -> 选模式 -> 搭建。

两种模式共用这一套界面和进度显示，区别只在于用哪个 builder、哪个浏览器 profile：

  minigame  小游戏        src/builder.py          browser_profile
  drama     短剧商品库     src/drama/builder.py    browser_profile_drama

两个 profile 必须分开：它们是两次独立的登录会话，混用会互相顶掉登录状态。
"""

import threading
import traceback

from flask import Flask, jsonify, render_template, request
from playwright.sync_api import sync_playwright

from src.account import (
    check_advertiser_access,
    clear_profile,
    describe_access,
    is_browser_closed_error,
    profile_has_login,
    wait_for_login,
)
from src.builder import build_campaign_group
from src.config import (
    ACCEPT_LANGUAGE,
    BROWSER_PROFILE_DIR,
    LOCALE,
    UPLOADS_DIR,
)
from src.drama.builder import build_drama_campaign
from src.drama.config import DRAMA_BROWSER_PROFILE_DIR
from src.drama.series_lookup import load_series_map, resolve_series_from_campaign_name
from src.excel_loader import group_by_campaign, load_rows

app = Flask(__name__)

UPLOAD_PATH = UPLOADS_DIR / "latest.xlsx"

# 不要用 5000：macOS 的「隔空播放接收器」（ControlCenter）常驻占着 *:5000，
# Flask 起不来会报 Address already in use，而浏览器可能连到别的残留进程上，
# 看到的是旧页面——排查起来非常费劲。
PORT = 5050

MODES = {
    "minigame": {
        "label": "小游戏",
        "profile": BROWSER_PROFILE_DIR,
    },
    "drama": {
        "label": "短剧商品库",
        "profile": DRAMA_BROWSER_PROFILE_DIR,
    },
}

state_lock = threading.Lock()
run_state = {
    "status": "idle",  # idle | running | done | error
    "mode": None,
    "total": 0,
    "completed": 0,
    "current": None,
    "results": [],
    "fatal_error": None,
}

# 登录窗口是另一条长时间运行的线程，状态单独放。
# 必须和搭建互斥：Chromium 会锁住 user_data_dir，两边同时开同一个 profile 会打架。
login_state = {
    "status": "idle",  # idle | waiting | done | error
    "mode": None,
    "message": "",
}


def _reset_state():
    run_state.update(
        status="idle",
        mode=None,
        total=0,
        completed=0,
        current=None,
        results=[],
        fatal_error=None,
    )


def _busy_reason():
    """现在有没有别的事情正占着浏览器 profile。没有就返回 None。"""
    with state_lock:
        if run_state["status"] == "running":
            return "正在搭建，等它跑完再操作账号"
        if login_state["status"] == "waiting":
            return "登录窗口还开着，先在那个窗口里登录完（或者关掉它）"
    return None


def _preflight_drama(groups):
    """跑之前先检查每个计划名能不能匹配到短剧ID。

    匹配不到的计划一定会在「特定剧集」那步失败，与其跑到一半才炸，不如在上传时
    就告诉使用者是哪几个计划、名字对不上。
    """
    try:
        name_to_id, _ = load_series_map()
    except Exception as e:
        return [f"读不到「商品库-剧目」表: {e}"]

    # 注意：匹配不上时 resolve_series_from_campaign_name 是【抛异常】而不是返回空值，
    # 必须 try 住。第一版按「返回空值」写，预检自己先崩了。
    unmatched = []
    for (_advertiser_id, campaign_name), _rows in groups:
        try:
            _name, series_id = resolve_series_from_campaign_name(
                str(campaign_name), name_to_id
            )
        except Exception:
            series_id = None
        if not series_id:
            unmatched.append(str(campaign_name))
    if unmatched:
        return [
            f"这些计划名在「商品库-剧目」表里匹配不到剧目，跑到「特定剧集」那步会失败："
            + "、".join(unmatched)
        ]
    return []


def _log_result(mode, publish, campaign_name, result):
    """把每个计划的结果追加到 logs/web_build.txt。

    网页版原来什么都不落盘，报错只在启动它的终端里滚过去——排查时只能靠使用者
    截图，截图太大还传不过去。命令行入口一直有 drama_build.txt，网页版也该有。
    """
    from src.config import LOGS_DIR

    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(str(LOGS_DIR / "web_build.txt"), "a", encoding="utf-8") as f:
            f.write(f"\n=== {campaign_name} ===\n")
            f.write(f"模式={mode} 发布={'是' if publish else '否'}\n")
            f.write("结果=" + ("成功" if result.get("success") else "失败") + "\n")
            if result.get("error"):
                f.write(f"失败原因: {result['error']}\n")
            for w in result.get("warnings") or []:
                f.write(f"  ! {w}\n")
    except Exception:
        pass


def _advertiser_ids(groups):
    """表格里出现过的所有广告主 ID，去重、保持出现顺序。

    原来只拿第一行那个去检查（ensure_chinese_ui(records[0]["Advertiser ID"])），
    因为作者自己的表里从头到尾就一个广告主。别人的表里完全可能一次跑好几个广告主，
    那样第 2 个广告主没权限就要跑到一半才炸，前面已经真发布出去的钱收不回来。
    """
    seen, out = set(), []
    for (advertiser_id, _campaign_name), _rows in groups:
        aid = str(advertiser_id).strip()
        if aid and aid not in seen:
            seen.add(aid)
            out.append(aid)
    return out


def _preflight_access(page, groups, mode):
    """开跑之前，把表格里每一个广告主 ID 都打开确认一遍。

    这一步是给别人用之后加的。以前的失败长这样：跑起来 -> 卡在语言检测 45 秒 ->
    报一句「页面可能没加载出来，或者当前登录账号没有这个广告主的权限」，
    使用者只看到「无权限操作」四个字，不知道是该登录、该换账号还是该改表格。
    现在在动手之前就把每个 ID 分别验一遍，报错直接说清是哪个 ID、哪种原因。
    """
    label = MODES[mode]["label"]
    ids = _advertiser_ids(groups)
    print(f"[预检] 表格里共 {len(ids)} 个广告主 ID: {', '.join(ids)}", flush=True)
    for aid in ids:
        access = check_advertiser_access(page, aid)
        if access.get("state") != "ok":
            raise PermissionError(describe_access(access, aid, label))
        print(f"[预检] 广告主 {aid} ✓ 可以打开（界面语言 {access.get('lang')}）",
              flush=True)


def _friendly_fatal(exc):
    """把致命异常翻成使用者看得懂的话；看不懂的才附完整堆栈。

    浏览器被关掉和没权限是最常见的两种，它们都不是「程序坏了」，
    甩一整个 Playwright 堆栈只会让人以为要改代码。
    """
    if is_browser_closed_error(exc):
        return ("浏览器窗口被关掉了，这次没跑完。\n"
                "跑的过程中请不要关那个自动打开的窗口——它就是干活的地方。\n"
                "已经发布出去的计划不会回滚，重跑之前请先去后台确认一下建到哪了。")
    if isinstance(exc, PermissionError):
        return str(exc)
    return traceback.format_exc()


def _run_build(xlsx_path, publish, mode):
    try:
        records = load_rows(xlsx_path)
        groups = group_by_campaign(records)
        with state_lock:
            run_state["status"] = "running"
            run_state["mode"] = mode
            run_state["total"] = len(groups)
            run_state["completed"] = 0
            run_state["results"] = []
            run_state["current"] = None
            run_state["fatal_error"] = None

        profile = MODES[mode]["profile"]
        series_map = None
        if mode == "drama":
            series_map, _ = load_series_map()

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                locale=LOCALE,
                extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
                viewport={"width": 1600, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()
            creative_usage = {}

            # 先确认登录 + 每个广告主 ID 的权限，再谈别的
            _preflight_access(page, groups, mode)

            if mode == "drama" and records:
                # 整套定位都依赖中文文案，界面变英文时每一步都会失败，所以先拦住。
                # 实测界面会在中英文之间自己来回切，每次跑都要确认。
                from src.drama.pages.campaign_page import ensure_chinese_ui

                ensure_chinese_ui(page, str(records[0]["Advertiser ID"]).strip())

            for (advertiser_id, campaign_name), rows in groups:
                with state_lock:
                    run_state["current"] = campaign_name

                budget = rows[0]["Budget"]
                if mode == "drama":
                    result = build_drama_campaign(
                        page,
                        str(advertiser_id),
                        str(campaign_name),
                        budget,
                        rows,
                        publish=publish,
                        creative_usage=creative_usage,
                        series_map=series_map,
                    )
                else:
                    result = build_campaign_group(
                        page,
                        str(advertiser_id),
                        str(campaign_name),
                        budget,
                        rows,
                        publish=publish,
                        creative_usage=creative_usage,
                    )
                result["campaign_name"] = campaign_name
                result["ad_group_count"] = len(rows)
                _log_result(mode, publish, campaign_name, result)

                with state_lock:
                    run_state["results"].append(result)
                    run_state["completed"] += 1

            context.close()

        with state_lock:
            run_state["status"] = "done"
            run_state["current"] = None

    except Exception as e:
        message = _friendly_fatal(e)
        with state_lock:
            run_state["status"] = "error"
            run_state["fatal_error"] = message
        try:
            from src.config import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(str(LOGS_DIR / "web_build.txt"), "a", encoding="utf-8") as f:
                f.write(f"\n=== 整体停了（mode={mode}）===\n{message}\n")
                # 日志里永远留一份完整堆栈，界面上只给人话
                f.write(f"\n--- 完整堆栈 ---\n{traceback.format_exc()}\n")
        except Exception:
            pass


def _login_worker(mode):
    """开一个浏览器窗口让使用者登录自己的 BC 账号，登录态存进这个模式的 profile。

    和搭建用的是同一个 profile 目录，所以必须互斥（见 _busy_reason）。
    """
    profile = MODES[mode]["profile"]
    label = MODES[mode]["label"]
    try:
        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(profile),
                headless=False,
                locale=LOCALE,
                extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
                viewport={"width": 1600, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()

            def progress(waited, url):
                with state_lock:
                    login_state["message"] = (
                        f"已等待 {waited} 秒，请在打开的窗口里登录（当前 {url[:60]}）"
                    )

            found = wait_for_login(page, timeout_seconds=600, on_progress=progress)
            context.close()

        with state_lock:
            if found:
                login_state["status"] = "done"
                login_state["message"] = (
                    f"登录成功（检测到「{found}」）。{label}的登录态已保存，可以开始搭建了。"
                )
            else:
                login_state["status"] = "error"
                login_state["message"] = (
                    "等了 10 分钟还没检测到登录成功。如果你其实已经登进去了，"
                    "可以直接关掉这个窗口再点一次【检查登录状态】。"
                )
    except Exception as e:
        with state_lock:
            login_state["status"] = "error"
            if is_browser_closed_error(e):
                login_state["message"] = (
                    "登录窗口被关掉了。如果登录已经完成，登录态是保存下来的，"
                    "直接开始搭建就行；没登完的话再点一次【登录 / 换账号】。"
                )
            else:
                login_state["message"] = f"登录窗口出错: {e}"


@app.route("/account")
def account():
    """当前模式的登录状态（弱判断：只看 profile 里有没有登录过的痕迹）。"""
    mode = request.args.get("mode", "minigame")
    if mode not in MODES:
        return jsonify({"ok": False, "error": f"未知模式: {mode}"}), 400
    with state_lock:
        login = dict(login_state)
    return jsonify(
        {
            "ok": True,
            "mode": mode,
            "label": MODES[mode]["label"],
            "has_login": profile_has_login(MODES[mode]["profile"]),
            "login": login,
            "busy": _busy_reason(),
        }
    )


@app.route("/account/login", methods=["POST"])
def account_login():
    payload = request.json if request.is_json else {}
    mode = payload.get("mode", "minigame")
    if mode not in MODES:
        return jsonify({"ok": False, "error": f"未知模式: {mode}"}), 400

    busy = _busy_reason()
    if busy:
        return jsonify({"ok": False, "error": busy}), 400

    with state_lock:
        login_state.update(
            status="waiting",
            mode=mode,
            message="正在打开登录窗口……请在弹出的浏览器里登录你自己的 BC 账号。",
        )
    threading.Thread(target=_login_worker, args=(mode,), daemon=True).start()
    return jsonify({"ok": True})


@app.route("/account/logout", methods=["POST"])
def account_logout():
    """清掉当前模式的登录态 —— 换成另一个人/另一个 BC 账号时用。

    做法是把 profile 目录整个挪走（留一份上一次的），下次打开就是全新未登录状态。
    换账号必须走这一步：直接在浏览器里切账号，残留 cookie 经常会把人自动登回旧账号，
    看着像换了、跑起来还是旧的。
    """
    payload = request.json if request.is_json else {}
    mode = payload.get("mode", "minigame")
    if mode not in MODES:
        return jsonify({"ok": False, "error": f"未知模式: {mode}"}), 400

    busy = _busy_reason()
    if busy:
        return jsonify({"ok": False, "error": busy}), 400

    try:
        backup = clear_profile(MODES[mode]["profile"])
    except Exception as e:
        return jsonify({"ok": False, "error": f"清理登录态失败: {e}"}), 500

    with state_lock:
        login_state.update(
            status="idle",
            mode=mode,
            message=f"已退出登录（上一次的登录态备份在 {backup}）。点【登录 / 换账号】登新账号。",
        )
    return jsonify({"ok": True, "backup": backup})


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/upload", methods=["POST"])
def upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"ok": False, "error": "没有选择文件"}), 400
    if not f.filename.lower().endswith(".xlsx"):
        return jsonify({"ok": False, "error": "请上传 .xlsx 文件"}), 400

    mode = request.form.get("mode", "minigame")
    if mode not in MODES:
        return jsonify({"ok": False, "error": f"未知模式: {mode}"}), 400

    f.save(str(UPLOAD_PATH))

    try:
        records = load_rows(str(UPLOAD_PATH))
        groups = group_by_campaign(records)
    except Exception as e:
        return jsonify({"ok": False, "error": f"表格格式有问题: {e}"}), 400

    warnings = _preflight_drama(groups) if mode == "drama" else []

    # 把表格里的广告主 ID 回显出来。给别人用之后这一项很重要：使用者能一眼看出
    # 程序读到的是不是他自己那个 ID，而不是跑起来才发现读错了列。
    advertiser_ids = _advertiser_ids(groups)
    if not profile_has_login(MODES[mode]["profile"]):
        warnings.append(
            f"浏览器里还没登录过（{MODES[mode]['label']}）。"
            "请先点上面的【登录 / 换账号】，用你自己的 BC 账号登录，再开始搭建。"
        )

    return jsonify(
        {
            "ok": True,
            "filename": f.filename,
            "row_count": len(records),
            "campaign_count": len(groups),
            "advertiser_ids": advertiser_ids,
            "warnings": warnings,
        }
    )


@app.route("/run", methods=["POST"])
def run():
    with state_lock:
        if run_state["status"] == "running":
            return jsonify({"ok": False, "error": "已经在运行中，请等它跑完"}), 400

    if not UPLOAD_PATH.exists():
        return jsonify({"ok": False, "error": "还没上传表格"}), 400

    payload = request.json if request.is_json else {}
    publish = bool(payload.get("publish", True))
    mode = payload.get("mode", "minigame")
    if mode not in MODES:
        return jsonify({"ok": False, "error": f"未知模式: {mode}"}), 400

    _reset_state()
    t = threading.Thread(
        target=_run_build, args=(str(UPLOAD_PATH), publish, mode), daemon=True
    )
    t.start()
    return jsonify({"ok": True})


@app.route("/status")
def status():
    with state_lock:
        return jsonify(dict(run_state))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=PORT, debug=False)
