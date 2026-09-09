"""批量下载视频 —— 起子进程、收进度。

这个模块【不碰】搭建那一套的任何东西：不用 Playwright、不用浏览器 profile、
不共享 app.py 里的 state_lock。下载和搭建可以同时跑，互不影响。

下载器本体在 yt-bulk-downloader/，有自己的 .venv（python 3.14），
这里用 subprocess 调它的 headless.py，按行读 JSON 事件。
为什么不 import 进来直接跑，见 headless.py 开头那段。
"""

import json
import os
import shutil
import socket
import subprocess
import threading
import time

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DL_DIR = os.path.join(PROJECT_ROOT, "yt-bulk-downloader")
DL_PYTHON = os.path.join(DL_DIR, ".venv", "bin", "python")
DL_HEADLESS = os.path.join(DL_DIR, "headless.py")
POT_SERVER_JS = os.path.join(DL_DIR, "pot-provider", "server", "build", "main.js")
NODE_MODULES = os.path.join(DL_DIR, "pot-provider", "server", "node_modules")

# 日志留多少行。下载进度刷得很快，不封顶会把内存吃光。
MAX_LOG_LINES = 500

DEFAULT_DEST = os.path.expanduser("~/Downloads/批量下载素材")

SORT_KEYS = {
    "latest": "最新",
    "view_count": "播放量",
    "like_count": "点赞量",
}

_lock = threading.Lock()
_proc = None            # 当前子进程；None 表示没在跑

state = {
    "status": "idle",       # idle | running | done | stopped | error
    "status_msg": "",
    "lines": [],
    "sources": [],          # [{"url":..., "status":..., "done":0, "total":0}]
    "error": None,
    "dest": "",
    "started_at": None,
    "finished_at": None,
}


# ---------------------------------------------------------------------------
# 环境自检
#
# 这几样缺一个，症状都是「点了开始、跑一半失败」，而且报错信息很难看懂：
#   * ffmpeg 缺  -> 下载完合并音视频那一步炸（YouTube 一定要合并）
#   * node_modules 缺 -> PO-token 服务起不来 -> YouTube 全部 403
#   * .venv 缺   -> 子进程根本起不来
# 所以在【点开始之前】就查一遍，把话说明白，别让人对着一堆英文栈发愣。
# 实测这台机器上三样一开始全是缺的。
# ---------------------------------------------------------------------------

def _which(name):
    found = shutil.which(name)
    if found:
        return found
    for cand in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.exists(cand):
            return cand
    return None


def check_env():
    """返回 (致命问题列表, 提醒列表)。致命的会挡住启动。"""
    fatal, warn = [], []

    if not os.path.exists(DL_PYTHON):
        fatal.append(
            f"下载器的 Python 环境不在：{DL_PYTHON}。"
            "在 yt-bulk-downloader 文件夹里执行 "
            "`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`"
        )
    if not os.path.exists(DL_HEADLESS):
        fatal.append(f"缺文件：{DL_HEADLESS}")

    if not _which("ffmpeg"):
        fatal.append(
            "没装 ffmpeg。下载下来的视频和音频是两个流，要靠它合并；"
            "没有它 YouTube 的视频一定失败。装：brew install ffmpeg"
        )

    if not _which("node"):
        warn.append("没装 node，YouTube 的反机器人服务起不来，YouTube 大概率 403（TikTok 不受影响）")
    elif not os.path.isdir(NODE_MODULES):
        warn.append(
            "pot-provider 的 node_modules 没装，YouTube 反机器人服务起不来 —— "
            "在 yt-bulk-downloader/pot-provider/server 里执行 npm install（TikTok 不受影响）"
        )

    if not _which("aria2c"):
        warn.append("没装 aria2c，下载会慢一些（不影响成功率）。装：brew install aria2")

    return fatal, warn


def pot_running():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.4)
        return s.connect_ex(("127.0.0.1", 4416)) == 0


# ---------------------------------------------------------------------------
# 跑
# ---------------------------------------------------------------------------

def is_running():
    with _lock:
        return state["status"] == "running"


def _log(msg, replace=False):
    with _lock:
        lines = state["lines"]
        if replace and lines:
            lines[-1] = msg          # 原地刷新（下载百分比就是这么滚的）
        else:
            lines.append(msg)
        if len(lines) > MAX_LOG_LINES:
            del lines[: len(lines) - MAX_LOG_LINES]


def _handle_event(ev):
    kind = ev.get("t")
    if kind == "log":
        _log(str(ev.get("msg", "")), bool(ev.get("replace")))
    elif kind == "status":
        with _lock:
            state["status_msg"] = str(ev.get("msg", ""))
    elif kind == "source":
        idx = int(ev.get("idx", 0)) - 1
        with _lock:
            if 0 <= idx < len(state["sources"]):
                s = state["sources"][idx]
                for k in ("status", "done", "total"):
                    if ev.get(k) is not None:
                        s[k] = ev[k]
    elif kind == "done":
        with _lock:
            state["status"] = "done"
            state["status_msg"] = "全部完成"
    elif kind == "stopped":
        with _lock:
            state["status"] = "stopped"
            state["status_msg"] = "已停止"
    elif kind == "error":
        with _lock:
            state["status"] = "error"
            state["error"] = str(ev.get("msg", ""))
            state["status_msg"] = "出错了"
        if ev.get("trace"):
            _log(str(ev["trace"]))


