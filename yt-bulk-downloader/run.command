#!/bin/bash
# Double-click this file in Finder (or run it in Terminal) to launch the app.
cd "$(dirname "$0")"
# Finder launches with a minimal PATH; make sure Homebrew's node + ffmpeg are found.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
exec .venv/bin/python app.py
