#!/bin/bash
cd "$(dirname "$0")"

PORT=5050

# 先看端口上有没有残留的旧服务。有过一次：三天前起的孤儿进程一直占着端口，
# 新服务起不来，浏览器却连到旧进程上，页面还是旧的，报错也是旧代码的。
STALE=$(lsof -nP -iTCP:$PORT -sTCP:LISTEN -t 2>/dev/null)
if [ -n "$STALE" ]; then
  echo "端口 $PORT 上已经有服务在跑 (PID $STALE)。"
  echo "如果是上次没关干净的，先执行：kill $STALE"
  echo "然后重新运行本脚本。"
  exit 1
fi

echo "Starting server, please wait..."
# 输出同时写进 logs/webserver.log。网页版原来只把报错打在这个终端里，
# 出问题只能靠截图传给别人看——截图还可能太大传不过去。写进文件谁都能直接读。
mkdir -p logs
venv/bin/python3 -u app.py 2>&1 | tee logs/webserver.log &
SERVER_PID=$!

sleep 3

if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:$PORT/"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:$PORT/"
else
  echo "Please open http://127.0.0.1:$PORT/ in your browser manually."
fi

echo "Browser opened. If the page fails to load, wait a few seconds and refresh."
echo "Do not close this window - closing it stops the server (PID $SERVER_PID)."
wait $SERVER_PID
