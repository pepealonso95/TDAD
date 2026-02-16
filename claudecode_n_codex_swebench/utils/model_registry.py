"""Model registry for Claude Code and Codex backends."""

from typing import Dict

# Claude models
CLAUDE_MODELS: Dict[str, str] = {
    # Opus models (most capable)
    "opus-4.1": "opus",
    "opus-4.0": "opus",
    "opus-4": "opus",
    "opus": "opus",

    # Sonnet models - use Claude Code aliases
    "sonnet-4.5": "sonnet",
    "sonnet-4": "sonnet",
    "sonnet-3.7": "sonnet",
    "sonnet-3.6": "sonnet",
    "sonnet-3.5": "sonnet",
    "sonnet": "sonnet",

    # Haiku models (fastest)
    "haiku-4.5": "haiku",
    "haiku-4": "haiku",
    "haiku": "haiku",

    # Aliases
    "best": "opus",
    "balanced": "sonnet",
    "fast": "haiku",
    "fastest": "haiku",
    "latest": "sonnet",
    "claude-code": "sonnet",
}

CLAUDE_DESCRIPTIONS = {
    "opus-4.1": "Opus 4.1 - Latest and most capable",
    "opus-4.0": "Opus 4.0 - Very strong performance",
    "sonnet-4": "Sonnet 4 - New generation balanced model",
    "sonnet-3.7": "Sonnet 3.7 - Latest 3.x series",
    "sonnet-3.6": "Sonnet 3.6 - Solid performance",
    "sonnet-3.5": "Sonnet 3.5 - Fast and efficient",
}

CLAUDE_CATEGORIES = {
    "Opus Models (Most Capable)": ["opus-4.1", "opus-4.0"],
    "Sonnet Models (Balanced)": ["sonnet-4", "sonnet-3.7", "sonnet-3.6", "sonnet-3.5"],
    "Quick Aliases": ["best", "balanced", "fast"],
}

CLAUDE_EXPECTED = {
    "opus-4.1": {"min": 30, "max": 40, "typical": 35},
    "opus-4.0": {"min": 25, "max": 35, "typical": 30},
    "sonnet-4": {"min": 20, "max": 30, "typical": 25},
    "sonnet-3.7": {"min": 18, "max": 25, "typical": 21},
    "sonnet-3.6": {"min": 15, "max": 22, "typical": 18},
    "sonnet-3.5": {"min": 12, "max": 20, "typical": 15},
}

# Codex models (example aliases)
CODEX_MODELS: Dict[str, str] = {
    "codex-4.2": "gpt-4.2-codex",
    "codex-latest": "gpt-4.2-codex",
    "codex": "codex-latest",
    "best": "gpt-4.2-codex",
}

CODEX_DESCRIPTIONS = {
    "codex-4.2": "GPT-4.2 Codex - Latest model",
    "codex-latest": "Alias for the latest Codex model",
}

CODEX_CATEGORIES = {
    "Codex Models": ["codex-4.2", "codex-latest"],
    "Quick Aliases": ["best"],
}

CODEX_EXPECTED = {
    "codex-4.2": {"min": 20, "max": 35, "typical": 28},
}

# Qwen models (Ollama-based)
QWEN_MODELS: Dict[str, str] = {
    "qwen3-coder-30b": "qwen3-coder:30b",
    "qwen3-coder:30b": "qwen3-coder:30b",
    "qwen3-coder": "qwen3-coder:30b",
    "qwen-latest": "qwen3-coder:30b",
    "qwen": "qwen3-coder:30b",
    "best": "qwen3-coder:30b",
    "latest": "qwen3-coder:30b",
}

QWEN_DESCRIPTIONS = {
    "qwen3-coder-30b": "Qwen 3 Coder 30B - Latest Qwen coding model",
    "qwen3-coder": "Alias for Qwen 3 Coder 30B",
    "qwen-latest": "Latest Qwen model available",
}

QWEN_CATEGORIES = {
    "Qwen Models": ["qwen3-coder-30b", "qwen3-coder"],
    "Quick Aliases": ["best", "latest"],
}

