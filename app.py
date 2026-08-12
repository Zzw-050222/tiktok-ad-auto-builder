import threading
import traceback

from flask import Flask, jsonify, render_template, request
from playwright.sync_api import sync_playwright

from src.builder import build_campaign_group
from src.config import ACCEPT_LANGUAGE, BROWSER_PROFILE_DIR, LOCALE, UPLOADS_DIR
from src.excel_loader import group_by_campaign, load_rows

app = Flask(__name__)

UPLOAD_PATH = UPLOADS_DIR / "latest.xlsx"

state_lock = threading.Lock()
run_state = {
    "status": "idle",  # idle | running | done | error
    "total": 0,
    "completed": 0,
    "current": None,
    "results": [],
    "fatal_error": None,
}


def _reset_state():
    run_state.update(
        status="idle", total=0, completed=0, current=None, results=[], fatal_error=None
    )


def _run_build(xlsx_path, publish):
    try:
        records = load_rows(xlsx_path)
        groups = group_by_campaign(records)
        with state_lock:
            run_state["status"] = "running"
            run_state["total"] = len(groups)
            run_state["completed"] = 0
            run_state["results"] = []
            run_state["current"] = None
            run_state["fatal_error"] = None

        with sync_playwright() as p:
            context = p.chromium.launch_persistent_context(
                user_data_dir=str(BROWSER_PROFILE_DIR),
                headless=False,
                locale=LOCALE,
                extra_http_headers={"Accept-Language": ACCEPT_LANGUAGE},
                viewport={"width": 1600, "height": 1000},
            )
            page = context.pages[0] if context.pages else context.new_page()
            creative_usage = {}

            for (advertiser_id, campaign_name), rows in groups:
                with state_lock:
                    run_state["current"] = campaign_name

                budget = rows[0]["Budget"]
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

                with state_lock:
                    run_state["results"].append(result)
                    run_state["completed"] += 1

            context.close()

        with state_lock:
            run_state["status"] = "done"
            run_state["current"] = None

    except Exception:
        with state_lock:
            run_state["status"] = "error"
            run_state["fatal_error"] = traceback.format_exc()


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

    f.save(str(UPLOAD_PATH))

    try:
        records = load_rows(str(UPLOAD_PATH))
        groups = group_by_campaign(records)
    except Exception as e:
        return jsonify({"ok": False, "error": f"表格格式有问题: {e}"}), 400

    return jsonify(
        {
            "ok": True,
            "filename": f.filename,
            "row_count": len(records),
            "campaign_count": len(groups),
        }
    )


@app.route("/run", methods=["POST"])
def run():
    with state_lock:
        if run_state["status"] == "running":
            return jsonify({"ok": False, "error": "已经在运行中，请等它跑完"}), 400

    if not UPLOAD_PATH.exists():
        return jsonify({"ok": False, "error": "还没上传表格"}), 400

    publish = bool(request.json.get("publish", True)) if request.is_json else True

    _reset_state()
    t = threading.Thread(target=_run_build, args=(str(UPLOAD_PATH), publish), daemon=True)
    t.start()
    return jsonify({"ok": True})


@app.route("/status")
def status():
    with state_lock:
        return jsonify(dict(run_state))


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
