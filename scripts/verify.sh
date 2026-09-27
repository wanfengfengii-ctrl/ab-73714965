#!/usr/bin/env bash
# 一次性校验：代码测试 -> 前端构建 -> 定位 API 冒烟。
# 任一步骤失败即以非零退出码结束（set -e）。
set -euo pipefail

echo "==> [1/3] 后端代码测试（pytest）"
(cd /src/api && /opt/venv/bin/python -m pytest -q)

echo "==> [2/3] 前端构建（tsc 类型检查 + vite build）"
(cd /src/web && npm run build)

echo "==> [3/3] 定位 API 冒烟测试（直连 API + 经 Web 代理）"
python3 /src/scripts/smoke.py

echo "VERIFY PASSED"
