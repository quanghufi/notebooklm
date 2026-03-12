#!/usr/bin/env python3
"""NotebookLM MCP Server for Antigravity — API-based (no browser).

Uses notebooklm_mcp.api_client (HTTP) instead of Selenium.
State machine manages auth lifecycle with proper error classification.
"""

import asyncio
import enum
import json
import logging
import random
import sys
import time
from typing import Any

from mcp.server.fastmcp import FastMCP

# ─── State Machine ───────────────────────────────────────────────

class State(enum.Enum):
    IDLE = "idle"
    AUTHENTICATING = "authenticating"
    READY = "ready"
    RECOVERING = "recovering"
    RATE_LIMITED = "rate_limited"
    ERROR = "error"
    AUTH_EXPIRED = "auth_expired"


# Read-only tools that are safe to auto-retry
READ_ONLY_TOOLS = frozenset([
    "list_notebooks", "get_notebook", "query_notebook",
    "get_notebook_summary", "healthcheck",
])

MAX_RETRY = 3
MAX_RETRY_SECONDS = 30


class AuthError(Exception):
    """Auth failure (401, auth-403, RPC 16)."""
    pass

class PermissionError_(Exception):
    """Permission denied (authz-403, NOT auth)."""
    pass

class RateLimitError(Exception):
    """429 rate limited."""
    pass

class InfraError(Exception):
    """Infrastructure failure (5xx, DNS, timeout)."""
    pass


def classify_error(exc: Exception) -> type:
    """Classify an exception into error categories per the plan."""
    msg = str(exc).lower()
    
    # Check for auth errors
    if "401" in msg or "unauthenticated" in msg or "login_required" in msg:
        return AuthError
    
    # 403 with auth markers → auth failure
    if "403" in msg:
        if "unauthenticated" in msg or "login_required" in msg:
            return AuthError
        if "permission_denied" in msg:
            return PermissionError_
        # 403 without known markers → permission denied (safe default)
        return PermissionError_
    
    # RPC errors
    if "rpc error" in msg:
        if "error 16" in msg or "code 16" in msg:
            return AuthError
        return InfraError
    
    # Rate limiting
    if "429" in msg or "rate" in msg and "limit" in msg:
        return RateLimitError
    
    # 5xx
    if any(f"{code}" in msg for code in [500, 502, 503, 504]):
        return InfraError
    
    # Network / timeout
    if any(kw in msg for kw in ["timeout", "dns", "connect", "network", "unreachable"]):
        return InfraError
    
    # Specific httpx / ValueError from api_client
    if "redirect" in msg and "login" in msg:
        return AuthError
    if "cookies" in msg and ("expired" in msg or "invalid" in msg):
        return AuthError
    
    return InfraError  # Default unknown errors → infra


class ServerState:
    """State machine for managing auth lifecycle."""
    
    def __init__(self):
        self.state = State.IDLE
        self.client = None  # notebooklm_mcp.api_client.NotebookLMClient
        self._lock = asyncio.Lock()
        self._last_error: str | None = None
        self._last_error_time: float = 0
    
    async def ensure_ready(self) -> None:
        """Ensure client is authenticated and ready. Transitions IDLE→READY."""
        if self.state == State.READY and self.client:
            return
        
        if self.state == State.AUTH_EXPIRED:
            raise AuthError(
                "Cookies hết hạn. Chạy 'notebooklm-mcp-auth' để đăng nhập lại, "
                "sau đó restart MCP server."
            )
        
        async with self._lock:
            # Re-check after acquiring lock (another call may have fixed it)
            if self.state == State.READY and self.client:
                return
            
            self.state = State.AUTHENTICATING
            try:
                self.client = await asyncio.to_thread(self._init_client)
                self.state = State.READY
                self._last_error = None
            except AuthError:
                self.state = State.AUTH_EXPIRED
                raise
            except Exception as e:
                err_type = classify_error(e)
                if err_type == AuthError:
                    self.state = State.AUTH_EXPIRED
                    raise AuthError(str(e))
                else:
                    self.state = State.ERROR
                    self._last_error = str(e)
                    self._last_error_time = time.time()
                    raise InfraError(str(e))
    
    async def recover(self) -> None:
        """Try to recover from auth failure by refreshing CSRF."""
        async with self._lock:
            if self.state == State.READY:
                return  # Already recovered by another concurrent call
            
            self.state = State.RECOVERING
            try:
                await asyncio.to_thread(self.client._refresh_auth_tokens)
                self.state = State.READY
                self._last_error = None
            except Exception as e:
                err_type = classify_error(e)
                if err_type == AuthError:
                    self.state = State.AUTH_EXPIRED
                    raise AuthError(
                        "CSRF refresh thất bại — cookies hết hạn. "
                        "Chạy 'notebooklm-mcp-auth' để đăng nhập lại."
                    )
                else:
                    self.state = State.ERROR
                    self._last_error = str(e)
                    self._last_error_time = time.time()
                    raise InfraError(str(e))
    
    async def reload_auth(self) -> None:
        """Reload auth from auth.json (user may have re-authenticated)."""
        async with self._lock:
            self.state = State.AUTHENTICATING
            try:
                self.client = await asyncio.to_thread(self._init_client)
                self.state = State.READY
                self._last_error = None
            except Exception as e:
                err_type = classify_error(e)
                if err_type == AuthError:
                    self.state = State.AUTH_EXPIRED
                    raise AuthError(str(e))
                else:
                    self.state = State.ERROR
                    self._last_error = str(e)
                    raise InfraError(str(e))
    
    def _init_client(self):
        """Initialize API client from cached tokens (runs in thread)."""
        from notebooklm_mcp.auth import load_cached_tokens
        from notebooklm_mcp.api_client import NotebookLMClient
        
        tokens = load_cached_tokens()
        if not tokens:
            raise AuthError(
                "Không tìm thấy auth.json. Chạy 'notebooklm-mcp-auth' để đăng nhập."
            )
        
        if not tokens.cookies:
            raise AuthError("Cookies rỗng trong auth.json.")
        
        # This will auto-refresh CSRF token from the page
        client = NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
        )
        return client


