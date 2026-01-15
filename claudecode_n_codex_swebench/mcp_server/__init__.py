"""
TDAD GraphRAG Test Impact Analysis MCP Server

This package provides an MCP server for test impact analysis using GraphRAG.
It indexes Python codebases using AST-based structural chunking and links
unit tests to code via static analysis and coverage data.

Main components:
- server.py: FastAPI MCP server with tool endpoints
- graph_builder.py: AST parsing and Neo4j graph construction
- test_linker.py: Test-to-code relationship mapping
- impact_analyzer.py: Change impact analysis and test selection
- config.py: Configuration management
"""

__version__ = "0.1.0"
__author__ = "Rafael Alonso"
__description__ = "GraphRAG Test Impact Analysis for TDAD Thesis"

from .config import config

__all__ = ["config"]
