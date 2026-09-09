"""无界面版下载器 —— 给自动搭建程序的网页后台调用。

为什么单独开一个进程、而不是把引擎直接 import 进 Flask：
  * 这个下载器有自己的 .venv（python 3.14），搭建程序的 venv 是 3.13，
    yt-dlp / curl_cffi / bgutil 插件全装在前者里，混在一起装容易把
    已经跑通的搭建功能带崩 —— 使用者明确要求「不能影响正常运行的功能」。
  * yt-dlp 会起线程、开子进程（ffmpeg / aria2c / node），万一卡死或者
    内存爆了，单独的进程直接杀掉就行，搭建那边一点感觉都没有。

和调用方的约定：
  * 入参：argv[1] 是一个 JSON 文件的路径（不走命令行参数，URL 和路径里
    什么字符都可能有，走文件最省心）。
  * 出参：stdout 上【一行一个 JSON】，字段 t 是事件类型：
        {"t":"log","msg":...}                  一行日志
        {"t":"status","msg":...}               总体状态
        {"t":"source","idx":1,"status":...,"done":3,"total":50}
        {"t":"done"} / {"t":"stopped"} / {"t":"error","msg":...}
  * 停止：往 stdin 写一行 "stop"。不用直接 kill —— 已下完的视频会记进
    下载目录里的 .download_state.json，正常收尾能保住断点续传的记录。
"""

import json
import os
import sys
import threading
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import app as engine        # noqa: E402  （app.py 的界面在 __main__ 里，import 不会弹窗）

_stop = threading.Event()
_out_lock = threading.Lock()


def emit(kind, **payload):
    """往 stdout 写一行 JSON。加锁是因为 yt-dlp 的进度回调在多个线程里跑，
    不加锁两行会插在一起，调用方就解析不出来了。"""
    line = json.dumps({"t": kind, **payload}, ensure_ascii=False)
    with _out_lock:
        sys.stdout.write(line + "\n")
        sys.stdout.flush()


def _watch_stdin():
    """等调用方发 "stop"。"""
    try:
        for line in sys.stdin:
            if line.strip().lower() == "stop":
                _stop.set()
                emit("log", msg="收到停止请求，正在收尾（已下完的不会丢）…")
                return
    except Exception:
        pass


def main():
    if len(sys.argv) < 2:
        emit("error", msg="没有传入参数文件")
        return 2
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        a = json.load(f)

    threading.Thread(target=_watch_stdin, daemon=True).start()

    # 引擎的 log 回调带一个 replace 参数（界面上用来原地刷新百分比）。
    # 网页这边不做原地覆盖，但要把它透传出去，让前端自己决定要不要替换上一行。
    def log(msg, replace=False):
        emit("log", msg=str(msg).rstrip("\n"), replace=bool(replace))

    dest = os.path.expanduser(str(a.get("dest") or ""))
    os.makedirs(dest, exist_ok=True)

    pot = None
    try:
        # YouTube 的反机器人要这个本地 PO-token 服务；TikTok 用不上，
        # 但起一下没坏处，起不来引擎自己会打警告继续走。
        pot = engine.ensure_pot_server(lambda m, replace=False: emit("log", msg=str(m)))

        # 引擎只等 10 秒就放弃。这在【第一次跑】的电脑上不够：
        # 实测一台没有 Homebrew、node 是刚从 nodejs.org 下下来的机器上，
        # 首次启动要 5 秒以上（macOS 还要对新下载的二进制做一次安全扫描），
        # 于是明明能起来却被判成失败，YouTube 全部 403。
        # 这里再多等一会儿 —— 只在进程还活着的时候等，没起来也只是慢一点。
        if pot is not None and not engine._pot_running():
            emit("log", msg="反机器人服务还在启动，再等等（第一次会慢）…")
            for _ in range(40):                      # 最多再等 20 秒
                if pot.poll() is not None:           # 进程已经死了，不用等了
                    break
                if engine._pot_running():
                    emit("log", msg="反机器人服务已就绪。")
                    break
                time.sleep(0.5)

        engine.run_jobs(
            urls=a["urls"],
            sort_key=a.get("sort_key", "latest"),
            top_n=int(a.get("top_n", 50)),
            scan_limit=int(a.get("scan_limit", 200)),
            dest=dest,
            cookies_browser=a.get("cookies_browser") or "none",
            cookiefile=a.get("cookiefile") or None,
            max_height=int(a.get("max_height", 1080)),
            parallel=int(a.get("parallel", 3)),
            prefer_res=bool(a.get("prefer_res", False)),
            log=log,
            status=lambda m: emit("status", msg=str(m)),
            progress=lambda m: emit("status", msg=str(m)),
            source=lambda idx, **kw: emit("source", idx=idx, **kw),
            should_stop=_stop.is_set,
        )
        emit("done")
        return 0
    except engine.Cancelled:
        emit("stopped")
        return 0
    except Exception as exc:
        import traceback
        emit("error", msg=f"{type(exc).__name__}: {exc}",
             trace=traceback.format_exc()[-2000:])
        return 1
    finally:
        if pot is not None:
            try:
                pot.terminate()
            except Exception:
                pass


if __name__ == "__main__":
    sys.exit(main())
