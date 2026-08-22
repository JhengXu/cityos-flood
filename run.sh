#!/usr/bin/env bash
# CITY OS · 深圳内涝预测 — 一键启动（后端 :8000 + 前端 :5173）
set -e
ROOT="$(cd "$(dirname "$0")" && pwd)"

echo "▶ 启动后端 (FastAPI :8000) ..."
cd "$ROOT/backend"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
source .venv/bin/activate
pip install -q -r requirements.txt
uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/cityos-backend.log 2>&1 &
BACK_PID=$!

echo "▶ 启动前端 (Vite :5173) ..."
cd "$ROOT/frontend"
[ -d node_modules ] || npm install
npm run dev > /tmp/cityos-frontend.log 2>&1 &
FRONT_PID=$!

echo "✅ 后端 PID=$BACK_PID  前端 PID=$FRONT_PID"
echo "   打开 http://localhost:5173"
trap "kill $BACK_PID $FRONT_PID 2>/dev/null" EXIT INT TERM
wait
