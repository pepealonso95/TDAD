# Claude Code Session Management Guide

## Critical Issue: Session Limits

Claude Code has daily session limits that reset at **5:00 AM Pacific Time**. This directly impacts long-running experiments.

### What Happened

During the initial 3-experiment run (50 instances each):

```
01:09:47 AM → 03:27:59 AM | Baseline completed (2h 19m) ✓ 46% generation rate
03:27:59 AM → 03:44:28 AM | TDD failed (16m)          ✗ 0% generation rate
03:44:49 AM → 04:02:00 AM | GraphRAG failed (17m)     ✗ 0% generation rate
```

**Root Cause:**
- Baseline exhausted most of the session budget
- TDD (7KB prompts) and GraphRAG (11KB prompts) hit session limits immediately
- All 100 instances (50 TDD + 50 GraphRAG) failed with: `"Session limit resets 5am (America/Los_Angeles)"`

### Prompt Size Impact

| Experiment | Prompt Size | Token Usage | Session Impact |
|------------|-------------|-------------|----------------|
| Baseline | 2 KB | ~500 tokens/instance | Used 2h 19m |
| TDD | 7 KB (~3.5× larger) | ~1,750 tokens/instance | Exhausted instantly |
| GraphRAG | 11 KB (~5.5× larger) | ~2,750 tokens/instance | Exhausted instantly |

---

## Solutions

### Option 1: Run Experiments on Separate Days (RECOMMENDED)

**Best for accurate, statistically valid results**

```bash
# Day 1 - Baseline (already completed)
# Result: predictions_20251120_012806.jsonl (46% generation rate)

# Day 2 - TDD Only (after 5am Pacific or next day)
python run_experiments.py --limit 50 --yes --experiments tdd

# Day 3 - GraphRAG Only (after 5am Pacific or next day)
python run_experiments.py --limit 50 --yes --experiments graphrag

# Day 4 - Generate combined report
python generate_comparison_report.py
```

**Advantages:**
- Each experiment gets full session budget
- Optimal conditions for each approach
- Can troubleshoot GraphRAG MCP server separately

---

### Option 2: Run After Session Reset

**Wait until after 5:00 AM Pacific, then run all experiments**

```bash
# Check current Pacific time
TZ='America/Los_Angeles' date

# If after 5:00 AM Pacific, run full suite
python run_experiments.py --limit 50 --yes
```

**Advantages:**
- Single automated run
- All experiments complete in one session

**Risks:**
- May still hit limits if runtime > session budget
- Total estimated time: 8-10 hours (3 experiments × 50 instances)

---

### Option 3: Reduce Instance Count

**Run with fewer instances to fit within available session**

```bash
# Conservative: 15 instances per experiment
python run_experiments.py --limit 15 --yes

# Moderate: 25 instances per experiment
python run_experiments.py --limit 25 --yes
```

**Advantages:**
- Can run immediately
- Still provides valid comparison
- Faster completion (2-4 hours)

**Disadvantages:**
- Smaller sample size
- Less statistical significance

---

### Option 4: Staged Execution with Monitoring

**Run experiments sequentially with session monitoring**

```bash
# Run baseline first (warmup)
python run_experiments.py --limit 50 --yes --experiments baseline

# Check if TDD will fit
# Estimate: If current time < 2:00 AM Pacific, proceed
python run_experiments.py --limit 50 --yes --experiments tdd

# Next day: Run GraphRAG
python run_experiments.py --limit 50 --yes --experiments graphrag
```

---

## Session Budget Estimation

### Baseline Budget Calculation

From actual run data:
- **50 instances × ~3 minutes/instance = 150 minutes (2.5 hours)**
- **Actual runtime: 2h 19m (139 minutes)**
- **Generation rate: 46%**

### TDD Budget Calculation

Estimated based on prompt size increase:
- **50 instances × ~4 minutes/instance = 200 minutes (3.3 hours)**
- **Prompt overhead: +3.5× tokens = +40% time**
- **Estimated: 3-4 hours**

### GraphRAG Budget Calculation

Estimated based on prompt size + graph building:
- **Graph building: ~30-60s per unique repo (first time)**
- **Processing: 50 instances × ~5 minutes/instance = 250 minutes**
- **Estimated: 4-5 hours**

