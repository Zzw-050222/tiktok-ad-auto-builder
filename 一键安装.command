#!/bin/bash
# 一键安装（macOS）—— 全新电脑上装这个程序，双击这个文件就行。
#
# 为什么要有这个文件：原来的说明书让人手敲三行命令
#     python3 -m venv venv
#     venv/bin/pip install -r requirements.txt
#     venv/bin/playwright install chromium
# 这三行【必须在 auto-builder 文件夹里】敲。实际发生的是：终端一打开在用户主目录，
# 直接粘进去 —— 于是在主目录建了个没用的 venv，然后报
#     ERROR: Could not open requirements file: 'requirements.txt'
#     zsh: no such file or directory: venv/bin/playwright
# 说明书没写「先 cd 进文件夹」，这是说明书的问题，不是使用者的问题。
# 双击运行的脚本自己知道自己在哪，不会有这个问题。
#
# 它做的事：
#   1. 确认自己确实在 auto-builder 文件夹里（不在就直接说清楚，不瞎跑）
#   2. 解掉 macOS 的「下载隔离」标记
#   3. 检查 Python
#   4. 建 venv、装依赖、装 Chromium 浏览器
#   5. 把文件夹接到 GitHub，以后双击「一键更新」就能拉最新版
#   6. 自检：真的能 import、Chromium 真的装上了
#
# 重复运行是安全的：装好的不会重装，登录态和表格一根手指都不碰。

cd "$(dirname "$0")" || exit 1

REPO="https://github.com/Zzw-050222/tiktok-ad-auto-builder.git"

say()  { printf "\n\033[1m%s\033[0m\n" "$1"; }
ok()   { printf "  \033[32m✓\033[0m %s\n" "$1"; }
warn() { printf "  \033[33m!\033[0m %s\n" "$1"; }
die()  { printf "\n\033[31m✗ %s\033[0m\n\n按回车关闭。\n" "$1"; read -r _; exit 1; }

say "TikTok 广告自动搭建 · 一键安装"
echo "文件夹：$(pwd)"

# ---- 1. 先确认位置对不对 ----
# 这一步就是为了挡住上面说的那个坑：脚本被单独拷到别处、或者文件夹解压得不完整时，
# 与其装出一个跑不起来的半成品，不如立刻说清楚。
if [ ! -f requirements.txt ] || [ ! -f app.py ]; then
  die "这个文件夹里没有 requirements.txt 或 app.py，不像是 auto-builder 程序文件夹。
把「一键安装.command」放回解压出来的 auto-builder 文件夹里再双击。
（解压后里面应该能看到 app.py、run_web.sh、src 这些东西）"
fi
ok "位置正确"

# ---- 2. 解掉「下载隔离」----
# 从浏览器下载的 zip，解压出来的每个文件都带 com.apple.quarantine 标记，
# 双击 .command 会弹「无法打开，因为无法验证开发者」。这里一次性去掉，
# 免得使用者还要对每个文件右键→打开。
if command -v xattr >/dev/null 2>&1; then
  xattr -dr com.apple.quarantine . >/dev/null 2>&1
  ok "已解除 macOS 下载隔离标记"
fi
chmod +x run_web.sh 启动.command 一键安装.command 一键更新.command >/dev/null 2>&1

# ---- 3. 检查 Python ----
# 全新的 Mac 上 python3 只是个占位命令，第一次调用会弹「需要安装命令行开发者工具」，
# 命令本身返回失败。所以要试着真的执行一下，不能只看命令存不存在。
if ! python3 --version >/dev/null 2>&1; then
  die "这台电脑还不能用 python3。
多半是没装「命令行开发者工具」——刚才可能已经弹了个安装窗口，点【安装】等它装完
（要几分钟），然后重新双击本文件。
如果没弹窗，在【终端】里执行：xcode-select --install"
fi
PYV=$(python3 -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null)
PYOK=$(python3 -c 'import sys; print(1 if sys.version_info[:2] >= (3,10) else 0)' 2>/dev/null)
if [ "$PYOK" != "1" ]; then
  die "Python 版本太老了（当前 $PYV），这个程序要 3.10 以上。
去 https://www.python.org/downloads/ 装一个新的，装完重新双击本文件。"
fi
ok "Python $PYV"

# ---- 4. 建运行环境 ----
# venv 是个「只属于这个程序的 Python 环境」，装的东西不会污染整台电脑。
NEED_INSTALL=0
if [ ! -d venv ]; then
  NEED_INSTALL=1
