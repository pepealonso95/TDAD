#!/bin/bash
# Manual evaluation script for EXP-002
# Run this in your terminal with: bash run_evaluation_manual.sh

set -e  # Exit on error

echo "================================================================"
echo "EXP-002 Evaluation - Manual Execution"
echo "================================================================"
echo ""
echo "Prerequisites:"
echo "  1. Conda environment 'py313' must be activated"
echo "  2. Docker must be running"
echo "  3. This will take approximately 20-30 minutes"
echo ""
echo "Press Ctrl+C to cancel, or Enter to continue..."
read

echo ""
echo "Checking environment..."
python --version
which python

echo ""
echo "Checking predictions file..."
if [ ! -f "predictions/predictions_20251029_104634.jsonl" ]; then
    echo "ERROR: Predictions file not found!"
    exit 1
fi

echo "Found predictions file: $(wc -l < predictions/predictions_20251029_104634.jsonl) instances"

echo ""
echo "================================================================"
echo "Starting Docker evaluation..."
echo "================================================================"
echo ""

# Run evaluation
python evaluate_predictions.py \
    --file predictions/predictions_20251029_104634.jsonl

echo ""
echo "================================================================"
echo "Evaluation complete!"
echo "================================================================"
echo ""
echo "Next steps:"
echo "  1. Run regression analysis: bash run_regression_analysis.sh"
echo "  2. Or manually: python analyze_regressions.py --predictions predictions/predictions_20251029_104634.jsonl"
