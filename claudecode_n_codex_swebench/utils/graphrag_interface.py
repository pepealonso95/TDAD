"""GraphRAG interface factory (local hardened tool or MCP transport)."""

from __future__ import annotations

from typing import Optional

from .graphrag_local_interface import GraphRAGLocalInterface
from .mcp_graphrag_interface import GraphRAGMCPInterface


def create_graphrag_interface(
    *,
    mode: str = "local",
    server_url: Optional[str] = None,
):
    """
    Create GraphRAG interface.

    Modes:
    - local: in-process hardened tool (default)
    - mcp: HTTP/MCP transport
    - auto: try local first, fallback to mcp
    """
    selected = str(mode or "local").strip().lower()
    if selected not in {"local", "mcp", "auto"}:
        raise ValueError(f"Unsupported GraphRAG mode: {mode}")

    if selected == "local":
        return GraphRAGLocalInterface()

    if selected == "mcp":
        return GraphRAGMCPInterface(server_url=server_url or "http://localhost:8080")

    # auto
    try:
        return GraphRAGLocalInterface()
    except Exception:
        return GraphRAGMCPInterface(server_url=server_url or "http://localhost:8080")

