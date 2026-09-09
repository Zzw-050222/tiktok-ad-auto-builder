#!/usr/bin/env python3
"""
YouTube Bulk Downloader — GUI tool.

Paste several channel / "subscribe" page URLs, choose how many videos to keep
per channel ranked by view count or like count, pick a destination folder, and
the tool downloads each channel's top-N one channel at a time (finishing A
before starting B).

Engine: yt-dlp (+ ffmpeg for merging). UI: tkinter (native folder picker).
"""

import json
import os
import queue
import shutil
import socket
import subprocess
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

import yt_dlp
from yt_dlp.utils import DownloadCancelled


# ---------------------------------------------------------------------------
# Backend: extraction + download (runs in a worker thread, never touches the UI)
# ---------------------------------------------------------------------------

# --- "Be polite to YouTube" knobs -------------------------------------------
# These keep request patterns gentle so a logged-in account isn't flagged for
# scraping. Lower = safer (and slower); raise only if you understand the risk.
#
# How many threads probe per-video metadata (view/like counts) at once. Kept
# low because ranking can touch hundreds of video pages in quick succession.
METADATA_WORKERS = 3
# Random pause (seconds) before each video download, and between extraction
# requests, to look like human activity rather than a bot.
DOWNLOAD_SLEEP = (1.0, 5.0)        # (min, max) seconds before each download
REQUEST_SLEEP = 0.75               # seconds between requests during extraction
# Total aria2c connections to spread across the videos downloading at once.
TOTAL_CONNS = 8

# Local "PO token" provider (bgutil) — yt-dlp needs it to fetch video data.
HERE = os.path.dirname(os.path.abspath(__file__))
POT_PORT = 4416
POT_SERVER_JS = os.path.join(HERE, "pot-provider", "server", "build", "main.js")


