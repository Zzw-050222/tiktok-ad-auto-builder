# Video Bulk Downloader — YouTube · TikTok · Snapchat

Paste several channel/profile URLs, pick how many top videos to keep per source
(ranked by **view count**, **like count**, or just **latest**), choose a
download folder, and the tool downloads each source's top-N **one at a time** —
it finishes source A's list before starting source B.

## Supported sites

| Site | Paste a channel/profile to rank top-N? | Notes |
|------|----------------------------------------|-------|
| **YouTube** | ✅ | Needs the full anti-bot stack (auto-handled). |
| **TikTok**  | ✅ | View/like counts come free in the listing, so ranking needs **no** extra per-video requests — fastest & gentlest. |
| **Snapchat**| ❌ | yt-dlp has no profile extractor. Paste **individual Spotlight clip links** only; each is downloaded directly (no ranking). |

You can mix sites in one batch — each URL is detected automatically.

**TikTok handles that won't open:** TikTok can't always resolve a bare
`@handle` (you'll see "Unable to extract secondary user ID"). Workaround: open
**any video** from that account in your browser and paste **that video's URL**
instead — the tool reads the account from it and grabs the whole account's
top-N. If TikTok also refuses to list that account (some repost/"short-drama"
accounts return an empty list), the tool falls back to downloading just the
video URL you pasted, so you still get something.

**"Says downloaded but the folder is empty":** every download is now verified —
if no real file lands, it's reported as an error (not a silent success) and is
**not** marked complete, so re-running will retry it. A frequent cause is TikTok
temporarily blocking you with **HTTP 403** after many rapid requests; wait a
while (and/or set cookies) before retrying. Files are saved in a per-uploader
**subfolder** (`<download folder>/<uploader>/…`) — check there, not the top level.

## Launch

Double-click **`run.command`** in Finder, or in Terminal:

```bash
cd ~/yt-bulk-downloader
./run.command          # or: .venv/bin/python app.py
```

## How to use

1. **URLs** — one channel per line (`https://www.youtube.com/@handle`, `.../channel/UC...`, etc.).
2. **Select top N by:**
   - **View count** / **Like count** — reads each candidate video's stats, then keeps the highest. Accurate but slower (it must probe every candidate).
   - **Latest (newest)** — just the most-recent N. No stat-probing, so it starts downloading almost immediately.
3. **Top N per channel** — e.g. `50`.
4. **Max quality** — caps resolution (default `1080p`). Lower = smaller files and faster downloads. `Best` grabs the highest available (can be 4K / multi-GB).
5. **Scan most-recent videos** — only used for View/Like ranking; caps how many recent videos get probed (default `200`, `0` = entire channel). Disabled for "Latest".
6. **Parallel downloads** — how many videos download at once *within* a channel (default `3`). Channels still run one at a time (A finishes before B). Because YouTube throttles each connection, 3–4 at once usually beats one; going too high risks rate-limiting.
7. **Download folder** — **Browse…** to pick. Saved as `<folder>/<channel>/<title> [id].mp4`.
8. **Use sign-in cookies from browser** — **required by YouTube and TikTok** (see below). Default Chrome; set it to a browser you're logged into those sites with.
9. **Start** / **Stop**.

## Why the browser-cookies setting matters

As of 2025–2026 YouTube blocks anonymous downloads ("confirm you're not a
bot" / `HTTP 403`). This tool gets around it automatically using **four**
pieces, all wired in for you:

- **Browser cookies** — a logged-in session (you choose the browser).
- **Node.js** — runs YouTube's JS signature challenge.
- **EJS solver** — downloaded from GitHub on first run.
- **PO-token provider** — a small local server (`bgutil`) the app **starts and
  stops automatically** on port 4416.

If downloads fail with `403`, the usual cause is the cookie browser: pick one
where you are actually signed into YouTube, and make sure it's closed-or-open
per that browser's cookie-locking rules (Chrome usually works either way).

### cookies.txt file (fallback)

If live browser-cookie reading fails (newer Chrome encrypts its cookie store),
export a **cookies.txt** with the **"Get cookies.txt LOCALLY"** Chrome extension
(Netscape format) and select it in the **"…or cookies.txt file"** box. When set,
it overrides the browser dropdown and is used for every request. This is the
most reliable way to pass identity/cookies for locked-down videos.

## Progress tracking & resume

- The **Sources** table shows each link with a live **Status** (Queued → Listing
  → Ranking → Downloading → **Done ✓** / Stopped / Failed) and a **Downloaded
  X/N** count.
- Every completed video is recorded in a hidden `.download_state.json` file in
  your download folder. If a run is interrupted (Stop, crash, or quitting), just
  **run the same batch again** — already-downloaded videos are skipped and the
  counts pick up where they left off (you'll see "Resuming: X/N already
  downloaded"). Delete that file to force a clean re-download.

## Speed

Downloads use **aria2c** (multiple connections per file) plus ranged chunking to
beat YouTube's per-connection throttling, and run several videos in **parallel**
(see "Parallel downloads"). The connection count per file is scaled down as
parallelism rises, so the total stays reasonable. The single biggest control you
have is **Max quality** — dropping from Best/4K to 1080p or 720p cuts file size
and time dramatically.

**Codec:** by default downloads prefer **H.264 video + AAC audio**, which plays
with sound in every player. This matters most on TikTok, whose higher tiers are
H.265 (HEVC) — many players show those silently or not at all — so the tool
picks the H.264 version (typically up to 720p on TikTok) instead. "Max quality"
caps on the **shorter** side, so it works correctly for vertical videos too.

Tick **"Prefer highest resolution (may be HEVC)"** to flip this: it grabs the
highest resolution available regardless of codec (e.g. TikTok 1080p, which is
HEVC-only). Use it when you want maximum quality and your player handles HEVC;
leave it off if you ever get silent or unplayable files.

## 第三方组件与许可证（重要）

`pot-provider/` 是外部开源项目 **bgutil-ytdlp-pot-provider**，按 **GPL-3.0** 授权
（许可证原文在 `pot-provider/LICENSE`）。本仓库其余部分是 MIT。

两者是**各自独立的程序**：Python 这边把它当成一个本地 HTTP 服务来调（`127.0.0.1:4416`），
不做代码级链接，属于 GPL 说的「聚合」（mere aggregation），所以 MIT 那部分不受影响。
但仓库里确实含有 GPL-3.0 的代码，根目录那份 MIT LICENSE 并不覆盖 `pot-provider/`。

不想在公开仓库里放它的话，可以把 `pot-provider/` 加进 .gitignore，改成安装时
从上游拉取 —— 代价是新电脑上多一步联网安装，YouTube 下载在装好之前用不了。

## Maintenance

- Update the engine occasionally: `.venv/bin/python -m pip install -U yt-dlp`
- Components used: `yt-dlp`, `ffmpeg`, `node`, `aria2c`, and the bundled
  `pot-provider/` (bgutil). All already installed.
