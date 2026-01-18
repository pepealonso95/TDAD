#!/bin/bash
# EXP-009 Test Script: Restart MCP server and run GraphRAG experiment

set -e

cd /Users/rafaelalonso/Development/Master/Tesis/claudecode_n_codex_swebench

echo "=============================================="
echo "EXP-009: GraphRAG Test Run"
echo "=============================================="

# Step 1: Stop existing MCP server
echo ""
echo "Step 1: Stopping existing MCP server..."
pkill -f "mcp_server" 2>/dev/null || echo "  No existing MCP server found"
sleep 2

# Step 2: Start MCP server in background
echo ""
echo "Step 2: Starting MCP server..."
python -m mcp_server.server &
MCP_PID=$!
echo "  MCP server started (PID: $MCP_PID)"

# Wait for server to be ready
echo "  Waiting for server to be ready..."
for i in {1..30}; do
    if curl -s http://localhost:8080/health > /dev/null 2>&1; then
        echo "  MCP server is ready!"
        break
    fi
    sleep 1
    if [ $i -eq 30 ]; then
        echo "  ERROR: MCP server failed to start"
        exit 1
    fi
done

# Step 3: Run the experiment
echo ""
echo "Step 3: Running GraphRAG experiment (3 instances, TDD mode)..."
echo "=============================================="

python code_swe_agent_graphrag.py \
  --dataset_name princeton-nlp/SWE-bench_Verified \
  --limit 100 \
  --backend qwen \
  --tdd

echo ""
echo "=============================================="
echo "Experiment complete!"
echo "=============================================="

# Cleanup: Stop MCP server
echo ""
echo "Stopping MCP server..."
kill $MCP_PID 2>/dev/null || true
echo "Done!"