### Total for All Three

```
Baseline:  2.5 hours
TDD:       3.5 hours
GraphRAG:  4.5 hours
--------------------------
Total:     10.5 hours
```

**Verdict:** Running all three sequentially will exceed most session budgets.

---

## Best Practices

### 1. Check Pacific Time Before Running

```bash
# Show current Pacific time
TZ='America/Los_Angeles' date

# If before 5am, calculate remaining session time
```

### 2. Monitor Session Usage

Watch for session limit warnings in output:
```
"Session limit resets 5am (America/Los_Angeles)"
```

If you see this, **STOP IMMEDIATELY** and wait for reset.

### 3. Use Dry Run to Estimate

```bash
# Dry run shows what will execute
python run_experiments.py --limit 50 --dry-run

# Estimate total time from command output
```

### 4. Save Progress Incrementally

The experiment runner automatically saves after each experiment completes:
- `experiment_results_TIMESTAMP.json`
- Individual prediction files

If session expires, you can resume later with `--experiments` flag.

---

## GraphRAG-Specific Considerations

### MCP Server Pre-Start

To avoid initialization delays, pre-start the MCP server:

```bash
# Terminal 1: Start MCP server
cd mcp_server
python server.py

# Terminal 2: Run experiment (connects to existing server)
python code_swe_agent_graphrag.py --limit 50 --mcp-server-url http://localhost:8080
```

**Benefits:**
- No 60-second initialization wait
- Server logs visible for debugging
- Can restart server without restarting experiment

### Server Timeout Increased

The MCP server timeout has been increased from 30s to 60s to handle slow starts.

If server still fails to start:
1. Check Neo4j is installed: `pip install neo4j py2neo`
2. Check port 8080 is available: `lsof -i :8080`
3. Review server logs in terminal

---

## Recommended Workflow for Thesis

### Full 50-Instance Comparison (3-4 days)

**Day 1: Baseline ✓ (Already Complete)**
- File: `predictions_20251120_012806.jsonl`
- Generation rate: 46%
- Status: DONE

**Day 2: TDD Experiment**
```bash
# After 5am Pacific
python run_experiments.py --limit 50 --yes --experiments tdd
```

**Day 3: GraphRAG Experiment**
```bash
# Pre-start MCP server
cd mcp_server
python server.py &

# Run experiment
cd ..
python run_experiments.py --limit 50 --yes --experiments graphrag
```

**Day 4: Generate Comparison Report**
```bash
python generate_comparison_report.py
```

### Quick Test (Same Day, ~2 hours)

```bash
# Use smaller sample for validation
python run_experiments.py --limit 10 --yes
```

---

## Troubleshooting Session Issues

### Error: "Session limit resets 5am"

**Solution 1:** Wait until after 5am Pacific
```bash
# Check time
TZ='America/Los_Angeles' date

# Wait if before 5am, then re-run
```

**Solution 2:** Run experiments on separate days

**Solution 3:** Reduce instance count

### Error: "GraphRAG MCP server failed to start"

**Solution 1:** Pre-start server manually
```bash
cd mcp_server
python server.py
```

**Solution 2:** Increase timeout (already done to 60s)

**Solution 3:** Check dependencies
```bash
pip install -r requirements_mcp.txt
```

### Experiment Runner Stalls

**Check logs:**
```bash
tail -f experiment_comparison.log
```

**Look for:**
- Session limit messages
- MCP connection errors
- Claude Code timeout errors

---

## Summary Checklist

Before running experiments:

- [ ] Check current Pacific time
- [ ] Estimate total runtime (instances × avg time)
- [ ] Ensure session budget available
- [ ] For GraphRAG: Pre-start MCP server (optional)
- [ ] Use `--yes` flag for unattended runs
- [ ] Monitor logs: `tail -f experiment_comparison.log`

For best results:
- ✅ Run experiments on separate days (full session each)
- ✅ Start after 5am Pacific
- ✅ Use smaller instance counts for testing
- ✅ Pre-start GraphRAG MCP server

---

**Remember:** Session limits are a feature, not a bug. Plan your experiments around them for optimal results! 🎓
