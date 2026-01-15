#!/bin/bash
# Run Qwen on 100 SWE-bench instances
# Usage: ./run_qwen_100.sh

cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
LOG_FILE="logs/qwen_run_${TIMESTAMP}.log"

# Create logs directory
mkdir -p logs

echo "=============================================="
echo "Starting Qwen SWE-bench run"
echo "Timestamp: $TIMESTAMP"
echo "Limit: 100 instances"
echo "Log file: $LOG_FILE"
echo "=============================================="

# Run with output to both terminal and log file
python code_swe_agent.py \
    --dataset_name princeton-nlp/SWE-bench_Verified \
    --limit 100 \
    --backend qwen \
    2>&1 | tee "$LOG_FILE"

echo ""
echo "=============================================="
echo "Run complete!"
echo "Log saved to: $LOG_FILE"
echo "Predictions saved to: predictions/"
echo "=============================================="