def _reader(proc):
    """把子进程 stdout 上的 JSON 行读成事件。"""
    try:
        for raw in proc.stdout:
            raw = raw.strip()
            if not raw:
                continue
            try:
                _handle_event(json.loads(raw))
            except json.JSONDecodeError:
                # 不是 JSON 的行（子进程里第三方库直接打的）也留着，排查时有用
                _log(raw)
    except Exception as exc:
        _log(f"[读取子进程输出失败] {type(exc).__name__}: {exc}")
    finally:
        code = proc.wait()
        with _lock:
            if state["status"] == "running":
                # 子进程没发 done/stopped/error 就退了 —— 被杀或者崩了
                if code == 0:
                    state["status"] = "done"
                    state["status_msg"] = "结束"
                else:
                    state["status"] = "error"
                    state["error"] = f"下载进程异常退出（退出码 {code}）"
                    state["status_msg"] = "出错了"
            state["finished_at"] = time.time()
        global _proc
        _proc = None


def start(urls, dest, sort_key="latest", top_n=50, scan_limit=200,
          max_height=1080, parallel=3, prefer_res=False,
          cookies_browser="chrome", cookiefile=""):
    """启动一次批量下载。返回 (ok, 出错原因)。"""
    global _proc

    with _lock:
        if state["status"] == "running":
            return False, "已经有一个下载在跑了，等它结束或者先点停止"

    fatal, warn = check_env()
    if fatal:
        return False, "环境还差东西：\n" + "\n".join("· " + f for f in fatal)

    dest = os.path.expanduser((dest or "").strip() or DEFAULT_DEST)
    try:
        os.makedirs(dest, exist_ok=True)
    except Exception as exc:
        return False, f"下载目录建不出来：{dest}（{exc}）"
    if not os.access(dest, os.W_OK):
        return False, f"下载目录没有写权限：{dest}"

    args = {
        "urls": urls,
        "dest": dest,
        "sort_key": sort_key,
        "top_n": int(top_n),
        "scan_limit": int(scan_limit),
        "max_height": int(max_height),
        "parallel": int(parallel),
        "prefer_res": bool(prefer_res),
        "cookies_browser": cookies_browser,
        "cookiefile": cookiefile,
    }
    argfile = os.path.join(dest, ".download_args.json")
    with open(argfile, "w", encoding="utf-8") as f:
        json.dump(args, f, ensure_ascii=False)

    # Finder / launchd 起的进程 PATH 很窄，ffmpeg、aria2c、node 都在 Homebrew 里，
    # 不显式加进去子进程就找不到 —— 下载器自己的 run.command 也是这么做的。
    env = dict(os.environ)
    env["PATH"] = "/opt/homebrew/bin:/usr/local/bin:" + env.get("PATH", "")
    env["PYTHONUNBUFFERED"] = "1"

    with _lock:
        state.update(
            status="running", status_msg="正在启动…", lines=[], error=None,
            dest=dest, started_at=time.time(), finished_at=None,
            sources=[{"url": u, "status": "排队中", "done": 0, "total": 0}
                     for u in urls],
        )
    for w in warn:
        _log("! " + w)

    try:
        _proc = subprocess.Popen(
            [DL_PYTHON, DL_HEADLESS, argfile],
            cwd=DL_DIR, env=env, text=True,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT, bufsize=1,
        )
    except Exception as exc:
        with _lock:
            state.update(status="error", error=f"下载进程起不来：{exc}")
        return False, str(exc)

    threading.Thread(target=_reader, args=(_proc,), daemon=True).start()
    return True, None


def stop():
    """请求停止。先好好说（往 stdin 写 stop），不听再动手。

    为什么不上来就 kill：已经下完的视频记在下载目录的 .download_state.json 里，
    让子进程自己收尾，下次跑同一批能接着断点续传。
    """
    global _proc
    p = _proc
    if p is None or p.poll() is not None:
        return False, "现在没有在跑的下载"
    _log("正在停止…")
    try:
        p.stdin.write("stop\n")
        p.stdin.flush()
    except Exception:
        pass

    def _force():
        time.sleep(20)
        if p.poll() is None:
            _log("! 20 秒还没停下，强制结束进程")
            try:
                p.terminate()
                time.sleep(3)
                if p.poll() is None:
                    p.kill()
            except Exception:
                pass

    threading.Thread(target=_force, daemon=True).start()
    return True, None


def snapshot():
    with _lock:
        return {
            "status": state["status"],
            "status_msg": state["status_msg"],
            "lines": list(state["lines"])[-200:],
            "sources": [dict(s) for s in state["sources"]],
            "error": state["error"],
            "dest": state["dest"],
        }
