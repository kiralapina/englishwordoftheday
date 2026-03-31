#!/bin/bash
# Обновление бота из Git и перезапуск. Запускайте на сервере из папки проекта.
# Использование: ./scripts/update_and_restart.sh

set -e
cd "$(dirname "$0")/.."
BOT_DIR="$PWD"
PIDFILE="$BOT_DIR/bot.pid"
LOG="$BOT_DIR/bot.log"

echo "[$(date)] Updating..."
git fetch origin
if git diff --quiet HEAD origin/main 2>/dev/null || git diff --quiet HEAD origin/master 2>/dev/null; then
  echo "No changes."
  exit 0
fi

git pull origin main 2>/dev/null || git pull origin master 2>/dev/null

# Остановить старый процесс
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    echo "Stopping old bot (PID $OLD_PID)..."
    kill "$OLD_PID" 2>/dev/null || true
    sleep 2
  fi
  rm -f "$PIDFILE"
fi
pkill -f "python.*bot.py" 2>/dev/null || true
sleep 1

# Установить/обновить зависимости и запустить
source venv/bin/activate
pip install -q -r requirements.txt

nohup python bot.py >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 3

if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Bot restarted (PID $(cat $PIDFILE)). Log: $LOG"
else
  echo "ERROR: bot failed to start. Check $LOG"
  tail -20 "$LOG"
  exit 1
fi
