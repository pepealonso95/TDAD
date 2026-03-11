# GraphRAG TDD Agent Flow

This document shows the current `graphrag_tdd` architecture after the recent lifecycle change:

- the structural graph is built once per instance
- the graph is not re-indexed after code edits
- GraphRAG runs only on changed source files from a non-empty patch
- targeted coverage updates enrich graph links, but do not rebuild the graph

## 1. High-Level Component Flow

```mermaid
graph TD
    A["BenchmarkRunner<br/>run_benchmark.py"] --> B["GraphRAGCodeSWEAgent<br/>code_swe_agent_graphrag.py"]
    B --> C["QwenMiniInterfaceGraphRAGTDD<br/>TDD prompt baseline plus GraphRAG"]
    B --> D["GraphRAGLocalInterface<br/>local mode"]

    D --> E["Initial build_graph<br/>once per instance"]
    E --> F["GraphBuilder"]
    F --> G["Neo4j GraphDB"]
    F --> H["TestLinker link_tests<br/>static test links"]

    C --> I["Default codegen round"]
    I --> J{"Non empty patch<br/>and changed source files"}

    J -- No --> K["Skip GraphRAG query<br/>continue normal TDD retry loop"]
    J -- Yes --> L["run_graphrag_impact_query"]
    L --> M["run_impacted_tests_iteratively<br/>require_fresh_graph false"]
    M --> N["get_impacted_tests<br/>source files only"]
    N --> O["ImpactAnalyzer<br/>graph or hybrid selection"]
    O --> G

    M --> P["TestRunner run_tests<br/>on impacted tests"]
    P --> Q["TestLinker record_targeted_test_coverage"]
    Q -. enrich only .-> G

    P --> R{"Reliable named<br/>regression failures"}
    R -- Yes --> S["regression_repair round"]
    R -- No --> T["No regression repair<br/>fall back or continue"]

    G -. frozen for instance .-> U["No incremental refresh<br/>No rebuild after edits"]
```

## 2. Single-Instance Sequence

```mermaid
sequenceDiagram
    participant BR as BenchmarkRunner
    participant AG as GraphRAGCodeSWEAgent
    participant QI as QwenMiniInterfaceGraphRAGTDD
    participant GI as GraphRAGLocalInterface
    participant GB as GraphBuilder
    participant DB as Neo4j GraphDB
    participant IA as ImpactAnalyzer
    participant TL as TestRunner and TestLinker

    BR->>AG: execute instance
    AG->>QI: execute_code_cli

    Note over AG,GI: GraphRAG is hard-pinned to local mode
    AG->>GI: build_graph force_rebuild false
    GI->>GB: build_graph repo and base_commit
    GB->>DB: persist nodes + edges
    GB->>TL: link static tests
    GI-->>AG: graph ready

    QI->>QI: default codegen round

    alt patch is non-empty and changed source files exist
        QI->>GI: run_impacted_tests_iteratively require_fresh_graph false
        GI->>IA: get_impacted_tests source_changed_files
        IA->>DB: query graph / hybrid impact
        GI->>TL: run selected impacted tests
        TL->>DB: record targeted coverage links
        TL-->>GI: failed tests + execution metadata
        GI-->>QI: impacted test results

        alt reliable failing regression tests returned
            QI->>QI: start regression_repair round
        else no useful regression signal
            QI->>QI: deterministic fallback or normal retry
        end
    else patch empty or only test-file changes
        QI->>QI: skip GraphRAG impact query
    end

    Note over GI,DB: No post edit rebuild or incremental refresh when graph_refresh_policy is initial_only
```

## 3. Decision Logic

```mermaid
graph TD
    A["Patch candidate produced"] --> B{"Patch non empty"}
    B -- No --> C["Do not call GraphRAG"]
    B -- Yes --> D["Collect changed files"]
    D --> E["Filter to source py files only"]
    E --> F{"Any changed source files"}
    F -- No --> G["Do not call GraphRAG"]
    F -- Yes --> H["Query frozen graph<br/>require_fresh_graph false"]
    H --> I{"Impacted tests selected<br/>and runnable"}
    I -- Yes --> J["Run impacted tests"]
    I -- No --> K["Run bounded fallback tests"]
    K --> L["Record targeted coverage links"]
    J --> M{"Reliable named failures"}
    K --> M
    M -- Yes --> N["regression_repair round"]
    M -- No --> O["Return to normal retry and scoring"]
```

## 4. What No Longer Happens

```mermaid
graph LR
    A["Code edit creates dirty working tree"] -. no longer triggers .-> B["incremental_update"]
    A -. no longer triggers .-> C["build_graph force_rebuild true"]
    A -. no longer triggers .-> D["stagnation reprobe"]
    E["targeted coverage link write"] -. does not imply .-> B
    E -. does not imply .-> C
```

## 5. Practical Reading Guide

- `run_benchmark.py`
  - chooses `graphrag_tdd`
  - applies effective controls
  - forces `graphrag_tool_mode=local`
  - sets `graph_refresh_policy=initial_only`
- `code_swe_agent_graphrag.py`
  - constructs the agent and passes GraphRAG config into the qwen-mini interface
- `utils/qwen_mini_interface.py`
  - runs the main attempt loop
  - decides when GraphRAG should be queried
  - starts `regression_repair` only when the returned regression signal is reliable
- `utils/graphrag_local_interface.py`
  - builds the graph once
  - serves impacted-test queries locally
  - records targeted coverage links after already-selected tests run
- `mcp_server/impact_analyzer.py`
  - selects impacted tests from the existing graph

If you want, I can add a second Markdown file that focuses only on the retry loop and shows where `default`, `test_repair`, `regression_repair`, and `compile_repair` connect. 
