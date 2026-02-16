#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

DATASET_NAME="${DATASET_NAME:-princeton-nlp/SWE-bench_Verified}"
MAX_INSTANCES="${MAX_INSTANCES:-9}"
TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
OUTPUT_FILE="${OUTPUT_FILE:-predictions/predictions_repaired_qwen_mini_${TIMESTAMP}.jsonl}"

if ! [[ "$MAX_INSTANCES" =~ ^[0-9]+$ ]]; then
  echo "MAX_INSTANCES must be an integer, got: $MAX_INSTANCES" >&2
  exit 1
fi

FAILED_IDS=(
  "astropy__astropy-12907"
  "astropy__astropy-13033"
  "astropy__astropy-13236"
  "astropy__astropy-14182"
  "astropy__astropy-13398"
  "astropy__astropy-13453"
  "astropy__astropy-13579"
  "astropy__astropy-13977"
  "astropy__astropy-14096"
)

mkdir -p "$(dirname "$OUTPUT_FILE")" logs
: > "$OUTPUT_FILE"

echo "Dataset: $DATASET_NAME"
echo "Output : $OUTPUT_FILE"
echo "Max    : $MAX_INSTANCES"

count=0
for instance_id in "${FAILED_IDS[@]}"; do
  if (( count >= MAX_INSTANCES )); then
    break
  fi

  log_file="logs/repair_${instance_id}.log"
  echo
  echo "=== [${count}/${MAX_INSTANCES}] Regenerating ${instance_id} ==="
  echo "Log file: ${log_file}"

  python3 - "$instance_id" "$DATASET_NAME" "$OUTPUT_FILE" <<'PY' 2>&1 | tee "$log_file"
import json
import sys
import traceback

import jsonlines

from code_swe_agent import CodeSWEAgent

instance_id = sys.argv[1]
dataset_name = sys.argv[2]
output_file = sys.argv[3]

try:
    agent = CodeSWEAgent(backend="qwen-mini")
    prediction = agent.run_on_instance(instance_id, dataset_name)
    with jsonlines.open(output_file, mode="a") as writer:
        writer.write(prediction)
    print(
        json.dumps(
            {
                "instance_id": instance_id,
                "prediction_chars": len(prediction.get("prediction", "")),
                "has_error": bool(prediction.get("error")),
            }
        )
    )
except Exception as exc:
    print(json.dumps({"instance_id": instance_id, "error": str(exc)}))
    traceback.print_exc()
    raise
PY

  count=$((count + 1))
done

echo
echo "Completed regeneration for ${count} instance(s)."
echo "Saved predictions to ${OUTPUT_FILE}"
wc -l "$OUTPUT_FILE"