else
  # 已经有 venv，但可能是上次装到一半断掉的残骸。真去 import 一下才算数。
  if ! venv/bin/python -c "import flask, openpyxl, playwright, requests, dotenv" >/dev/null 2>&1; then
    warn "已有的运行环境不完整（上次可能装到一半中断了），重装一遍"
    rm -rf venv
    NEED_INSTALL=1
  else
    ok "运行环境已存在"
  fi
fi

if [ "$NEED_INSTALL" = "1" ]; then
  say "正在装运行环境，要几分钟，别关窗口…"
  python3 -m venv venv || die "创建 venv 失败。"
  venv/bin/python -m pip install --upgrade pip --quiet
  echo "  装依赖（flask / playwright / openpyxl …）"
  venv/bin/pip install -r requirements.txt || die "装依赖失败。检查一下网络。"
  ok "依赖装好了"
fi

# ---- 5. 装 Chromium ----
# 程序是靠这个浏览器去点 TikTok 后台的，没有它整个程序跑不起来。
# 约 150MB，第一次装最慢的就是这一步。
if venv/bin/python -c "
from playwright.sync_api import sync_playwright
import pathlib, sys
with sync_playwright() as p:
    sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)
" >/dev/null 2>&1; then
  ok "Chromium 浏览器已装好"
else
  say "正在装 Chromium 浏览器（约 150MB，别关窗口）…"
  venv/bin/playwright install chromium || die "装 Chromium 失败。检查一下网络。"
  ok "Chromium 装好了"
fi

# ---- 6. 接到 GitHub，方便以后一键更新 ----
# 从 zip 解压出来的文件夹没有 .git，接上之后双击「一键更新」就能拉最新代码。
# 代码仓库是【公开】的，不用登录 GitHub 也能拉。
#
# git 能不能用不能写成 command -v git ——没装「命令行开发者工具」的 Mac 上
# /usr/bin/git 照样存在，判断会通过，然后真去调用才弹「"git" 命令需要使用
# 命令行开发者工具」的窗口。也不能靠「跑一下 git --version 试试」：那一下本身
# 就会把弹窗招出来。所以只认「不是苹果占位符」或「开发者工具确实装好了」。
git_usable() {
  local g
  g=$(command -v git 2>/dev/null) || return 1
  [ -n "$g" ] || return 1
  if [ "$g" = "/usr/bin/git" ]; then
    xcode-select -p >/dev/null 2>&1 || return 1
  fi
  return 0
}

if git_usable; then
  if [ ! -d .git ]; then
    git init -q >/dev/null 2>&1
    git remote add origin "$REPO" >/dev/null 2>&1
    ok "已接到 GitHub（以后双击「一键更新.command」就能拿最新版）"
  else
    git remote set-url origin "$REPO" >/dev/null 2>&1 || true
    ok "已接到 GitHub"
  fi
else
  # 不是错误，也不用装 git：一键更新里有一条 curl 的退路，不需要开发者工具。
  warn "这台电脑用不了 git（没装「命令行开发者工具」）——不影响使用。
    以后双击「一键更新.command」会自动改用直接下载的方式，一样能更新。"
fi

# ---- 7. 自检 ----
# 不做自检的话，「装完了」只是「命令没报错」，不等于真的能跑。
say "自检"
venv/bin/python -c "import flask, openpyxl, playwright, requests, dotenv" 2>/dev/null \
  && ok "依赖都能加载" || die "依赖装了但加载不了，把上面的输出发给开发者。"
venv/bin/python -c "
from playwright.sync_api import sync_playwright
import pathlib
with sync_playwright() as p:
    exe = pathlib.Path(p.chromium.executable_path)
    assert exe.exists(), exe
    print('  \033[32m✓\033[0m Chromium 可用')
" 2>/dev/null || die "Chromium 没装上。重新双击本文件再试一次。"
venv/bin/python -c "import app" >/dev/null 2>&1 \
  && ok "程序本体能加载" || warn "程序本体加载有问题，启动时如果报错请把日志发给开发者"

say "✓ 装好了"
cat <<'TXT'
接下来：
  1. 双击【启动.command】（第一次可能要右键 →「打开」→「打开」）
  2. 浏览器会自动打开 http://127.0.0.1:5050
  3. 在网页第 2 步点【登录 / 换账号】，登录自己的 BC 账号
     ——登录态只存在这台电脑上，程序里没有任何账号密码

以后要更新：双击【一键更新.command】，登录态、日志、表格都不会丢。
TXT
printf "\n按回车关闭。\n"
read -r _
