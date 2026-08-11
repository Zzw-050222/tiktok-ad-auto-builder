#!/bin/bash
cd "$(dirname "$0")"

echo "Starting server, please wait..."
venv/bin/python3 app.py &
SERVER_PID=$!

sleep 3

if command -v open >/dev/null 2>&1; then
  open "http://127.0.0.1:5000/"
elif command -v xdg-open >/dev/null 2>&1; then
  xdg-open "http://127.0.0.1:5000/"
else
  echo "Please open http://127.0.0.1:5000/ in your browser manually."
fi

echo "Browser opened. If the page fails to load, wait a few seconds and refresh."
echo "Do not close this window - closing it stops the server (PID $SERVER_PID)."
wait $SERVER_PID