# ─── Server Setup ─────────────────────────────────────────────────

server_state = ServerState()

mcp = FastMCP(
    "notebooklm-api",
    instructions=(
        "NotebookLM MCP Server — quản lý notebooks, sources, và Q&A "
        "qua Google NotebookLM API. Dùng healthcheck để kiểm tra trạng thái."
    ),
)


async def _execute_tool(tool_name: str, fn, *args, **kwargs) -> Any:
    """Execute a tool with state machine error handling and retry logic."""
    is_read_only = tool_name in READ_ONLY_TOOLS
    
    # Ensure client is ready
    await server_state.ensure_ready()
    
    # Try executing
    start_time = time.time()
    attempts = 0
    last_error = None
    
    while True:
        attempts += 1
        try:
            result = await asyncio.to_thread(fn, *args, **kwargs)
            return result
        except Exception as e:
            last_error = e
            err_type = classify_error(e)
            
            if err_type == AuthError:
                # Try recovery
                try:
                    await server_state.recover()
                    # Recovery succeeded, retry once
                    if attempts <= 1:
                        continue
                    raise AuthError(f"Auth recovery succeeded but request still failed: {e}")
                except AuthError:
                    raise  # Propagate auth failure
            
            elif err_type == PermissionError_:
                raise PermissionError_(f"Permission denied: {e}")
            
            elif err_type == RateLimitError:
                if not is_read_only:
                    raise RateLimitError(
                        f"Rate limited. Tool '{tool_name}' là write operation — không auto-retry."
                    )
                server_state.state = State.RATE_LIMITED
                # Fall through to retry logic
            
            elif err_type == InfraError:
                server_state.state = State.ERROR
                server_state._last_error = str(e)
                server_state._last_error_time = time.time()
                if not is_read_only:
                    raise InfraError(
                        f"Lỗi: {e}. Tool '{tool_name}' là write operation — không auto-retry."
                    )
                # Fall through to retry logic
            
            # Retry logic (only for read-only tools)
            elapsed = time.time() - start_time
            if attempts >= MAX_RETRY or elapsed >= MAX_RETRY_SECONDS:
                server_state.state = State.ERROR
                raise InfraError(
                    f"Retry budget hết ({attempts} attempts, {elapsed:.1f}s). Lỗi: {last_error}"
                )
            
            # Exponential backoff with jitter
            delay = min(2 ** attempts + random.uniform(0, 1), 10)
            await asyncio.sleep(delay)
            server_state.state = State.READY  # Reset for retry


# ─── MCP Tools ────────────────────────────────────────────────────

@mcp.tool()
async def healthcheck() -> dict:
    """Check server status. Pure local state read — no API calls."""
    state_info = {
        "state": server_state.state.value,
        "has_client": server_state.client is not None,
    }
    
    if server_state.state == State.AUTH_EXPIRED:
        state_info["message"] = "Chạy 'notebooklm-mcp-auth' để đăng nhập lại."
    elif server_state.state == State.ERROR:
        state_info["message"] = "Lỗi tạm thời. Thử lại sau."
    elif server_state.state == State.READY:
        state_info["message"] = "Sẵn sàng."
    elif server_state.state == State.IDLE:
        state_info["message"] = "Chưa kết nối. Tool call đầu tiên sẽ tự động kết nối."
    
    return state_info


