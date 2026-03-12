#!/usr/bin/env python3
"""Entry point for NotebookLM MCP Server.

Filters stdout to suppress ASCII art banners that break JSON-RPC.
"""

import asyncio
import io
import sys


class FilteredStdout(io.TextIOBase):
    """Filter that suppresses non-JSON content on stdout.
    
    The notebooklm-mcp-server package prints ASCII art banners
    on import which breaks MCP's JSON-RPC protocol over stdio.
    This filter only passes through JSON-RPC messages (lines starting with {).
    """
    
    def __init__(self, original):
        self._original = original
        self._buffer_str = ""
    
    def write(self, data):
        self._buffer_str += data
        while "\n" in self._buffer_str:
            line, self._buffer_str = self._buffer_str.split("\n", 1)
            # Pass JSON-RPC messages and MCP protocol lines
            stripped = line.strip()
            if stripped.startswith("{") or stripped.startswith("["):
                self._original.write(line + "\n")
                self._original.flush()
        return len(data)
    
    def flush(self):
        if self._buffer_str.strip().startswith(("{", "[")):
            self._original.write(self._buffer_str)
            self._original.flush()
        self._buffer_str = ""
    
    def fileno(self):
        return self._original.fileno()
    
    def writable(self):
        return True
    
    def readable(self):
        return False
    
    @property
    def buffer(self):
        return self._original.buffer
    
    @property
    def encoding(self):
        return self._original.encoding


def main():
    # Patch stdout to filter banners BEFORE importing the package
    original_stdout = sys.stdout
    sys.stdout = FilteredStdout(original_stdout)
    
    # Import our server and call mcp.run() directly (sync).
    # FastMCP.run() internally uses anyio.run() to create its own event loop,
    # so we must NOT wrap it in asyncio.run() — that causes nested loop errors.
    from server import create_server
    server = create_server()
    server.run(transport="stdio")


if __name__ == "__main__":
    main()
