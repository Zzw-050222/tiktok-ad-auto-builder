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

            if mode == "drama" and records:
                # 整套定位都依赖中文文案，界面变英文时每一步都会失败，所以先拦住。
                # 这个账号实测会在中英文之间自己来回切，每次跑都要确认。
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

    except Exception:
        tb = traceback.format_exc()
        with state_lock:
            run_state["status"] = "error"
            run_state["fatal_error"] = tb
        try:
            from src.config import LOGS_DIR

            LOGS_DIR.mkdir(parents=True, exist_ok=True)
            with open(str(LOGS_DIR / "web_build.txt"), "a", encoding="utf-8") as f:
                f.write(f"\n=== 整体崩了（mode={mode}）===\n{tb}\n")
        except Exception:
            pass


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

    return jsonify(
        {
            "ok": True,
            "filename": f.filename,
            "row_count": len(records),
            "campaign_count": len(groups),
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
