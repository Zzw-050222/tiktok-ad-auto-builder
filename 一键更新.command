#!/bin/bash
# 一键更新（macOS）—— 双击这个文件就行。
#
# 它做的事：从 GitHub 把最新代码拉下来覆盖掉旧代码，然后（首次或依赖有变时）
# 装好运行环境。你的登录态、日志、上传的表格都不会被动。
#
# 有 git 就走 git，没 git 就用 curl 下代码包覆盖 —— 两条路都不用登录 GitHub，
# 因为代码仓库是公开的。
#
# 为什么优先用 git reset --hard：
#   * 它只动【git 跟踪的文件】，也就是程序本体。venv/、browser_profile*（登录态）、
#     logs/、uploads/、你的 .xlsx 都是未跟踪的，它一根手指都不碰。
#   * 它会正确处理【新版本里删掉的文件】——解压覆盖做不到这一点，旧文件会一直留着。
#
# 为什么还要留一条 curl 的退路：全新的 Mac 上没有「命令行开发者工具」，
# /usr/bin/git 只是个【占位符】—— 一调用就弹「"git" 命令需要使用命令行开发者工具」
# 的窗口然后失败，而那个安装经常装不上（更新服务器取不到）。
# curl 和 tar 是 macOS 自带的真实程序，不需要开发者工具，所以这条路一定走得通。

set -e
cd "$(dirname "$0")"

REPO="https://github.com/Zzw-050222/tiktok-ad-auto-builder.git"
BRANCH="master"
TARBALL="https://codeload.github.com/Zzw-050222/tiktok-ad-auto-builder/tar.gz/refs/heads/$BRANCH"
API="https://api.github.com/repos/Zzw-050222/tiktok-ad-auto-builder/commits/$BRANCH"

say()  { printf "\n\033[1m%s\033[0m\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n\n按回车关闭。\n" "$1"; read -r _; exit 1; }

say "TikTok 广告自动搭建 · 一键更新"
echo "文件夹：$(pwd)"

# ---- git 到底能不能用 ----
# 不能写成 command -v git —— 没装开发者工具的 Mac 上 /usr/bin/git 照样存在，
# 判断会通过，然后真去调用才弹窗+失败。使用者截图里就是这一幕。
# 也不能靠「跑一下 git --version 试试」来判断：那一下本身就会把弹窗招出来。
# 所以：只有当 git 不是苹果那个占位符（比如 Homebrew 装的），
# 或者开发者工具确实装好了（xcode-select -p 能报出路径），才算 git 可用。
git_usable() {
  local g
  g=$(command -v git 2>/dev/null) || return 1
  [ -n "$g" ] || return 1
  if [ "$g" = "/usr/bin/git" ]; then
    xcode-select -p >/dev/null 2>&1 || return 1
  fi
  return 0
}

BEFORE_REQ=$(md5 -q requirements.txt 2>/dev/null || echo none)

if git_usable; then
  # ================= A. 有 git：最干净的一条路 =================

  # ---- 1. 没有 .git 就把它变成一个 git 仓库（当初是拷文件装的就会这样）----
  if [ ! -d .git ]; then
    say "第一次用这个工具，正在把文件夹接到 GitHub…"
    git init -q
    git remote add origin "$REPO"
  else
    # 远程地址对不上就纠正（比如以前指向别的仓库）
    git remote set-url origin "$REPO" 2>/dev/null || git remote add origin "$REPO"
  fi

  # ---- 2. 有人改过程序本体就先问一声，别默默覆盖掉 ----
  if [ -n "$(git status --porcelain --untracked-files=no 2>/dev/null)" ]; then
    say "注意：这台电脑上有人改过程序文件，更新会把这些改动覆盖掉："
    git status --short --untracked-files=no
    printf "\n要继续吗？[y/N] "
    read -r ans
    case "$ans" in [yY]*) ;; *) die "已取消，什么都没动。" ;; esac
  fi

  # ---- 3. 拉最新代码 ----
  say "正在从 GitHub 拉取最新代码…"
  OLD=$(git rev-parse --short HEAD 2>/dev/null || echo "（无）")

  git fetch --depth=1 origin "$BRANCH" || die "拉取失败。检查一下网络，或者这台电脑能不能访问 GitHub。"
  git reset --hard -q FETCH_HEAD || die "覆盖旧代码时出错了。"

  NEW=$(git rev-parse --short HEAD)
  if [ "$OLD" = "$NEW" ]; then
    echo "已经是最新版了（$NEW），代码没有变化。"
  else
    echo "代码：$OLD → $NEW"
    git --no-pager log --oneline -8 "$NEW" | sed 's/^/  /'
  fi

