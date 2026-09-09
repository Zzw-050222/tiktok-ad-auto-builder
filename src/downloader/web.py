"""批量下载视频 —— 网页接口。

单独一个蓝图，路由都在 /download 下面，和搭建、共享那几个接口完全不重名。
app.py 只要两行就能接上：
    from src.downloader.web import bp as download_bp
    app.register_blueprint(download_bp)
"""

from flask import Blueprint, jsonify, request

from src.downloader import runner

bp = Blueprint("downloader", __name__)

# 页面上让选的清晰度档位
QUALITY_CHOICES = [0, 480, 720, 1080, 1440, 2160]
BROWSER_CHOICES = ["chrome", "edge", "firefox", "safari", "brave", "opera", "vivaldi", "none"]


def _lines(text):
    return [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]


@bp.route("/download/env")
def download_env():
    """环境自检。页面加载时查一次，缺东西直接显示在卡片上。"""
    fatal, warn = runner.check_env()
    return jsonify({
        "ok": not fatal,
        "fatal": fatal,
        "warn": warn,
        "pot_running": runner.pot_running(),
        "default_dest": runner.DEFAULT_DEST,
    })


@bp.route("/download/start", methods=["POST"])
def download_start():
    p = request.json if request.is_json else {}

    urls = _lines(p.get("urls"))
    if not urls:
        return jsonify({"ok": False, "error": "还没填要下载的链接（一行一个）"}), 400
    bad = [u for u in urls if not u.lower().startswith(("http://", "https://"))]
    if bad:
        return jsonify({
            "ok": False,
            "error": "这些不像网址（要以 http:// 或 https:// 开头）：" + "、".join(bad[:3]),
        }), 400

    sort_key = p.get("sort_key", "latest")
    if sort_key not in runner.SORT_KEYS:
        return jsonify({"ok": False, "error": f"未知的排序方式: {sort_key}"}), 400

    def _int(name, default, lo, hi):
        try:
            v = int(p.get(name, default))
        except (TypeError, ValueError):
            return None, f"「{name}」要填数字"
        if not (lo <= v <= hi):
            return None, f"「{name}」要在 {lo} 到 {hi} 之间"
        return v, None

    top_n, err = _int("top_n", 50, 1, 5000)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    scan_limit, err = _int("scan_limit", 200, 0, 100000)
    if err:
        return jsonify({"ok": False, "error": err}), 400
    parallel, err = _int("parallel", 3, 1, 10)
    if err:
        return jsonify({"ok": False, "error": err}), 400

    try:
        max_height = int(p.get("max_height", 1080))
    except (TypeError, ValueError):
        max_height = 1080
    if max_height not in QUALITY_CHOICES:
        return jsonify({"ok": False, "error": f"清晰度只能选 {QUALITY_CHOICES}"}), 400

    browser = p.get("cookies_browser", "chrome")
    if browser not in BROWSER_CHOICES:
        return jsonify({"ok": False, "error": f"未知的浏览器: {browser}"}), 400

    ok, why = runner.start(
        urls=urls,
        dest=p.get("dest", ""),
        sort_key=sort_key,
        top_n=top_n,
        scan_limit=scan_limit,
        max_height=max_height,
        parallel=parallel,
        prefer_res=bool(p.get("prefer_res")),
        cookies_browser=browser,
        cookiefile=str(p.get("cookiefile") or "").strip(),
    )
    if not ok:
        return jsonify({"ok": False, "error": why}), 400
    return jsonify({"ok": True, "count": len(urls)})


@bp.route("/download/status")
def download_status():
    return jsonify(runner.snapshot())


@bp.route("/download/stop", methods=["POST"])
def download_stop():
    ok, why = runner.stop()
    return jsonify({"ok": ok, "error": why}), (200 if ok else 400)
