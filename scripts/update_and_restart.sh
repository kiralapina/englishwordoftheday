#!/bin/bash
# Обновление бота из Git и перезапуск. Запускайте на сервере из папки проекта.
# Использование: ./scripts/update_and_restart.sh

set -e
cd "$(dirname "$0")/.."
BOT_DIR="$PWD"
PIDFILE="$BOT_DIR/bot.pid"
LOCKFILE="$BOT_DIR/bot.lock"
LOG="$BOT_DIR/bot.log"

# ── Защита от параллельного запуска ──────────────────────────
exec 200>"$LOCKFILE"
if ! flock -n 200; then
  echo "Another deploy is already running. Exiting."
  exit 0
fi

echo "[$(date)] ===== Deploy started ====="

# ── Обновление кода ──────────────────────────────────────────
git fetch origin
CHANGED=0
if ! git diff --quiet HEAD origin/main 2>/dev/null; then
  CHANGED=1
fi
if ! git diff --quiet HEAD origin/master 2>/dev/null; then
  CHANGED=1
fi

if [ "$CHANGED" -eq 1 ]; then
  echo "Pulling changes..."
  git pull origin main 2>/dev/null || git pull origin master 2>/dev/null
fi

# ── Убить ВСЕ старые процессы бота ───────────────────────────
echo "Stopping old bot processes..."
if [ -f "$PIDFILE" ]; then
  OLD_PID=$(cat "$PIDFILE")
  if kill -0 "$OLD_PID" 2>/dev/null; then
    kill "$OLD_PID" 2>/dev/null || true
  fi
  rm -f "$PIDFILE"
fi
# Страховка: убить всё, что похоже на наш бот
pkill -f "python.*bot\.py" 2>/dev/null || true
sleep 2
# Если кто-то выжил — SIGKILL
pkill -9 -f "python.*bot\.py" 2>/dev/null || true
sleep 1

# Проверить, что не осталось процессов
REMAINING=$(pgrep -f "python.*bot\.py" 2>/dev/null | wc -l)
if [ "$REMAINING" -gt 0 ]; then
  echo "WARNING: $REMAINING bot processes still alive after kill"
  pgrep -af "python.*bot\.py" 2>/dev/null || true
fi

# ── Установить зависимости и запустить ────────────────────────
source venv/bin/activate
pip install -q -r requirements.txt

nohup python bot.py >> "$LOG" 2>&1 &
echo $! > "$PIDFILE"
sleep 3

if kill -0 "$(cat "$PIDFILE")" 2>/dev/null; then
  echo "Bot started (PID $(cat $PIDFILE)). Log: $LOG"
else
  echo "ERROR: bot failed to start. Last 30 lines of log:"
  tail -30 "$LOG"
  exit 1
fi

echo "[$(date)] ===== Deploy finished ====="
