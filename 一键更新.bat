@echo off
rem 本文件用 GBK(936) 编码保存、CRLF 换行 —— 两个都不能改。详见 .gitattributes。
chcp 936 >nul
setlocal
cd /d "%~dp0"

rem 一键更新（Windows）—— 双击这个文件就行。
rem
rem 从 GitHub 把最新代码拉下来覆盖掉旧代码，然后（首次或依赖有变时）装好运行环境。
rem 登录态、日志、上传的表格都不会被动——它们是 git 未跟踪的文件，
rem git reset --hard 一根手指都不碰。

set REPO=https://github.com/Zzw-050222/tiktok-ad-auto-builder.git
set BRANCH=master

echo.
echo === TikTok 广告自动搭建 · 一键更新 ===
echo 文件夹：%cd%
echo.

where git >nul 2>nul
if errorlevel 1 (
  echo [X] 这台电脑没装 git，没法自动更新。两个办法，选一个：
  echo.
  echo   1. 装 git（推荐，以后就能一键更新）：https://git-scm.com/download/win
  echo   2. 不装 git：去私有仓库下载 auto-builder-最新版.zip，
  echo      解压后把文件覆盖到这个文件夹即可。venv、登录态、日志、你的表格
  echo      都不在那个压缩包里，覆盖不会动它们。
  goto :end
)

rem --- 1. 没有 .git 就把文件夹接到 GitHub（当初是拷文件装的就会这样）---
if not exist ".git" (
  echo 第一次用这个工具，正在把文件夹接到 GitHub…
  git init -q
  git remote add origin %REPO%
) else (
  git remote set-url origin %REPO% 2>nul
  if errorlevel 1 git remote add origin %REPO%
)

rem --- 2. 有人改过程序本体就先问一声 ---
rem 这一段不能用 if (...) 括号包起来：整个括号块是一次性解析的，%ANS% 在
rem set /p 还没执行时就已经被替换成空字符串了，于是不管用户答 y 还是 n，
rem 都会走进「已取消」。改成 goto 跳过，%ANS% 才能读到用户真正输入的东西。
set DIRTY=
for /f %%i in ('git status --porcelain --untracked-files^=no 2^>nul ^| find /c /v ""') do set DIRTY=%%i
if "%DIRTY%"=="0" goto :nochange
echo.
echo 注意：这台电脑上有人改过程序文件，更新会把这些改动覆盖掉：
git status --short --untracked-files=no
echo.
set ANS=
set /p ANS="要继续吗？[y/N] "
if /i not "%ANS%"=="y" (
  echo 已取消，什么都没动。
  goto :end
)
:nochange

rem --- 3. 拉最新代码 ---
echo.
echo 正在从 GitHub 拉取最新代码…
if exist requirements.txt (
  certutil -hashfile requirements.txt MD5 | findstr /r /v "hash CertUtil" > "%TEMP%\ab_req_before.txt"
)
for /f %%i in ('git rev-parse --short HEAD 2^>nul') do set OLD=%%i
if "%OLD%"=="" set OLD=(无)

git fetch --depth=1 origin %BRANCH%
if errorlevel 1 (
  echo [X] 拉取失败。检查网络，或者这台电脑能不能访问 GitHub。
  goto :end
)
git reset --hard -q FETCH_HEAD
if errorlevel 1 (
  echo [X] 覆盖旧代码时出错了。
  goto :end
)

for /f %%i in ('git rev-parse --short HEAD') do set NEW=%%i
if "%OLD%"=="%NEW%" (
  echo 已经是最新版了（%NEW%），代码没有变化。
) else (
  echo 代码：%OLD% -^> %NEW%
  git --no-pager log --oneline -8 %NEW%
)

rem --- 4. 首次使用、或依赖有变，就装环境 ---
if not exist "venv" (
  echo.
  echo 第一次使用，正在装运行环境（要几分钟，别关窗口）…
  python -m venv venv
  if errorlevel 1 (
    echo [X] 创建 venv 失败。这台电脑要先装 Python 3.10 以上，安装时记得勾 Add to PATH。
    goto :end
  )
  venv\Scripts\python -m pip install -q --upgrade pip
  venv\Scripts\pip install -q -r requirements.txt
  if errorlevel 1 ( echo [X] 装依赖失败。& goto :end )
  venv\Scripts\playwright install chromium
  if errorlevel 1 ( echo [X] 装浏览器失败。& goto :end )
  echo 环境装好了。
) else (
  if exist requirements.txt (
    certutil -hashfile requirements.txt MD5 | findstr /r /v "hash CertUtil" > "%TEMP%\ab_req_after.txt"
    fc "%TEMP%\ab_req_before.txt" "%TEMP%\ab_req_after.txt" >nul 2>nul
    if errorlevel 1 (
      echo.
      echo 依赖有更新，正在重新安装…
      venv\Scripts\pip install -q -r requirements.txt
      if errorlevel 1 ( echo [X] 装依赖失败。& goto :end )
      echo 依赖已更新。
    )
  )
)

echo.
echo === 更新完成 ===
echo 接下来：
echo   · 双击 run_web.bat 启动
echo   · 浏览器打开 http://127.0.0.1:5050
echo   · 第一次用要在网页第 2 步点【登录 / 换账号】，登录自己的 BC 账号
echo.
echo 你的登录态、日志、上传过的表格都没有被动。

:end
echo.
pause
endlocal
