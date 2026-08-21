#!/usr/bin/env python3
"""FC Custom Runtime 入口 — 启动 AIHOT HTTP 服务。

FC Custom Runtime 要求：
  - 进程监听 PORT 环境变量指定的端口（默认 9000）
  - 处理 FC 转发的 HTTP 请求
"""
import os
import sys

# 确保工作目录在代码包根目录（FC 可能将 cwd 设为 /code）
os.chdir(os.path.dirname(os.path.abspath(__file__)))

# 将代码包目录加入 Python 路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import main

if __name__ == "__main__":
    main()
else:
    main()
