#!/bin/bash
# 启动（macOS）—— 双击这个文件就能开程序。
#
# 为什么不直接双击 run_web.sh：macOS 上双击 .sh 文件默认不是「运行」，
# 而是用文本编辑器打开它。只有 .command 后缀才会稳定地在【终端】里跑起来。
# 所以这个文件就是个壳，真正干活的还是 run_web.sh，一行没改。

cd "$(dirname "$0")" || exit 1

if [ ! -x venv/bin/python3 ] && [ ! -f venv/bin/python3 ]; then
  printf "\n\033[31m✗ 还没装运行环境。\033[0m\n\n先双击【一键安装.command】装一次，再回来双击本文件。\n\n按回车关闭。\n"
  read -r _
  exit 1
fi

exec ./run_web.sh