@mcp.tool()
async def list_notebooks() -> list[dict]:
    """List all notebooks in NotebookLM."""
    
    def _run():
        notebooks = server_state.client.list_notebooks()
        return [
            {
                "id": nb.id,
                "title": nb.title,
                "source_count": nb.source_count,
                "created_at": nb.created_at,
                "updated_at": nb.updated_at,
            }
            for nb in notebooks
        ]
    
    return await _execute_tool("list_notebooks", _run)


@mcp.tool()
async def get_notebook(notebook_id: str) -> dict:
    """Get detailed info about a specific notebook including sources.
    
    Args:
        notebook_id: The notebook UUID
    """
    
    def _run():
        # Use the get_notebook RPC
        result = server_state.client._call_rpc(
            server_state.client.RPC_GET_NOTEBOOK,
            json.dumps([notebook_id])
        )
        return {"notebook_id": notebook_id, "data": result}
    
    return await _execute_tool("get_notebook", _run)


@mcp.tool()
async def create_notebook(title: str = "") -> dict:
    """Create a new notebook.
    
    Args:
        title: Optional title for the notebook
    """
    
    def _run():
        nb = server_state.client.create_notebook(title=title)
        if nb:
            return {"id": nb.id, "title": nb.title, "status": "created"}
        return {"status": "failed", "error": "Could not create notebook"}
    
    return await _execute_tool("create_notebook", _run)


@mcp.tool()
async def rename_notebook(notebook_id: str, new_title: str) -> dict:
    """Rename a notebook.
    
    Args:
        notebook_id: The notebook UUID
        new_title: New title for the notebook
    """
    
    def _run():
        success = server_state.client.rename_notebook(notebook_id, new_title)
        return {"status": "renamed" if success else "failed", "new_title": new_title}
    
    return await _execute_tool("rename_notebook", _run)


@mcp.tool()
async def delete_notebook(notebook_id: str) -> dict:
    """Delete a notebook.
    
    Args:
        notebook_id: The notebook UUID
    """
    
    def _run():
        success = server_state.client.delete_notebook(notebook_id)
        return {"status": "deleted" if success else "failed"}
    
    return await _execute_tool("delete_notebook", _run)


@mcp.tool()
async def query_notebook(
    notebook_id: str,
    question: str,
    conversation_id: str | None = None,
) -> dict:
    """Ask a question about a notebook's content (Q&A with citations).
    
    Args:
        notebook_id: The notebook UUID
        question: The question to ask
        conversation_id: Optional ID for follow-up questions in same conversation
    """
    
    def _run():
        result = server_state.client.query(
            notebook_id=notebook_id,
            query_text=question,
            conversation_id=conversation_id,
        )
        if result:
            return {
                "answer": result.get("answer", ""),
                "conversation_id": result.get("conversation_id", ""),
                "turn_number": result.get("turn_number", 1),
                "is_follow_up": result.get("is_follow_up", False),
            }
        return {"error": "No response from NotebookLM"}
    
    return await _execute_tool("query_notebook", _run)


@mcp.tool()
async def add_url_source(notebook_id: str, url: str) -> dict:
    """Add a URL as a source to a notebook.
    
    Args:
        notebook_id: The notebook UUID
        url: The URL to add as a source
    """
    
    def _run():
        result = server_state.client.add_url_source(notebook_id, url)
        if result:
            return {"status": "added", "source": result}
        return {"status": "failed", "error": "Could not add URL source"}
    
    return await _execute_tool("add_url_source", _run)


@mcp.tool()
async def add_text_source(
    notebook_id: str,
    text: str,
    title: str = "Pasted Text",
) -> dict:
    """Add text content as a source to a notebook.
    
    Args:
        notebook_id: The notebook UUID
        text: The text content to add
        title: Title for the text source
    """
    
    def _run():
        result = server_state.client.add_text_source(notebook_id, text, title=title)
        if result:
            return {"status": "added", "source": result}
        return {"status": "failed", "error": "Could not add text source"}
    
    return await _execute_tool("add_text_source", _run)


@mcp.tool()
async def get_notebook_summary(notebook_id: str) -> dict:
    """Get a summary of a notebook's content.
    
    Args:
        notebook_id: The notebook UUID
    """
    
    def _run():
        result = server_state.client.get_notebook_summary(notebook_id)
        return result if result else {"error": "Could not get summary"}
    
    return await _execute_tool("get_notebook_summary", _run)


# ─── Entry Point ──────────────────────────────────────────────────

def create_server() -> FastMCP:
    """Create and return the MCP server instance."""
    return mcp


async def main():
    """Run the MCP server via stdio."""
    await mcp.run(transport="stdio")


if __name__ == "__main__":
    asyncio.run(main())
