#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PID_FILE="$REPO_ROOT/data/logs/workers.pid"

echo "=================================================================="
echo "🛑 STOPPING BACKGROUND WORKERS"
echo "=================================================================="

if [ -f "$PID_FILE" ]; then
    PIDS=$(cat "$PID_FILE")
    for pid in $PIDS; do
        if ps -p "$pid" > /dev/null 2>&1; then
            echo " -> Killing worker PID $pid..."
            kill "$pid" 2>/dev/null || true
        fi
    done
    rm -f "$PID_FILE"
fi

# Kill any lingering worker processes
pkill -f "job_application_agents.auto_apply.worker" || true
pkill -f "job_application_agents.plugins.notion.worker" || true

echo "✅ All workers stopped cleanly."