else
  # ================= B. 没 git：curl 下代码包覆盖 =================
  # 这台 Mac 没有「命令行开发者工具」，git 用不了。curl 和 tar 是系统自带的
  # 真实程序，不需要开发者工具，所以走这条。代码仓库是公开的，不用登录。
  say "这台电脑用不了 git，改用直接下载的方式更新…"
  echo "（原因：没装「命令行开发者工具」。不影响使用，程序本身不需要 git。）"

  command -v curl >/dev/null 2>&1 || die "这台电脑连 curl 都没有，没法自动更新了。
只能去私有仓库下载 auto-builder-最新版.zip，解压覆盖到这个文件夹。"

  TMPD=$(mktemp -d) || die "创建临时目录失败。"
  # set -e 下这里要保证清理一定发生
  trap 'rm -rf "$TMPD"' EXIT

  say "正在下载最新代码…"
  curl -fsSL "$TARBALL" -o "$TMPD/src.tgz" \
    || die "下载失败。检查一下网络，或者这台电脑能不能访问 github.com。"

  # 先验一下下来的是不是个正常的 tar.gz，别把坏文件解进程序文件夹
  tar -tzf "$TMPD/src.tgz" >/dev/null 2>&1 \
    || die "下载的文件是坏的（可能是网络被拦截了，下回来一个网页）。过一会儿再试。"

  # --strip-components=1 去掉压缩包最外面那层 tiktok-ad-auto-builder-master/
  # 只覆盖压缩包里有的文件；venv/、browser_profile*、logs/、你的 .xlsx
  # 压缩包里没有，所以一根手指都不碰。
  tar -xzf "$TMPD/src.tgz" -C . --strip-components=1 \
    || die "解压覆盖时出错了。"

  NEW=$(curl -fsSL "$API" 2>/dev/null \
        | /usr/bin/sed -n 's/^  "sha": "\(.......\).*/\1/p' | head -1)
  echo "已覆盖为最新代码${NEW:+（$NEW）}。"
  warn "这条路有个限制：只会新增/替换文件，【不会删掉】新版本里已经删除的旧文件。
    平时没影响。真要干干净净的一份，就装上开发者工具（xcode-select --install）
    之后再跑一次本文件，它会自动走 git 那条路。"

  rm -rf "$TMPD"
  trap - EXIT
fi

# ---- 4. 首次使用、或依赖有变，就装环境 ----
AFTER_REQ=$(md5 -q requirements.txt 2>/dev/null || echo none)
if [ ! -d venv ]; then
  say "第一次使用，正在装运行环境（要几分钟，别关窗口）…"
  python3 -m venv venv || die "创建 venv 失败。这台电脑要先装 Python 3.10 以上。"
  venv/bin/pip install -q --upgrade pip
  venv/bin/pip install -q -r requirements.txt || die "装依赖失败。"
  venv/bin/playwright install chromium || die "装浏览器失败。"
  echo "环境装好了。"
elif [ "$BEFORE_REQ" != "$AFTER_REQ" ]; then
  say "依赖有更新，正在重新安装…"
  venv/bin/pip install -q -r requirements.txt || die "装依赖失败。"
  echo "依赖已更新。"
fi

# 新拉下来的脚本也要给执行权限。git 自己会带 100755 过来，但从 zip 装的那批
# 文件夹里旧文件的权限位可能已经被解压工具改过，补一次不亏。
chmod +x run_web.sh 一键更新.command 一键安装.command 启动.command 2>/dev/null || true

# 从网上下的 zip 解压出来带 com.apple.quarantine，双击 .command 会弹
# 「无法验证开发者」。更新完顺手解一次，免得使用者每加一个新脚本就要右键一次。
#
# 只扫最外层的文件，不用 xattr -dr：递归会把 venv/ 和 browser_profile/ 里
# 几万个文件全走一遍，白等好几秒，而要双击的脚本本来就都在最外层。
if command -v xattr >/dev/null 2>&1; then
  find . -maxdepth 1 -type f -exec xattr -d com.apple.quarantine {} \; >/dev/null 2>&1 || true
fi

say "✓ 更新完成"
cat <<'TXT'
接下来：
  · 双击【启动.command】（或在终端执行 ./run_web.sh）
  · 浏览器打开 http://127.0.0.1:5050
  · 第一次用要在网页第 2 步点【登录 / 换账号】，登录自己的 BC 账号

你的登录态、日志、上传过的表格都没有被动。
TXT
printf "\n按回车关闭。\n"
read -r _
