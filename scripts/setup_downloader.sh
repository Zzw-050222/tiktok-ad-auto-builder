#!/bin/bash
# 装「批量下载视频」要用的东西（macOS）。
#
# 目标：别人的电脑上双击【一键更新】，全程不用手动做任何事、【不用输密码】。
#
# 难点在这儿：ffmpeg 和 node 平常都是 brew 装的，可 brew 本身要管理员密码，
# 没装 brew 的电脑上就卡住了 —— 那就不叫「什么都不用操作」。
# 所以每一样都准备了不需要密码的退路：
#
#   ffmpeg  ── 有 brew 就 brew；没有就 pip 装 imageio-ffmpeg（自带一个 49MB 的
#              官方 ffmpeg 二进制），软链到 .bin/。合并音视频只需要 ffmpeg，
#              不需要 ffprobe，所以够用。
#   node    ── 有 brew 就 brew；没有就从 nodejs.org 下官方 tar.gz 解压到 .node/，
#              解压即用，自带 npm。
#   aria2c  ── 只影响速度，装不上就算了，不拦路。
#
# 可以重复执行：已经装好的会跳过，所以每次更新都跑一遍没关系。
# 任何一步失败都【不会】让外面的更新脚本挂掉 —— 下载功能装不上是小事，
# 不能因此把搭建功能的更新也带崩。

DL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/yt-bulk-downloader"
BIN_DIR="$DL_DIR/.bin"
NODE_DIR="$DL_DIR/.node"
NPM_CACHE="$DL_DIR/.npm-cache"
POT_SERVER="$DL_DIR/pot-provider/server"

step() { printf "  \033[36m·\033[0m %s\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
bad()  { printf "  \033[33m!\033[0m %s\n" "$1"; }

[ -d "$DL_DIR" ] || { echo "  （没有 yt-bulk-downloader 文件夹，跳过）"; exit 0; }

mkdir -p "$BIN_DIR"
export PATH="$BIN_DIR:$NODE_DIR/bin:/opt/homebrew/bin:/usr/local/bin:$PATH"

have() { command -v "$1" >/dev/null 2>&1; }
BREW=""
have brew && BREW=1

case "$(uname -m)" in arm64) NARCH=arm64 ;; *) NARCH=x64 ;; esac


# ---------------------------------------------------------------- 1. Python 环境
if [ ! -x "$DL_DIR/.venv/bin/python" ]; then
  step "建下载器的 Python 环境…"
  # 优先用主程序那个 venv 的 python：一键安装已经挑过、确认过 >= 3.10。
  # 直接用系统 python3 是碰运气 —— macOS 自带的 /usr/bin/python3 是 3.9，
  # 而且 Finder 双击时 PATH 很窄，很容易正好拿到那一个。
  MAIN_PY="$(dirname "$DL_DIR")/venv/bin/python"
  [ -x "$MAIN_PY" ] || MAIN_PY="$(command -v python3)"
  if [ -z "$MAIN_PY" ] || ! "$MAIN_PY" -m venv "$DL_DIR/.venv" >/dev/null 2>&1; then
    bad "建 venv 失败，下载功能用不了（其它功能不受影响）"
    exit 0
  fi
fi

