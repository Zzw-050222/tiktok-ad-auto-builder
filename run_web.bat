@echo off
chcp 65001 >nul
cd /d "%~dp0"
echo Starting server, please wait...
start "TikTok-Server" venv\Scripts\python.exe app.py
ping -n 4 127.0.0.1 >nul
start http://127.0.0.1:5000/
echo Browser opened. If the page fails to load, wait a few seconds and refresh.
echo Do not close this window or the black server window - closing them stops the tool.
pause
