@echo off
rem 本文件用 GBK(936) 编码保存、CRLF 换行 —— 两个都不能改。详见 .gitattributes。
chcp 936 >nul
cd /d "%~dp0"
rem 端口是 5050 不是 5000：macOS 的隔空播放接收器常驻占着 5000，
rem 两个平台统一用 5050，app.py 里也是 5050。改一处就要改三处（app.py /
rem run_web.sh / 本文件），漏掉哪个都会打开一个空白页面。
echo Starting server, please wait...
start "TikTok-Server" venv\Scripts\python.exe app.py
ping -n 4 127.0.0.1 >nul
start http://127.0.0.1:5050/
echo Browser opened. If the page fails to load, wait a few seconds and refresh.
echo Do not close this window or the black server window - closing them stops the tool.
pause