def _which(name):
    """Locate a binary. Apps launched from Finder get a minimal PATH, so fall
    back to the usual Homebrew locations."""
    found = shutil.which(name)
    if found:
        return found
    for cand in (f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"):
        if os.path.exists(cand):
            return cand
    return None


def _find_node():
    return _which("node")


def _pot_running():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex(("127.0.0.1", POT_PORT)) == 0


def ensure_pot_server(log):
    """Start the bgutil PO-token provider on :4416 if it isn't already up.

    Returns the Popen handle (or None if it was already running / couldn't
    start). The caller keeps the handle so it can be terminated on exit.
    """
    if _pot_running():
        log("PO-token provider already running on :%d." % POT_PORT)
        return None
    node = _find_node()
    if not node:
        log("! WARNING: Node.js not found — downloads will likely fail with 403. "
            "Install it with `brew install node`.")
        return None
    if not os.path.exists(POT_SERVER_JS):
        log("! WARNING: PO-token provider isn't built at %s" % POT_SERVER_JS)
        return None
    log("Starting PO-token provider…")
    proc = subprocess.Popen(
        [node, POT_SERVER_JS],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    for _ in range(40):  # wait up to ~10s for it to bind the port
        if _pot_running():
            log("PO-token provider ready.")
            return proc
        time.sleep(0.25)
    log("! WARNING: PO-token provider did not come up in time.")
    return proc


class Cancelled(Exception):
    """Raised internally to unwind the worker when the user hits Stop."""


class DownloadState:
    """Persists which videos have already completed, in a small JSON file inside
    the destination folder. This lets an interrupted run resume — re-running the
    same batch skips finished videos — and lets the UI show per-source progress.
    """
    FILENAME = ".download_state.json"

    def __init__(self, dest):
        self.path = os.path.join(dest, self.FILENAME)
        self.lock = threading.Lock()
        self.completed = set()
        try:
            with open(self.path) as f:
                self.completed = set(json.load(f).get("completed", []))
        except (OSError, ValueError):
            pass  # missing or corrupt -> start fresh

    @staticmethod
    def key(platform, vid):
        return f"{platform}:{vid}"

    def is_done(self, platform, vid):
        return self.key(platform, vid) in self.completed

    def mark_done(self, platform, vid):
        with self.lock:
            self.completed.add(self.key(platform, vid))
            tmp = self.path + ".tmp"
            try:
                with open(tmp, "w") as f:
                    json.dump({"completed": sorted(self.completed)}, f, indent=0)
                os.replace(tmp, self.path)  # atomic, survives a crash mid-write
            except OSError:
                pass


def _platform(url):
    """Identify which site a URL belongs to, so we apply the right settings."""
    u = (url or "").lower()
    if "tiktok.com" in u:
        return "tiktok"
    if "snapchat.com" in u:
        return "snapchat"
    if "youtube.com" in u or "youtu.be" in u:
        return "youtube"
    return "other"


def _engine_opts(opts, cookies_browser, url, cookiefile=None):
    """Add the auth + anti-bot settings a yt-dlp call needs for this URL.

    Cookies (a logged-in session) help on every supported site. Two sources:
    an exported Netscape cookies.txt file (e.g. from the "Get cookies.txt
    LOCALLY" extension) takes priority if given — it's the most reliable when
    Chrome's encryption blocks live reads — otherwise cookies are pulled live
    from the chosen browser. The heavier YouTube anti-bot stack (Node JS
    runtime, EJS solver, local PO-token provider) is only needed for YouTube.
    """
    if cookiefile:
        opts["cookiefile"] = cookiefile
    elif cookies_browser and cookies_browser != "none":
        opts["cookiesfrombrowser"] = (cookies_browser,)
    if _platform(url) == "youtube":
        node = _find_node()
        opts["js_runtimes"] = {"node": {"path": node} if node else {}}
        opts["remote_components"] = ["ejs:github"]
    return opts


def _flatten_entries(info):
    """A channel URL can return nested playlists (Videos / Shorts / Live tabs).

    Walk the tree and yield only real video entries (those with an id/url that
    points at a watchable video, not another playlist).
    """
    if info is None:
        return
    etype = info.get("_type")
    if etype == "playlist" or "entries" in info:
        for entry in info.get("entries") or []:
            yield from _flatten_entries(entry)
    else:
        yield info


def _tiktok_account_from_video(url, cookies_browser, cookiefile, log):
    """Given a TikTok video URL, resolve the poster's account listing URL
    (`tiktokuser:<channel_id>`). TikTok can't always resolve a bare @handle, but
    a video always carries its poster's channel_id, so pasting any video from an
    account is a reliable way to reach the whole account."""
    opts = {"quiet": True, "no_warnings": True, "skip_download": True}
    _engine_opts(opts, cookies_browser, url, cookiefile)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    cid = info.get("channel_id")
    if cid:
        log("  Resolved TikTok account from the video URL; listing the account.")
        return f"tiktokuser:{cid}"
    return url  # fall back to treating it as a single video


def _flat_list(url, scan_limit, cookies_browser, cookiefile, should_stop):
    """Flat-extract a URL into a list of video dicts (no view/like probing)."""
    opts = {
        "quiet": True,
        "no_warnings": True,
        "extract_flat": "in_playlist",
        "skip_download": True,
    }
    _engine_opts(opts, cookies_browser, url, cookiefile)
    if scan_limit and scan_limit > 0:
        opts["playlistend"] = scan_limit

    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False)
    if should_stop():
        raise Cancelled()

    videos = []
    seen = set()
    for e in _flatten_entries(info):
        vid = e.get("id")
        vurl = e.get("url") or e.get("webpage_url")
        if not vurl and vid:
            vurl = f"https://www.youtube.com/watch?v={vid}"
        if not vurl or vurl in seen:
            continue
        seen.add(vurl)
        videos.append({
            "id": vid, "url": vurl, "title": e.get("title") or vid,
            # Kept if the listing already provides them (TikTok does); None
            # means "not known yet" and triggers a per-video probe when ranking.
            "view_count": e.get("view_count"),
            "like_count": e.get("like_count"),
        })
        if scan_limit and len(videos) >= scan_limit:
            break
    return videos


def list_channel_videos(url, scan_limit, cookies_browser, cookiefile, log, should_stop):
    """Return a flat list of video dicts for a channel / user / video URL.

    Some sites (notably TikTok) include view/like counts in the listing, so we
    keep them and skip per-video probing. `scan_limit` caps how many recent
    videos we consider (0 = all). A single-video URL comes back as one entry.
    """
    # A TikTok video URL: try to expand it to the whole account, but fall back
    # to just that video if the account can't be enumerated (common for some
    # repost/"short-drama" accounts — TikTok won't return their video list).
    if _platform(url) == "tiktok" and "/video/" in url:
        account_url = _tiktok_account_from_video(url, cookies_browser, cookiefile, log)
        if account_url != url:
            try:
                vids = _flat_list(account_url, scan_limit, cookies_browser,
                                  cookiefile, should_stop)
            except Cancelled:
                raise
            except Exception:
                vids = []
            if vids:
                log(f"  Found {len(vids)} video(s) in the account.")
                return vids
            log("  Account listing is empty/unavailable — downloading just the "
                "video URL you pasted.")
        # fall through to list the single video URL itself

    try:
        videos = _flat_list(url, scan_limit, cookies_browser, cookiefile, should_stop)
    except Cancelled:
        raise
    except Exception as exc:
        msg = str(exc)
        if "secondary user ID" in msg or "does not have any videos" in msg:
            raise RuntimeError(
                "TikTok couldn't open this @handle (a known limitation for some "
                "accounts). Fix: open any video from this account in your browser "
                "and paste that video's URL here instead.") from exc
        raise

    log(f"  Found {len(videos)} video(s).")
    return videos


def fetch_metadata(video, cookies_browser, cookiefile, log, should_stop):
    """Fetch view_count and like_count for one video (full extraction)."""
    if should_stop():
        raise Cancelled()
    opts = {
        "quiet": True, "no_warnings": True, "skip_download": True,
        "sleep_interval_requests": REQUEST_SLEEP,  # gentle pacing between requests
    }
    _engine_opts(opts, cookies_browser, video["url"], cookiefile)
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(video["url"], download=False)
        video["view_count"] = info.get("view_count") or 0
        video["like_count"] = info.get("like_count") or 0
        video["title"] = info.get("title") or video["title"]
    except Exception as exc:  # a single broken/private video shouldn't kill the run
        video["view_count"] = 0
        video["like_count"] = 0
        video["error"] = str(exc)
    return video


def rank_videos(videos, sort_key, top_n, cookies_browser, cookiefile, log, should_stop, progress):
    """Return the top-N videos by sort_key ("view_count" or "like_count").

    Only videos whose count the listing didn't already provide get a per-video
    probe — so sites like TikTok (counts come free) need zero extra requests.
    """
    need = [v for v in videos if v.get(sort_key) is None]
    if need:
        total = len(need)
        done = 0
        log(f"  Fetching view/like counts for {total} videos…")
        with ThreadPoolExecutor(max_workers=METADATA_WORKERS) as pool:
            futures = {pool.submit(fetch_metadata, v, cookies_browser, cookiefile,
                                   log, should_stop): v
                       for v in need}
            for fut in as_completed(futures):
                if should_stop():
                    raise Cancelled()
                fut.result()
                done += 1
                if done % 5 == 0 or done == total:
                    progress(f"Ranking: fetched {done}/{total} metadata")
    else:
        log("  Counts already provided by the listing — no probing needed.")

    videos.sort(key=lambda v: v.get(sort_key) or 0, reverse=True)
    top = videos[:top_n] if top_n > 0 else videos

    missing = sum(1 for v in top if sort_key == "like_count" and not v.get("like_count"))
    if missing:
        log(f"  Note: {missing} of the top videos had no public like count "
            f"available (counted as 0).")
    return top


def _format_for(max_height, prefer_res=False):
    """Return (format, format_sort) for yt-dlp.

    `bv*+ba/b` always yields a file WITH audio: it merges best video + best
    audio, or falls back to the best already-combined format.

    Two ranking modes:
      * default (prefer_res=False) — prefer H.264 video + AAC audio, which plays
        with sound in every player. TikTok's higher tiers are H.265 (HEVC),
        which many players show silently, so we pick H.264 (often up to 720p).
      * prefer_res=True — prefer the highest resolution regardless of codec, so
        you can get e.g. TikTok 1080p (which is HEVC-only). May be silent or
        unplayable in some apps; H.264 is only a tie-breaker here.

    `res` caps on the *smaller* dimension, so the cap behaves correctly for
    portrait (TikTok) and landscape alike.
    """
    fmt = "bv*+ba/b"
    cap = f"res:{max_height}" if max_height and max_height > 0 else "res"
    if prefer_res:
        sort = [cap, "vcodec:h264", "acodec:aac"]
    else:
        sort = ["vcodec:h264", "acodec:aac"]
        if max_height and max_height > 0:
            sort.append(cap)
    return fmt, sort


def download_video(video, dest, channel_label, cookies_browser, cookiefile, max_height,
                   log, should_stop, tag="", live=True, conns=16, prefer_res=False):
    """Download a single video into dest/<channel>/.

    `tag` prefixes log lines (e.g. "[3] ") so interleaved parallel downloads
    stay readable. `live` uses in-place line updates (good for one-at-a-time);
    when False, progress is logged at ~10% steps to avoid flooding the log.
    """
    state = {"decile": -1}

    def hook(d):
        if should_stop():
            raise DownloadCancelled()
        if d["status"] == "downloading":
            speed = d.get("_speed_str", "").strip()
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            pct = (done / total * 100) if total else 0
            if live:
                log(f"      {tag}{pct:.1f}% at {speed}", replace=True)
            else:
                dec = int(pct // 10)
                if dec > state["decile"]:
                    state["decile"] = dec
                    log(f"      {tag}{pct:.0f}% at {speed}")
        elif d["status"] == "finished":
            log(f"      {tag}merging / finishing…", replace=live)

    outtmpl = os.path.join(dest, "%(uploader)s", "%(title)s [%(id)s].%(ext)s")
    fmt, fmt_sort = _format_for(max_height, prefer_res)
    opts = {
        "quiet": True,
        "no_warnings": True,
        "outtmpl": outtmpl,
        "format": fmt,
        "format_sort": fmt_sort,
        "merge_output_format": "mp4",
        # NOT ignoreerrors: a failed download must raise so it's reported and
        # never silently counted as "done" (which would leave an empty folder).
        "progress_hooks": [hook],
        "retries": 3,
        "concurrent_fragment_downloads": 4,
        # Ranged chunks bypass YouTube's per-request speed throttling.
        "http_chunk_size": 10 * 1024 * 1024,
        # Random human-like pause before each download so the account isn't
        # flagged for rapid-fire scraping.
        "sleep_interval": DOWNLOAD_SLEEP[0],
        "max_sleep_interval": DOWNLOAD_SLEEP[1],
    }
    # aria2c pulls each stream over many parallel connections — much faster.
    aria2c = _which("aria2c")
    if aria2c:
        c = str(max(1, conns))
        opts["external_downloader"] = {"default": aria2c}
        opts["external_downloader_args"] = {
            "aria2c": ["-x", c, "-s", c, "-k", "1M", "--summary-interval=0"],
        }
    _engine_opts(opts, cookies_browser, video["url"], cookiefile)
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(video["url"], download=True)

    # Confirm a real, non-empty file actually landed — otherwise treat as a
    # failure so it isn't marked complete and the folder isn't left empty.
    paths = [d.get("filepath") for d in (info.get("requested_downloads") or [])
             if d.get("filepath")]
    if not any(p and os.path.isfile(p) and os.path.getsize(p) > 0 for p in paths):
        raise RuntimeError("no output file was produced "
                           "(video may be private, region-locked, or download-protected)")


def run_jobs(urls, sort_key, top_n, scan_limit, dest, cookies_browser, cookiefile,
             max_height, parallel, prefer_res, log, status, progress, source, should_stop):
    """Top-level pipeline: process each source URL sequentially, A then B then C.

    sort_key is "view_count", "like_count", or "latest". "latest" skips the
    per-video metadata fetch entirely — listings already come back newest-first.

    Within a source, up to `parallel` videos download concurrently; sources
    themselves stay sequential (source B starts only after A finishes).

    Progress is reported per source via `source(idx, status=…, done=…, total=…)`,
    and completed videos are recorded in a state file so an interrupted run can
    be resumed by simply running the same batch again.
    """
    parallel = max(1, int(parallel))
    label = {"like_count": "likes", "view_count": "views"}.get(sort_key, "latest")
    state = DownloadState(dest)

    for idx, url in enumerate(urls, 1):
        if should_stop():
            raise Cancelled()
        platform = _platform(url)
        status(f"Source {idx}/{len(urls)}")
        log(f"\n=== [{idx}/{len(urls)}] {url} ===")
        source(idx, status="Listing…")

        # For "latest" we only need the first top_n entries; cap the listing too.
        eff_scan = top_n if sort_key == "latest" else scan_limit
        try:
            videos = list_channel_videos(url, eff_scan, cookies_browser, cookiefile,
                                         log, should_stop)
        except Cancelled:
            raise
        except Exception as exc:
            log(f"  ! Failed to read source: {exc}")
            source(idx, status="Failed (could not read)")
            continue

        if not videos:
            log("  ! No videos found, skipping.")
            source(idx, status="No videos found")
            continue

        if sort_key == "latest":
            top = videos[:top_n] if top_n > 0 else videos
            log(f"  Taking {len(top)} most-recent videos (no ranking needed).")
        else:
            source(idx, status="Ranking…")
            top = rank_videos(videos, sort_key, top_n, cookies_browser, cookiefile,
                              log, should_stop, progress)
            log(f"  Downloading top {len(top)} by {label} →")

        total = len(top)
        # Count what's already done from a previous run (resume).
        already = sum(1 for v in top if state.is_done(platform, v["id"]))
        counter = {"done": already}
        clock = threading.Lock()
        if already:
            log(f"  Resuming: {already}/{total} already downloaded previously.")
        source(idx, status="Downloading", done=already, total=total)

        live = parallel == 1  # in-place progress only makes sense one-at-a-time
        # Spread a modest total connection budget across the parallel videos,
        # so we never open an aggressive number of sockets at once.
        conns = max(2, TOTAL_CONNS // parallel)

        def bump():
            with clock:
                counter["done"] += 1
                source(idx, done=counter["done"], total=total)

        def grab(item):
            n, v = item
            if should_stop():
                return
            if state.is_done(platform, v["id"]):
                log(f"    [{n}/{total}] already downloaded — skipping.")
                return
            if sort_key == "latest":
                log(f"    [{n}/{total}] {v['title']}")
            else:
                log(f"    [{n}/{total}] {v['title']}  ({v.get(sort_key, 0):,} {label})")
            try:
                download_video(v, dest, url, cookies_browser, cookiefile, max_height,
                               log, should_stop, tag=f"[{n}] " if not live else "",
                               live=live, conns=conns, prefer_res=prefer_res)
                state.mark_done(platform, v["id"])  # persist for resume
                bump()
            except DownloadCancelled:
                pass  # stop requested; other workers wind down the same way
            except Exception as exc:
                log(f"      [{n}] ! download error: {exc}")

        items = list(enumerate(top, 1))
        if parallel == 1:
            for it in items:
                if should_stop():
                    raise Cancelled()
                grab(it)
        else:
            with ThreadPoolExecutor(max_workers=parallel) as pool:
                list(pool.map(grab, items))

        if should_stop():
            source(idx, status="Stopped", done=counter["done"], total=total)
            raise Cancelled()

        source(idx, status="Done ✓", done=counter["done"], total=total)
        log(f"  ✓ Finished source {idx} ({counter['done']}/{total}).")

    log("\nAll done.")


# ---------------------------------------------------------------------------
# GUI
# ---------------------------------------------------------------------------

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Video Bulk Downloader — YouTube · TikTok · Snapchat")
        self.geometry("760x760")
        self.minsize(640, 640)

        self.msg_q = queue.Queue()
        self.stop_flag = threading.Event()
        self.worker = None
        self.pot_proc = None  # PO-token provider subprocess, if we started it
        self._last_replaceable = False  # for in-place progress lines in the log

        self._build_ui()
        self._sync_scan_state()
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.after(100, self._drain_queue)
        # macOS system-Tk 8.5 sometimes shows a blank window until it gets a
        # resize/focus event — nudge it so the widgets paint immediately.
        self.after(60, self._force_paint)

    def _force_paint(self):
        self.update_idletasks()
        self.lift()
        self.attributes("-topmost", True)
        self.after(200, lambda: self.attributes("-topmost", False))
        w, h = self.winfo_width(), self.winfo_height()
        self.geometry(f"{w + 1}x{h + 1}")
        self.geometry(f"{w}x{h}")
        self.focus_force()

    # ---- layout ----------------------------------------------------------
    def _build_ui(self):
        pad = {"padx": 10, "pady": 6}

        ttk.Label(self, text="Channel / profile / video URLs (one per line):").pack(
            anchor="w", **pad)
        self.urls_text = tk.Text(self, height=6, wrap="none")
        self.urls_text.pack(fill="x", padx=10)
        self.urls_text.insert("1.0", "https://www.youtube.com/@channelname\n"
                                      "https://www.tiktok.com/@username\n"
                                      "https://www.snapchat.com/spotlight/...  (single clips only)")

        opts = ttk.Frame(self)
        opts.pack(fill="x", **pad)

        # Select top N by
        ttk.Label(opts, text="Select top N by:").grid(row=0, column=0, sticky="w")
        self.sort_var = tk.StringVar(value="view_count")
        ttk.Radiobutton(opts, text="View count", value="view_count",
                        variable=self.sort_var, command=self._sync_scan_state
                        ).grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(opts, text="Like count", value="like_count",
                        variable=self.sort_var, command=self._sync_scan_state
                        ).grid(row=0, column=2, sticky="w")
        ttk.Radiobutton(opts, text="Latest (newest)", value="latest",
                        variable=self.sort_var, command=self._sync_scan_state
                        ).grid(row=0, column=3, sticky="w")

        # Plain Entry boxes (not Spinbox) for the number fields: no min/max cap
        # and no keystroke validation, so any number can be typed freely. The
        # values are parsed safely with _read_int when the run starts.

        # Top N — this is the number of videos actually downloaded per source,
        # in every mode (its label updates for "Latest" so that's clear).
        self.topn_label = ttk.Label(opts, text="Top N per source:")
        self.topn_label.grid(row=1, column=0, sticky="w", pady=4)
        self.topn_var = tk.StringVar(value="50")
        ttk.Entry(opts, textvariable=self.topn_var, width=10).grid(
            row=1, column=1, sticky="w")

        # Max quality
        ttk.Label(opts, text="Max quality:").grid(row=1, column=2, sticky="e", padx=(10, 4))
        self.quality_var = tk.StringVar(value="1080p")
        ttk.Combobox(opts, textvariable=self.quality_var, width=8, state="readonly",
                     values=["Best", "2160p", "1440p", "1080p", "720p", "480p", "360p"]
                     ).grid(row=1, column=3, sticky="w")

        # Scan limit (only used for view/like ranking — "Latest" doesn't need it)
        self.scan_label = ttk.Label(opts, text="Scan most-recent videos:")
        self.scan_label.grid(row=2, column=0, sticky="w")
        self.scan_var = tk.StringVar(value="200")
        self.scan_spin = ttk.Entry(opts, textvariable=self.scan_var, width=10)
        self.scan_spin.grid(row=2, column=1, sticky="w")
        self.scan_hint = ttk.Label(opts, text="(0 = every video — no limit; slower for big channels)",
                                   foreground="#666")
        self.scan_hint.grid(row=2, column=2, columnspan=2, sticky="w")

        # Parallel downloads
        ttk.Label(opts, text="Parallel downloads:").grid(row=3, column=0, sticky="w", pady=4)
        self.parallel_var = tk.StringVar(value="2")
        ttk.Spinbox(opts, from_=1, to=6, textvariable=self.parallel_var,
                    width=8).grid(row=3, column=1, sticky="w")
        ttk.Label(opts, text="(videos at once, per channel; keep it low — 1–2 is gentlest)",
                  foreground="#666").grid(row=3, column=2, columnspan=2, sticky="w")

        # Codec / resolution preference
        self.prefer_res_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            opts,
            text="Prefer highest resolution (may be HEVC — can play silently in some players)",
            variable=self.prefer_res_var,
        ).grid(row=4, column=0, columnspan=4, sticky="w", pady=4)

        # Destination
        dest_frame = ttk.Frame(self)
        dest_frame.pack(fill="x", **pad)
        ttk.Label(dest_frame, text="Download folder:").pack(side="left")
        self.dest_var = tk.StringVar(value=os.path.expanduser("~/Downloads"))
        ttk.Entry(dest_frame, textvariable=self.dest_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(dest_frame, text="Browse…", command=self._pick_folder).pack(side="left")

        # Cookies / sign-in
        cookie_frame = ttk.Frame(self)
        cookie_frame.pack(fill="x", **pad)
        ttk.Label(cookie_frame, text="Use sign-in cookies from browser:").pack(side="left")
        self.cookie_var = tk.StringVar(value="chrome")
        ttk.Combobox(cookie_frame, textvariable=self.cookie_var, width=12, state="readonly",
                     values=["none", "chrome", "safari", "firefox", "edge", "brave"]
                     ).pack(side="left", padx=6)
        ttk.Label(cookie_frame,
                  text="(YouTube & TikTok need a logged-in browser; pick one you use)",
                  foreground="#666").pack(side="left")

        # Optional cookies.txt file (overrides the browser dropdown) — for use
        # with exports from the "Get cookies.txt LOCALLY" extension, most useful
        # when live browser-cookie reads are blocked (e.g. encrypted Chrome).
        cf_frame = ttk.Frame(self)
        cf_frame.pack(fill="x", **pad)
        ttk.Label(cf_frame, text="…or cookies.txt file (optional, overrides above):").pack(side="left")
        self.cookiefile_var = tk.StringVar(value="")
        ttk.Entry(cf_frame, textvariable=self.cookiefile_var).pack(
            side="left", fill="x", expand=True, padx=6)
        ttk.Button(cf_frame, text="Browse…", command=self._pick_cookiefile).pack(side="left")
        ttk.Button(cf_frame, text="Clear",
                   command=lambda: self.cookiefile_var.set("")).pack(side="left", padx=(6, 0))

        ttk.Label(self,
                  text="YouTube & TikTok: paste a channel/profile URL to rank & grab the "
                       "top N. Snapchat: paste individual Spotlight clip links only (no "
                       "profile listing exists). Polite mode is built in — human-like "
                       "delays + low concurrency; \"Latest\" is gentlest. Keep batches "
                       "reasonable.",
                  foreground="#a60", wraplength=720, justify="left").pack(anchor="w", padx=10)

        # Buttons
        btns = ttk.Frame(self)
        btns.pack(fill="x", **pad)
        self.start_btn = ttk.Button(btns, text="Start download", command=self._start)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=6)

        self.status_var = tk.StringVar(value="Idle.")
        ttk.Label(self, textvariable=self.status_var, foreground="#0a6").pack(
            anchor="w", padx=10)

        # Per-source progress table
        ttk.Label(self, text="Sources (progress + resume status):").pack(
            anchor="w", padx=10, pady=(6, 0))
        src_frame = ttk.Frame(self)
        src_frame.pack(fill="x", padx=10)
        self.src_tree = ttk.Treeview(src_frame, columns=("url", "status", "progress"),
                                     show="headings", height=5)
        self.src_tree.heading("url", text="Source")
        self.src_tree.heading("status", text="Status")
        self.src_tree.heading("progress", text="Downloaded")
        self.src_tree.column("url", width=430, anchor="w")
        self.src_tree.column("status", width=150, anchor="w")
        self.src_tree.column("progress", width=110, anchor="center")
        self.src_tree.pack(side="left", fill="x", expand=True)
        src_sb = ttk.Scrollbar(src_frame, command=self.src_tree.yview)
        src_sb.pack(side="right", fill="y")
        self.src_tree.config(yscrollcommand=src_sb.set)
        self.src_rows = {}  # source index -> treeview item id

        # Log
        ttk.Label(self, text="Log:").pack(anchor="w", padx=10, pady=(6, 0))
        log_frame = ttk.Frame(self)
        log_frame.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.log_text = tk.Text(log_frame, wrap="word", state="disabled",
                                background="#111", foreground="#ddd",
                                insertbackground="#ddd")
        self.log_text.pack(side="left", fill="both", expand=True)
        sb = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        sb.pack(side="right", fill="y")
        self.log_text.config(yscrollcommand=sb.set)

    # ---- actions ---------------------------------------------------------
    def _sync_scan_state(self):
        """Grey out the scan field for "Latest" (it doesn't rank) and relabel the
        count field so it's clear which box sets how many videos to download."""
        latest = self.sort_var.get() == "latest"
        state = "disabled" if latest else "normal"
        color = "#aaa" if latest else "#000"
        self.scan_spin.config(state=state)
        self.scan_label.config(foreground=color)
        self.scan_hint.config(foreground="#aaa" if latest else "#666")
        # In Latest mode the count IS the number of newest videos to download.
        self.topn_label.config(
            text="How many latest videos:" if latest else "Top N per source:")

    @staticmethod
    def _read_int(var, default):
        """Parse a number field, tolerating spaces, commas, or junk."""
        try:
            return int(str(var.get()).strip().replace(",", "") or default)
        except (ValueError, tk.TclError):
            return default

    def _quality_height(self):
        q = self.quality_var.get()
        return 0 if q == "Best" else int(q.rstrip("p"))

    def _pick_folder(self):
        folder = filedialog.askdirectory(initialdir=self.dest_var.get() or os.path.expanduser("~"))
        if folder:
            self.dest_var.set(folder)

    def _pick_cookiefile(self):
        path = filedialog.askopenfilename(
            title="Select cookies.txt",
            initialdir=os.path.expanduser("~/Downloads"),
            filetypes=[("Cookies text file", "*.txt"), ("All files", "*.*")])
        if path:
            self.cookiefile_var.set(path)

    def _start(self):
        urls = [u.strip() for u in self.urls_text.get("1.0", "end").splitlines() if u.strip()]
        if not urls:
            messagebox.showerror("Missing input", "Please enter at least one channel URL.")
            return
        dest = self.dest_var.get().strip()
        if not dest:
            messagebox.showerror("Missing folder", "Please pick a download folder.")
            return
        try:
            os.makedirs(dest, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("Bad folder", f"Cannot create folder:\n{exc}")
            return

        sort_key = self.sort_var.get()
        top_n = max(1, self._read_int(self.topn_var, 50))
        scan_limit = self._read_int(self.scan_var, 0)
        cookies_browser = self.cookie_var.get()
        cookiefile = self.cookiefile_var.get().strip() or None
        if cookiefile and not os.path.isfile(cookiefile):
            messagebox.showerror("Bad cookies file",
                                 f"cookies.txt not found:\n{cookiefile}")
            return
        max_height = self._quality_height()
        parallel = max(1, self._read_int(self.parallel_var, 2))
        prefer_res = bool(self.prefer_res_var.get())

        # (Re)build the per-source table; rows update live as the run proceeds.
        self.src_tree.delete(*self.src_tree.get_children())
        self.src_rows = {}
        for i, u in enumerate(urls, 1):
            self.src_rows[i] = self.src_tree.insert("", "end", values=(u, "Queued", "—"))

        self.stop_flag.clear()
        self.start_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self._set_status("Starting…")

        self.worker = threading.Thread(
            target=self._worker_main,
            args=(urls, sort_key, top_n, scan_limit, dest, cookies_browser, cookiefile,
                  max_height, parallel, prefer_res),
            daemon=True,
        )
        self.worker.start()

    def _stop(self):
        self.stop_flag.set()
        self._set_status("Stopping… (finishing current step)")
        self.stop_btn.config(state="disabled")

    def _on_close(self):
        self.stop_flag.set()
        if self.pot_proc is not None:
            try:
                self.pot_proc.terminate()
            except Exception:
                pass
        self.destroy()

    # ---- worker thread bridge -------------------------------------------
    def _worker_main(self, urls, sort_key, top_n, scan_limit, dest, cookies_browser,
                     cookiefile, max_height, parallel, prefer_res):
        def log(msg, replace=False):
            self.msg_q.put(("log", msg, replace))

        def status(msg):
            self.msg_q.put(("status", msg, False))

        def progress(msg):
            self.msg_q.put(("status", msg, False))

        def source(idx, status=None, done=None, total=None):
            self.msg_q.put(("source",
                            {"idx": idx, "status": status, "done": done, "total": total},
                            False))

        try:
            # The PO-token provider is only needed for YouTube; skip it otherwise.
            if self.pot_proc is None and any(_platform(u) == "youtube" for u in urls):
                self.pot_proc = ensure_pot_server(log)
            run_jobs(urls, sort_key, top_n, scan_limit, dest, cookies_browser, cookiefile,
                     max_height, parallel, prefer_res, log, status, progress, source,
                     self.stop_flag.is_set)
            self.msg_q.put(("done", "Finished.", False))
        except Cancelled:
            self.msg_q.put(("done", "Stopped by user.", False))
        except Exception:
            self.msg_q.put(("log", "FATAL:\n" + traceback.format_exc(), False))
            self.msg_q.put(("done", "Error — see log.", False))

    def _drain_queue(self):
        try:
            while True:
                kind, msg, replace = self.msg_q.get_nowait()
                if kind == "log":
                    self._append_log(msg, replace)
                elif kind == "status":
                    self._set_status(msg)
                elif kind == "source":
                    self._update_source(msg)
                elif kind == "done":
                    self._set_status(msg)
                    self.start_btn.config(state="normal")
                    self.stop_btn.config(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._drain_queue)

    def _update_source(self, p):
        """Merge a partial per-source update into its table row."""
        iid = self.src_rows.get(p["idx"])
        if not iid:
            return
        url, status, progress = self.src_tree.item(iid, "values")
        if p.get("status") is not None:
            status = p["status"]
        if p.get("total") is not None:
            progress = f"{p.get('done') or 0}/{p['total']}"
        self.src_tree.item(iid, values=(url, status, progress))

    def _append_log(self, msg, replace):
        self.log_text.config(state="normal")
        if replace and self._last_replaceable:
            # overwrite the last line for live percentage updates
            self.log_text.delete("end-2l", "end-1l")
        self.log_text.insert("end", msg + "\n")
        self.log_text.see("end")
        self.log_text.config(state="disabled")
        self._last_replaceable = replace

    def _set_status(self, msg):
        self.status_var.set(msg)


if __name__ == "__main__":
    App().mainloop()
