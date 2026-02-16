#!/bin/bash
# Monitor regeneration progress

REPAIRED_FILE=$(ls -t predictions/predictions_repaired_*.jsonl 2>/dev/null | head -1)

if [ -z "$REPAIRED_FILE" ]; then
  echo "No repaired predictions file found"
  exit 1
fi

echo "=== Regeneration Progress ==="
echo "File: $REPAIRED_FILE"
echo "Size: $(ls -lh "$REPAIRED_FILE" | awk '{print $5}')"
echo ""

# Count predictions
TOTAL=$(wc -l < "$REPAIRED_FILE" 2>/dev/null || echo 0)
echo "Completed instances: $TOTAL/9"

if [ "$TOTAL" -gt 0 ]; then
  echo ""
  echo "Instance IDs:"
  cat "$REPAIRED_FILE" | jq -r '.instance_id'

  echo ""
  echo "Patch status:"
  NON_EMPTY=$(grep -c '"prediction": "[^"]' "$REPAIRED_FILE" 2>/dev/null || echo 0)
  EMPTY=$(grep -c '"prediction": ""' "$REPAIRED_FILE" 2>/dev/null || echo 0)
  echo "  Non-empty: $NON_EMPTY"
  echo "  Empty: $EMPTY"
fi

echo ""
echo "Latest logs:"
ls -lt logs/repair_*.log 2>/dev/null | head -5
