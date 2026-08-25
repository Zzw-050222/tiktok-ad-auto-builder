#!/bin/bash
# 把整个程序打成【一个 zip】，推到私有仓库，方便去别人电脑上更新时只拷一个文件。
#
# 为什么用 git archive 而不是直接 zip 整个文件夹：
#   git archive 只打包【公开仓库里跟踪的文件】，也就是程序本体。
#   venv/、browser_profile*（登录态）、logs/、uploads/、data/、各种 .xlsx 业务表格
#   本来就在 .gitignore 里，所以它们【不可能】被打进去——不用靠我一条条写排除规则，
#   少写一条就会把登录态或客户数据带出去。
#
# 用法（在项目文件夹里）：
#   ./打包最新版.sh
#
# 打出来的 zip 会推到私有仓库 tiktok-ad-builder-private-data，
# 到别人电脑上从那个仓库下载这一个文件就行。

set -e
cd "$(dirname "$0")"

ZIP_NAME="auto-builder-最新版.zip"
PRIVATE_GIT=".git-private-data"

# ---- 1. 检查有没有没提交的改动 ----
# git archive 打的是 HEAD（最后一次提交），工作区里没提交的改动【不会】进 zip。
if [ -n "$(git status --porcelain)" ]; then
  echo "⚠️  警告：工作区还有没提交的改动，它们不会被打进 zip："
  git status --short
  echo
  read -r -p "仍然按最后一次提交(HEAD)打包？[y/N] " ans
  case "$ans" in
    [yY]*) ;;
    *) echo "已取消。先 git commit 再来打包。"; exit 1 ;;
  esac
fi

COMMIT=$(git rev-parse --short HEAD)
BRANCH=$(git rev-parse --abbrev-ref HEAD)
NOW=$(date "+%Y-%m-%d %H:%M")

echo "==> 打包 commit $COMMIT（分支 $BRANCH）"

# ---- 2. 用 git archive 导出程序本体 ----
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
mkdir -p "$TMP/auto-builder"
git archive HEAD | tar -x -C "$TMP/auto-builder"

# ---- 3. 塞一张版本说明进去 ----
cat > "$TMP/auto-builder/版本.txt" <<TXT
打包时间: $NOW
代码版本: $COMMIT （分支 $BRANCH）
来源仓库: $(git remote get-url origin)

—— 装到一台新电脑 ——
1. 解压，把 auto-builder 文件夹放到你想放的地方（比如桌面）
2. 进到 auto-builder 文件夹里，双击：
       Mac    : 一键安装.command   （第一次要右键 →「打开」→「打开」）
       Windows: 一键安装.bat
   它会自己装好 Python 环境和 Chromium 浏览器，装完会自检一遍。要几分钟。
3. 装完双击：
       Mac    : 启动.command
       Windows: run_web.bat
4. 浏览器会自动打开 http://127.0.0.1:5050
5. 在网页第 2 步点【登录 / 换账号】，用自己的 BC 账号登录

不用手敲命令。以前这里写的是三行 python 命令，但那三行【必须在 auto-builder
文件夹里】敲——终端一打开在主目录，直接粘进去只会报「找不到 requirements.txt」。
双击的脚本自己知道自己在哪，不会有这个问题。

（也可以完全不用这个 zip：代码仓库是公开的，在终端里粘这一行就装好了
     git clone https://github.com/Zzw-050222/tiktok-ad-auto-builder.git ~/Desktop/auto-builder && cd ~/Desktop/auto-builder && bash 一键安装.command
 这条路不用下载 zip，也不会碰到 macOS 的「无法验证开发者」拦截。）

—— 更新一台已经装好的电脑 ——
双击【一键更新.command】(Mac) / 【一键更新.bat】(Windows) 就行，不用下这个 zip。

要用 zip 更新的话，把解压出来的文件【覆盖】到原来的文件夹即可。
venv/、browser_profile*（登录态）、logs/、uploads/、你的 .xlsx 表格都不在这个包里，
所以覆盖不会动它们，登录态和数据都还在。
如果 requirements.txt 变了，再跑一次 pip install -r requirements.txt。

注意：覆盖只会新增/替换文件，【不会删掉】新版本里已经删除的旧文件。
想要干干净净的一份，就把旧文件夹里除 venv/ browser_profile*/ logs/ uploads/ data/
和 .xlsx 之外的东西删掉，再解压进去。
TXT

# ---- 4. 打成一个 zip ----
rm -f "$ZIP_NAME"
( cd "$TMP" && zip -q -r -X "$OLDPWD/$ZIP_NAME" auto-builder )
echo "==> 生成 $ZIP_NAME （$(du -h "$ZIP_NAME" | cut -f1)，$(git ls-files | wc -l | tr -d ' ') 个程序文件）"

# ---- 5. 保险：确认 zip 里没有登录态 / 业务数据 ----
#
# examples/ 要排除在检查之外：那里面是【故意放在公开仓库里的示例模板】（假数据），
# 文件名恰好带 identity 之类的字样。第一次跑这个脚本就被它误报中止了。
# 真实的身份表是根目录下的 Identity_id.xlsx，所以用 ^auto-builder/ 锚定根目录。
BAD=$(unzip -Z1 "$ZIP_NAME" \
  | grep -v '^auto-builder/examples/' \
  | grep -Ei 'browser_profile|/venv/|^auto-builder/logs/|^auto-builder/uploads/|^auto-builder/data/|短剧|商品库|搭建表|^auto-builder/Identity_id\.xlsx|260810' \
  || true)
if [ -n "$BAD" ]; then
  echo "✗ zip 里出现了不该有的东西，已中止，请检查 .gitignore："
  echo "$BAD"
  rm -f "$ZIP_NAME"
  exit 1
fi
echo "==> 检查通过：zip 里没有登录态和业务数据"

# ---- 6. 推到私有仓库 ----
if [ ! -d "$PRIVATE_GIT" ]; then
  echo "✗ 找不到 $PRIVATE_GIT，没法推到私有仓库。zip 已经生成在本地了。"
  exit 1
fi
PG="git --git-dir=$PRIVATE_GIT --work-tree=."
$PG add -f "$ZIP_NAME"
if $PG diff --cached --quiet; then
  echo "==> 内容和上次一样，不用提交"
else
  $PG commit -q -m "程序打包 $COMMIT（$NOW）"
  $PG push -q origin HEAD
  echo "==> 已推到私有仓库：$($PG remote get-url origin)"
fi

echo
echo "完成。去别人电脑上更新时，从私有仓库下载这一个文件就够了："
echo "  $ZIP_NAME"
