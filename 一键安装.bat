@echo off
rem 本文件用 GBK(936) 编码保存、CRLF 换行 —— 两个都不能改，改了 cmd 就解析不了中文。
rem 详见同目录 .gitattributes 里的说明。用编辑器改本文件时记得保持 GBK 编码。
chcp 936 >nul
setlocal
cd /d "%~dp0"

rem 一键安装（Windows）—— 全新电脑上装这个程序，双击这个文件就行。
rem
rem 为什么要有这个文件：原来的说明书让人手敲三行命令，而那三行【必须在
rem auto-builder 文件夹里】敲。终端一打开在用户主目录，直接粘进去就会报
rem 「找不到 requirements.txt」。双击运行的脚本自己知道自己在哪，不会有这个问题。
rem
rem 重复运行是安全的：装好的不会重装，登录态和表格一根手指都不碰。

set REPO=https://github.com/Zzw-050222/tiktok-ad-auto-builder.git

echo.
echo === TikTok 广告自动搭建 · 一键安装 ===
echo 文件夹：%cd%
echo.

rem --- 1. 先确认位置对不对 ---
if not exist "requirements.txt" goto :wrongdir
if not exist "app.py" goto :wrongdir
echo   [OK] 位置正确

rem --- 2. 找一个能用的 Python ---
rem 和 macOS 那边同一个理由：不能只赌 python 这一个名字。
rem Windows 上装了 Python 官方版会带 py 启动器（py -3.12 这种），
rem 而 PATH 里的 python 可能是别的版本、甚至是应用商店那个占位符。
rem 所以按新到旧试一遍，挑第一个 >= 3.10 的。
set PYBIN=
set PYV=
for %%c in ("py -3.14" "py -3.13" "py -3.12" "py -3.11" "py -3.10" "py -3" "python" "python3") do (
  if not defined PYBIN (
    for /f "delims=" %%v in ('%%~c -c "import sys;print(\"%%d.%%d\" %% sys.version_info[:2])" 2^>nul') do (
      for /f "delims=" %%k in ('%%~c -c "import sys;print(1 if sys.version_info[:2]>=(3,10) else 0)" 2^>nul') do (
        if "%%k"=="1" (
          set PYBIN=%%~c
          set PYV=%%v
        ) else (
          echo   [!] %%~c 是 %%v，太老了，跳过
        )
      )
    )
  )
)

if not defined PYBIN (
  echo.
  echo [X] 这台电脑上没有 3.10 以上的 Python。
  echo     去 https://www.python.org/downloads/ 装一个，
  echo     安装第一页记得勾上【Add python.exe to PATH】，装完重新双击本文件。
  goto :end
)
echo   [OK] Python %PYV%（%PYBIN%）

rem --- 3. 建运行环境 ---
set NEED=0
if not exist "venv" (
  set NEED=1
) else (
  venv\Scripts\python -c "import flask, openpyxl, playwright, requests, dotenv" >nul 2>nul
  if errorlevel 1 (
    echo   [!] 已有的运行环境不完整（上次可能装到一半中断了），重装一遍
    rmdir /s /q venv
    set NEED=1
  ) else (
    echo   [OK] 运行环境已存在
  )
)

if "%NEED%"=="1" (
  echo.
  echo 正在装运行环境，要几分钟，别关窗口…
  %PYBIN% -m venv venv
  if errorlevel 1 ( echo [X] 创建 venv 失败。& goto :end )
  venv\Scripts\python -m pip install --upgrade pip --quiet
  echo   装依赖（flask / playwright / openpyxl …）
  venv\Scripts\pip install -r requirements.txt
  if errorlevel 1 ( echo [X] 装依赖失败。检查一下网络。& goto :end )
  echo   [OK] 依赖装好了
)

rem --- 4. 装 Chromium（程序靠它去点 TikTok 后台，没有它跑不起来）---
venv\Scripts\python -c "from playwright.sync_api import sync_playwright as s;import pathlib,sys;p=s().start();sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)" >nul 2>nul
if errorlevel 1 (
  echo.
  echo 正在装 Chromium 浏览器（约 150MB，别关窗口）…
  venv\Scripts\playwright install chromium
  if errorlevel 1 ( echo [X] 装 Chromium 失败。检查一下网络。& goto :end )
  echo   [OK] Chromium 装好了
) else (
  echo   [OK] Chromium 浏览器已装好
)

rem --- 5. 接到 GitHub，方便以后一键更新（代码仓库是公开的，不用登录）---
where git >nul 2>nul
if errorlevel 1 (
  echo   [!] 这台电脑没装 git，装好之后才能用「一键更新」。
  echo       装法：https://git-scm.com/download/win
) else (
  if not exist ".git" (
    git init -q
    git remote add origin %REPO%
    echo   [OK] 已接到 GitHub（以后双击「一键更新.bat」就能拿最新版）
  ) else (
    git remote set-url origin %REPO% 2>nul
    echo   [OK] 已接到 GitHub
  )
)

rem --- 6. 自检：「命令没报错」不等于「真的能跑」---
echo.
echo === 自检 ===
venv\Scripts\python -c "import flask, openpyxl, playwright, requests, dotenv" >nul 2>nul
if errorlevel 1 ( echo [X] 依赖装了但加载不了。& goto :end )
echo   [OK] 依赖都能加载
venv\Scripts\python -c "from playwright.sync_api import sync_playwright as s;import pathlib,sys;p=s().start();sys.exit(0 if pathlib.Path(p.chromium.executable_path).exists() else 1)" >nul 2>nul
if errorlevel 1 ( echo [X] Chromium 没装上。重新双击本文件再试一次。& goto :end )
echo   [OK] Chromium 可用
venv\Scripts\python -c "import app" >nul 2>nul
if errorlevel 1 ( echo   [!] 程序本体加载有问题，启动时如果报错请把日志发给开发者 ) else ( echo   [OK] 程序本体能加载 )

echo.
echo === 装好了 ===
echo 接下来：
echo   1. 双击【run_web.bat】
echo   2. 浏览器打开 http://127.0.0.1:5050
echo   3. 在网页第 2 步点【登录 / 换账号】，登录自己的 BC 账号
echo      ——登录态只存在这台电脑上，程序里没有任何账号密码
echo.
echo 以后要更新：双击【一键更新.bat】，登录态、日志、表格都不会丢。
goto :end

:wrongdir
echo.
echo [X] 这个文件夹里没有 requirements.txt 或 app.py，不像是 auto-builder 程序文件夹。
echo     把「一键安装.bat」放回解压出来的 auto-builder 文件夹里再双击。
echo     （解压后里面应该能看到 app.py、run_web.bat、src 这些东西）

:end
echo.
pause
endlocal
