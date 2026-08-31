#!/bin/bash
# health_monitor.sh — 后端健康监控 + 自动重启
# 用法：nohup bash scripts/health_monitor.sh > /tmp/monitor.log 2>&1 &

API="http://localhost:8000/api/health"
FAIL=0
MAX_FAIL=3

while true; do
  code=$(curl -s -o /dev/null -w "%{http_code}" --max-time 10 "$API" 2>/dev/null)
  if [ "$code" != "200" ]; then
    FAIL=$((FAIL+1))
    echo "[$(date '+%H:%M:%S')] health check failed ($code) [$FAIL/$MAX_FAIL]"
    if [ $FAIL -ge $MAX_FAIL ]; then
      echo "[$(date '+%H:%M:%S')] restarting backend..."
      pkill -f "uvicorn app.main:app" 2>/dev/null
      sleep 2
      PY=$(ls /Users/imac/shs/cityos-flood-main-old/.venv-ml/bin/python 2>/dev/null || which python3)
      cd "$(dirname "$0")/.." && cd backend
      nohup $PY -m uvicorn app.main:app --host 0.0.0.0 --port 8000 > /tmp/cityos-github-api.log 2>&1 &
      echo $! > ../.back.pid
      FAIL=0
      sleep 15
    fi
  else
    [ $FAIL -gt 0 ] && echo "[$(date '+%H:%M:%S')] recovered"
    FAIL=0
  fi
  sleep 30
done
