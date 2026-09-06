#!/usr/bin/env bash
set -euo pipefail

# ==============================================================================
# Side-by-Side Live Reviewer & Playwright Automation Launcher
# ==============================================================================

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
CHROME_BIN="/home/falluba/.cache/ms-playwright/chromium-1234/chrome-linux64/chrome"

export DISPLAY="${DISPLAY:-:0}"
export WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}"
export PLAYWRIGHT_HEADLESS=false
export PLAYWRIGHT_SLOWMO=800
export JAA_FIREBASE_PROJECT_ID="${JAA_FIREBASE_PROJECT_ID:?Set JAA_FIREBASE_PROJECT_ID to your Firebase project}"

if [ "${1:-}" != "--enable-submission" ] || [ "${JAA_ENABLE_SUBMISSION:-}" != "I_UNDERSTAND_SUBMISSION" ]; then
    echo "Refusing to start the submission UI. Pass --enable-submission and set JAA_ENABLE_SUBMISSION=I_UNDERSTAND_SUBMISSION explicitly." >&2
    exit 1
fi

echo "=================================================================="
echo "🖥️ LAUNCHING SIDE-BY-SIDE REVIEW UI & PLAYWRIGHT WORKER"
echo "=================================================================="
echo "Display: $DISPLAY | Wayland: $WAYLAND_DISPLAY"
echo "=================================================================="

# 1. Open the WebUI on the Left Side of the Host Screen
if [ -f "$CHROME_BIN" ]; then
    echo " -> Opening Web Review UI on left side of screen..."
    "$CHROME_BIN" \
        --app="https://${JAA_FIREBASE_PROJECT_ID}.web.app" \
        --window-position=30,50 \
        --window-size=760,950 \
        --user-data-dir="/tmp/tinder_jobs_pwa_profile" \
        --no-first-run --no-default-browser-check >/dev/null 2>&1 &
    UI_PID=$!
else
    echo " -> Opening Web Review UI in default browser..."
    firefox --new-window "https://${JAA_FIREBASE_PROJECT_ID}.web.app" >/dev/null 2>&1 &
    UI_PID=$!
fi

# 2. Run Playwright Worker in Foreground on the Right Side of the Screen
echo " -> Starting Playwright Worker (Headed mode positioned on right side)..."
echo " -> Listening for job approvals..."
echo -e "\n👉 Whenever you approve a draft for gated submission in the UI on the left,"
echo "   Playwright will open on the right and fill the application live!"
echo "   Press Ctrl+C to close both."
echo "=================================================================="

cleanup() {
    echo -e "\n🛑 Closing side-by-side session..."
    kill "${UI_PID:-}" 2>/dev/null || true
    exit 0
}
trap cleanup SIGINT SIGTERM

"$PYTHON_BIN" -m job_application_agents.auto_apply.worker
