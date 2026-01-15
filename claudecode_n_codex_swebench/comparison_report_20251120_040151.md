## EXP-005: Full Three-Way Comparison (50 Instances Each)

### Metadata
- **Date**: 2025-11-20 04:01
- **Dataset**: SWE-bench_Verified
- **Sample Size**: 50 instances per experiment
- **Experiments**: Baseline, TDD, GraphRAG

### Executive Summary

**Winner**: 🏆 **Baseline**

**Key Findings:**
- Baseline achieved the highest generation rate (46.0%), 46.0% better than GraphRAG
- Baseline produced the largest patches on average (9292 chars), suggesting more comprehensive fixes
- Baseline had the fewest errors (27), indicating better stability
- GraphRAG identified an average of 0.0 impacted tests per instance, with graph building taking 0.0s on average

### Detailed Metrics Comparison

| Metric | Baseline | TDD | GraphRAG |
|--------|----------|-----|----------|
| **Generation Rate** | 46.0% | 0.0% | 0.0% |
| **Avg Patch Size** | 9,292 chars | 0 chars | 0 chars |
| **Median Patch Size** | 6,453 chars | 0 chars | 0 chars |
| **Errors** | 27 | 50 | 50 |

### GraphRAG-Specific Metrics

- **Total Graphs Built**: 0
- **Avg Graph Build Time**: 0.0s
- **Avg Impacted Tests Found**: 0.0 tests
- **Avg Impact Analysis Time**: 0.00s
- **Test Range**: 0 - 0 tests

### Error Analysis

**Baseline Errors:**
- Execution Failed: 21
- Repository Setup: 6

**TDD Errors:**
- Execution Failed: 50

**GraphRAG Errors:**
- Execution Failed: 39
- Repository Setup: 11

### Recommendations

1. Use Baseline for production SWE-bench evaluation based on overall performance
2. Investigate why TDD has low generation rate - may need prompt refinement
3. Run Docker evaluation to measure actual resolution and regression rates for GraphRAG

### Next Steps

- [ ] Run Docker evaluation on all three prediction sets
- [ ] Calculate resolution rates from evaluation results
- [ ] Measure regression rates for each approach
- [ ] Compare actual test execution times
- [ ] Analyze specific instances where approaches differed

### Prediction Files

- **Baseline**: `predictions_20251120_010951.jsonl`
- **TDD**: `predictions_20251120_032821.jsonl`
- **GraphRAG**: `predictions_graphrag_20251120_034523.jsonl`
