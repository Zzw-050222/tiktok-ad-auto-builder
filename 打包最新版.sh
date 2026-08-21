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
1. 解压，把 auto-builder 文件夹放到你想放的地方
2. Mac: 双击 run_web.sh 之前先在终端里执行一次
       python3 -m venv venv
       venv/bin/pip install -r requirements.txt
       venv/bin/playwright install chromium
   Windows: 用 run_web.bat 之前先执行
       python -m venv venv
       venv\\Scripts\\pip install -r requirements.txt
       venv\\Scripts\\playwright install chromium
3. 起服务：Mac 执行 ./run_web.sh，Windows 双击 run_web.bat
4. 浏览器打开 http://127.0.0.1:5050
5. 在网页第 2 步点【登录 / 换账号】，用自己的 BC 账号登录

—— 更新一台已经装好的电脑 ——
把解压出来的文件【覆盖】到原来的文件夹即可。
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
BAD=$(unzip -Z1 "$ZIP_NAME" | grep -Ei 'browser_profile|/venv/|logs/|uploads/|短剧|商品库|搭建表|Identity_id|260810' || true)
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