QWEN_EXPECTED = {
    "qwen3-coder-30b": {"min": 15, "max": 30, "typical": 22},
}

# Qwen-Mini models (Mini-SWE-Agent + Ollama)
QWEN_MINI_MODELS: Dict[str, str] = {
    "qwen-mini": "qwen3-coder:30b",
    "qwen3-mini": "qwen3-coder:30b",
    "mini": "qwen3-coder:30b",
    "latest": "qwen3-coder:30b",
}

QWEN_MINI_DESCRIPTIONS = {
    "qwen-mini": "Qwen 30B via Mini-SWE-Agent + Ollama (proven 74% on SWE-bench)",
    "qwen3-mini": "Alias for qwen-mini",
    "mini": "Short alias for qwen-mini",
}

QWEN_MINI_CATEGORIES = {
    "Qwen-Mini Models": ["qwen-mini", "qwen3-mini"],
    "Quick Aliases": ["mini", "latest"],
}

QWEN_MINI_EXPECTED = {
    "qwen-mini": {"min": 40, "max": 75, "typical": 57},  # Based on mini-swe-agent's 74% benchmark
}


def _resolve(models: Dict[str, str], alias: str, seen=None) -> str:
    if seen is None:
        seen = set()

    if alias in seen:
        # Circular reference detected, return as-is
        return alias

    if alias in models:
        resolved = models[alias]
        if resolved == alias:
            # Self-reference, return as-is
            return alias
        if resolved in models:
            seen.add(alias)
            return _resolve(models, resolved, seen)
        return resolved
    return alias


def get_model_name(alias: str, backend: str = "claude") -> str:
    """Return the full model name for the given alias and backend."""
    if not alias:
        return None
    backend = backend.lower()
    if backend == "codex":
        models = CODEX_MODELS
    elif backend == "qwen":
        models = QWEN_MODELS
    elif backend == "qwen-mini":
        models = QWEN_MINI_MODELS
    else:
        models = CLAUDE_MODELS
    if alias in models:
        return _resolve(models, alias)
    return alias


def list_models(backend: str = "claude") -> str:
    """Generate a formatted list of available models for the backend."""
    backend = backend.lower()
    if backend == "codex":
        categories = CODEX_CATEGORIES
        descriptions = CODEX_DESCRIPTIONS
        title = "Available Codex Models"
    elif backend == "qwen":
        categories = QWEN_CATEGORIES
        descriptions = QWEN_DESCRIPTIONS
        title = "Available Qwen Models"
    elif backend == "qwen-mini":
        categories = QWEN_MINI_CATEGORIES
        descriptions = QWEN_MINI_DESCRIPTIONS
        title = "Available Qwen-Mini Models"
    else:
        categories = CLAUDE_CATEGORIES
        descriptions = CLAUDE_DESCRIPTIONS
        title = "Available Claude Models"

    lines = [title + ":", "=" * 50]
    for category, models in categories.items():
        lines.append(f"\n{category}:")
        for model in models:
            desc = descriptions.get(model, "")
            full_name = get_model_name(model, backend)
            if desc:
                lines.append(f"  {model:<12} - {desc}")
            else:
                lines.append(f"  {model:<12} -> {full_name}")
    return "\n".join(lines)


def validate_model(alias: str) -> bool:
    """Validate that a model alias is non-empty."""
    return bool(alias)


def get_expected_performance(model: str, backend: str = "claude") -> dict:
    """Get expected SWE-bench performance for a model."""
    backend = backend.lower()
    if backend == "codex":
        models = CODEX_MODELS
        expectations = CODEX_EXPECTED
    elif backend == "qwen":
        models = QWEN_MODELS
        expectations = QWEN_EXPECTED
    elif backend == "qwen-mini":
        models = QWEN_MINI_MODELS
        expectations = QWEN_MINI_EXPECTED
    else:
        models = CLAUDE_MODELS
        expectations = CLAUDE_EXPECTED
    full_model = get_model_name(model, backend)
    for alias, full in models.items():
        if full == full_model or alias == model:
            if alias in expectations:
                return expectations[alias]
    return {"min": 10, "max": 30, "typical": 20}
