#!/bin/bash
# 一键更新（macOS）—— 双击这个文件就行。
#
# 它做的事：从 GitHub 把最新代码拉下来覆盖掉旧代码，然后（首次或依赖有变时）
# 装好运行环境。你的登录态、日志、上传的表格都不会被动。
#
# 为什么用 git reset --hard 而不是解压 zip 覆盖：
#   * reset --hard 只动【git 跟踪的文件】，也就是程序本体。venv/、
#     browser_profile*（登录态）、logs/、uploads/、你的 .xlsx 都是未跟踪的，
#     它一根手指都不碰。
#   * 它会正确处理【新版本里删掉的文件】——解压覆盖做不到这一点，旧文件会一直留着。

set -e
cd "$(dirname "$0")"

REPO="https://github.com/Zzw-050222/tiktok-ad-auto-builder.git"
BRANCH="master"

say() { printf "\n\033[1m%s\033[0m\n" "$1"; }
die() { printf "\n\033[31m✗ %s\033[0m\n\n按回车关闭。\n" "$1"; read -r _; exit 1; }

say "TikTok 广告自动搭建 · 一键更新"
echo "文件夹：$(pwd)"

command -v git >/dev/null 2>&1 || die "这台电脑没装 git。装一下：在终端执行 xcode-select --install"

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
BEFORE_REQ=$(md5 -q requirements.txt 2>/dev/null || echo none)
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