# venv 是从别的文件夹拷过来的话（比如整个文件夹被拷到另一台电脑、或者换了位置），
# 里面脚本的 shebang 还指着老路径，一调用就是 "bad interpreter"。统一改成当前路径。
# 只在【真的改了】的时候才吭声 —— 每个正常的 venv 里都有一堆
# #!.../.venv/bin/python，光凭「匹配到了」就报「已修正」是在撒谎。
FIXED=0
for f in "$DL_DIR/.venv/bin"/*; do
  [ -f "$f" ] || continue
  LINE=$(head -1 "$f" 2>/dev/null) || continue
  case "$LINE" in
    "#!$DL_DIR/.venv/bin/"*) continue ;;          # 已经是对的
    "#!"*"/.venv/bin/python"*) ;;                 # 指向别处的 venv，要改
    *) continue ;;
  esac
  OLD=${LINE#\#!}; OLD=${OLD%/bin/python*}
  [ -n "$OLD" ] || continue
  sed -i '' "s|$OLD|$DL_DIR/.venv|g" "$f" 2>/dev/null && FIXED=$((FIXED + 1))
done
[ "$FIXED" -gt 0 ] && ok "修正了 $FIXED 个指向旧路径的脚本（venv 是从别处拷来的）"

if ! "$DL_DIR/.venv/bin/python" -c "import yt_dlp" >/dev/null 2>&1; then
  step "装 yt-dlp 等依赖（要一会儿）…"
  "$DL_DIR/.venv/bin/pip" install -q --upgrade pip >/dev/null 2>&1
  if "$DL_DIR/.venv/bin/pip" install -q -r "$DL_DIR/requirements.txt" >/dev/null 2>&1; then
    ok "yt-dlp 依赖装好了"
  else
    bad "装 yt-dlp 依赖失败（网络？），下载功能用不了"
    exit 0
  fi
else
  ok "yt-dlp 已就绪"
fi


# ---------------------------------------------------------------- 2. ffmpeg
# 没有它，下载完合并音视频那一步会失败（YouTube 的视频一定要合并）。
if have ffmpeg; then
  ok "ffmpeg 已就绪"
else
  if [ -n "$BREW" ]; then
    step "用 Homebrew 装 ffmpeg…"
    brew install ffmpeg >/dev/null 2>&1
  fi
  if ! have ffmpeg; then
    # 免密码退路：pip 包里自带一个官方 ffmpeg 二进制
    step "没有 Homebrew，改用 pip 装 ffmpeg（约 50MB）…"
    if "$DL_DIR/.venv/bin/pip" install -q imageio-ffmpeg >/dev/null 2>&1; then
      FF=$("$DL_DIR/.venv/bin/python" -c \
        "import imageio_ffmpeg;print(imageio_ffmpeg.get_ffmpeg_exe())" 2>/dev/null)
      if [ -n "$FF" ] && [ -f "$FF" ]; then
        ln -sf "$FF" "$BIN_DIR/ffmpeg"
        chmod +x "$FF" 2>/dev/null
      fi
    fi
  fi
  if have ffmpeg; then ok "ffmpeg 装好了"; else bad "ffmpeg 没装上 —— YouTube 的视频会失败"; fi
fi


# ---------------------------------------------------------------- 3. node
# 只有 YouTube 的反机器人（PO-token 服务）要用；TikTok 不需要。
if have node; then
  ok "node 已就绪"
else
  if [ -n "$BREW" ]; then
    step "用 Homebrew 装 node…"
    brew install node >/dev/null 2>&1
  fi
  if ! have node; then
    step "没有 Homebrew，从 nodejs.org 下官方版（约 50MB）…"
    NV=$(curl -fsSL --max-time 30 https://nodejs.org/dist/index.json 2>/dev/null \
         | python3 -c "import json,sys;d=json.load(sys.stdin);print([x for x in d if x.get('lts')][0]['version'])" 2>/dev/null)
    if [ -n "$NV" ]; then
      TGZ=$(mktemp -t nodetgz).tgz
      if curl -fsSL --max-time 300 \
           "https://nodejs.org/dist/$NV/node-$NV-darwin-$NARCH.tar.gz" -o "$TGZ" 2>/dev/null \
         && tar -tzf "$TGZ" >/dev/null 2>&1; then
        rm -rf "$NODE_DIR"; mkdir -p "$NODE_DIR"
        tar -xzf "$TGZ" -C "$NODE_DIR" --strip-components=1 2>/dev/null
      fi
      rm -f "$TGZ"
    fi
  fi
  if have node; then ok "node 装好了（$(node --version)）"; else bad "node 没装上 —— YouTube 会 403，TikTok 不受影响"; fi
fi


# ---------------------------------------------------------------- 4. PO-token 服务的依赖
if [ -d "$POT_SERVER/node_modules" ]; then
  ok "YouTube 反机器人服务已就绪"
elif have npm; then
  step "装 YouTube 反机器人服务的依赖…"
  # --cache 指到项目里：见过一台机器的 ~/.npm 里有 60 个文件属于 root
  # （以前 sudo npm 留下的），用默认缓存会直接权限报错，而修它要 sudo。
  # 换个缓存目录就完全绕开了，不用碰系统目录、也不用密码。
  if (cd "$POT_SERVER" && npm install --omit=dev --no-audit --no-fund \
        --cache "$NPM_CACHE" >/dev/null 2>&1); then
    ok "YouTube 反机器人服务装好了"
  else
    bad "它的依赖没装上 —— YouTube 会 403，TikTok 不受影响"
  fi
else
  bad "没有 npm，YouTube 反机器人服务装不了（TikTok 不受影响）"
fi


# ---------------------------------------------------------------- 5. aria2c（可选）
if have aria2c; then
  ok "aria2c 已就绪（下载更快）"
elif [ -n "$BREW" ]; then
  step "装 aria2c（可选，只影响速度）…"
  brew install aria2 >/dev/null 2>&1
  have aria2c && ok "aria2c 装好了" || bad "aria2c 没装上，下载会慢一点（不影响成功率）"
else
  bad "没装 aria2c，下载会慢一点（不影响成功率）"
fi

exit 0
