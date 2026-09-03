#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Native Background Worker Launcher for Live Firestore Mode (No Docker Needed)
# ==============================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export PYTHONPATH="$REPO_ROOT"
export JAA_FIREBASE_PROJECT_ID="${JAA_FIREBASE_PROJECT_ID:?Set JAA_FIREBASE_PROJECT_ID to your Firebase project}"
export NOTION_DATABASE_ID="${NOTION_DATABASE_ID:-3c7ac433-f81d-80bd-959d-ecfeba5f8ffe}"

PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
if [ ! -f "$PYTHON_BIN" ]; then
    PYTHON_BIN="python3"
fi

mkdir -p "$REPO_ROOT/data/logs"
LOG_FILE="$REPO_ROOT/data/logs/workers.log"

DAEMON_MODE=false
ENABLE_SUBMISSION=false
for arg in "$@"; do
    case "$arg" in
        --daemon|-d) DAEMON_MODE=true ;;
        --enable-submission) ENABLE_SUBMISSION=true ;;
    esac
done

if [ "$ENABLE_SUBMISSION" = true ] && [ "${JAA_ENABLE_SUBMISSION:-}" != "I_UNDERSTAND_SUBMISSION" ]; then
    echo "Refusing to start submission worker: set JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION explicitly." >&2
    exit 1
fi

echo "=================================================================="
echo "🚀 STARTING NATIVE BACKGROUND WORKERS (Cloud Firestore Connected)"
echo "=================================================================="
echo "Project ID: $JAA_FIREBASE_PROJECT_ID"
echo "Python:     $PYTHON_BIN"
echo "Log File:   $LOG_FILE"
echo "=================================================================="

if [ "$DAEMON_MODE" = true ]; then
    echo " -> Starting daemons in detached background mode..."
    if [ "$ENABLE_SUBMISSION" = true ]; then
        nohup "$PYTHON_BIN" -m job_application_agents.auto_apply.worker >> "$LOG_FILE" 2>&1 &
        PW_PID=$!
    fi
    nohup "$PYTHON_BIN" -m job_application_agents.plugins.notion.worker >> "$LOG_FILE" 2>&1 &
    NOTION_PID=$!

    echo "${PW_PID:-} $NOTION_PID" > "$REPO_ROOT/data/logs/workers.pid"
    echo "✅ Workers started successfully in background!"
    if [ "$ENABLE_SUBMISSION" = true ]; then
        echo "   • Playwright Worker PID: $PW_PID"
    else
        echo "   • Playwright Worker:     disabled (default)"
    fi
    echo "   • Notion Worker PID:     $NOTION_PID"
    echo -e "\nTo view live logs: tail -f data/logs/workers.log"
    echo "To stop workers:   ./scripts/stop_workers.sh"
    exit 0
fi

# Foreground mode with live output
if [ "$ENABLE_SUBMISSION" = true ]; then
    echo " -> Starting Playwright Submission Worker..."
    "$PYTHON_BIN" -m job_application_agents.auto_apply.worker &
    PW_PID=$!
    echo "    [PID: $PW_PID] Playwright worker active and listening to /submissionJobs."
else
    echo " -> Playwright Submission Worker disabled (default; use --enable-submission explicitly)."
fi

echo " -> Starting Notion Sync Worker..."
"$PYTHON_BIN" -m job_application_agents.plugins.notion.worker &
NOTION_PID=$!
echo "    [PID: $NOTION_PID] Notion worker active and listening to /notionJobs."

echo -e "\n=================================================================="
echo "👀 LISTENING FOR EVENTS (Terminal is waiting for incoming jobs)"
echo "=================================================================="
echo "📱 Mobile Review PWA: https://$JAA_FIREBASE_PROJECT_ID.web.app"
echo "Review-only mode is active; no application submission is enabled."
echo "Press Ctrl+C to stop the workers anytime."
echo "=================================================================="

cleanup() {
    echo -e "\n🛑 Stopping foreground workers..."
    kill "${PW_PID:-}" "${NOTION_PID:-}" 2>/dev/null || true
    wait "${PW_PID:-}" "${NOTION_PID:-}" 2>/dev/null || true
    exit 0
}

trap cleanup SIGINT SIGTERM

wait
