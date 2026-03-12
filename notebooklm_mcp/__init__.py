"""
NotebookLM MCP — API Client Package

Lightweight package containing only the HTTP API client for NotebookLM.
No browser automation or monitoring dependencies.
"""

__version__ = "1.0.0"

from .api_client import NotebookLMClient, Notebook
from .auth import AuthTokens, load_cached_tokens, save_tokens_to_cache

__all__ = [
    "NotebookLMClient",
    "Notebook",
    "AuthTokens",
    "load_cached_tokens",
    "save_tokens_to_cache",
]

