#!/bin/bash
# EXP-010-REPAIR: Consolidate repaired predictions with resolved instance

set -e

# Find the most recent repaired predictions file
REPAIRED_FILE=$(ls -t predictions/predictions_repaired_*.jsonl 2>/dev/null | head -1)
ORIGINAL_FILE="predictions/predictions_20260214_122836.jsonl"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
OUTPUT_FILE="predictions/predictions_consolidated_${TIMESTAMP}.jsonl"

if [ -z "$REPAIRED_FILE" ]; then
  echo "ERROR: No repaired predictions file found"
  exit 1
fi

if [ ! -f "$ORIGINAL_FILE" ]; then
  echo "ERROR: Original predictions file not found: $ORIGINAL_FILE"
  exit 1
fi

echo "=== EXP-010-REPAIR: Consolidating Predictions ==="
echo "Original file: $ORIGINAL_FILE"
echo "Repaired file: $REPAIRED_FILE"
echo "Output file: $OUTPUT_FILE"
echo ""

# Extract the 1 resolved instance from original (astropy__astropy-14309)
echo "Extracting resolved instance (astropy__astropy-14309)..."
grep '"astropy__astropy-14309"' "$ORIGINAL_FILE" > "$OUTPUT_FILE"
echo "✓ Added 1 resolved instance"

# Append all repaired predictions
echo "Adding repaired predictions..."
cat "$REPAIRED_FILE" >> "$OUTPUT_FILE"

# Count results
TOTAL=$(wc -l < "$OUTPUT_FILE")
NON_EMPTY=$(grep -c '"prediction": "[^"]' "$OUTPUT_FILE" || echo 0)
EMPTY=$(grep -c '"prediction": ""' "$OUTPUT_FILE" || echo 0)

echo ""
echo "=== Consolidation Summary ==="
echo "Total predictions: $TOTAL"
echo "Non-empty patches: $NON_EMPTY"
echo "Empty patches: $EMPTY"
echo "Generation rate: $(echo "scale=1; $NON_EMPTY * 100 / $TOTAL" | bc)%"
echo ""
echo "Consolidated file: $OUTPUT_FILE"
echo ""
echo "Next step: Run Docker evaluation"
echo "  python3 evaluate_predictions.py --file $OUTPUT_FILE --dataset princeton-nlp/SWE-bench_Verified --max-workers 2 --force"
