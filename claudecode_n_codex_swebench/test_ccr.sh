#!/bin/bash
# ============================================================
# Claude Code Router (CCR) Debug Script
# ============================================================

# Enable verbose output
set -x

LOG_FILE="/tmp/ccr_debug_$(date +%Y%m%d_%H%M%S).log"
exec > >(tee -a "$LOG_FILE") 2>&1

echo "============================================================"
echo "CCR Debug Script - $(date)"
echo "Log file: $LOG_FILE"
echo "============================================================"

# 1. Check Ollama
echo ""
echo "[1/6] Checking Ollama..."
curl -s http://localhost:11434/api/tags | head -5
echo ""

# 2. Check CCR version
echo "[2/6] CCR version..."
ccr -v
echo ""

# 3. Check CCR status BEFORE start
echo "[3/6] CCR status (before start)..."
ccr status
echo ""

# 4. Start CCR in background
echo "[4/6] Starting CCR server in background..."
ccr start &
CCR_PID=$!
echo "CCR start PID: $CCR_PID"
sleep 5
echo ""

# 5. Check CCR status AFTER start
echo "[5/6] CCR status (after start)..."
ccr status
echo ""

# 6. Try ccr code with timeout (prompt via stdin as required by --print)
echo "[6/6] Running ccr code with 60s timeout..."
echo "Command: echo 'Say hello' | timeout 60 ccr code --print"

# Use gtimeout on macOS (from coreutils) or perl as fallback
if command -v gtimeout &> /dev/null; then
    echo "Say hello" | gtimeout 60 ccr code --print 2>&1
elif command -v timeout &> /dev/null; then
    echo "Say hello" | timeout 60 ccr code --print 2>&1
else
    # Perl-based timeout fallback for macOS
    echo "Say hello" | perl -e 'alarm 60; exec @ARGV' ccr code --print 2>&1
fi

EXIT_CODE=$?
echo ""
echo "Exit code: $EXIT_CODE"

echo ""
echo "============================================================"
echo "DEBUG COMPLETE"
echo "============================================================"
echo "Full log saved to: $LOG_FILE"
echo ""
echo "To view the log:"
echo "  cat $LOG_FILE"
