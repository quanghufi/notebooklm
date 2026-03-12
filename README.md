# NotebookLM MCP Server

MCP Server for [Google NotebookLM](https://notebooklm.google.com) — manage notebooks, sources, and Q&A via API.

## ✨ Features

- 🔍 **List & Get** notebooks
- ➕ **Create, Rename, Delete** notebooks
- 📎 **Add Sources** (URL, text)
- 💬 **Q&A** with citations (follow-up conversations supported)
- 📊 **Notebook Summary**
- 🔄 **State machine** with auto-recovery (auth refresh, retry with backoff)

## 🚀 Quick Start

### 1. Install

```bash
# From GitHub
pip install git+https://github.com/quanghufi/notebooklm-mcp.git

# Or clone and install locally
git clone https://github.com/quanghufi/notebooklm-mcp.git
cd notebooklm-mcp
pip install .
```

### 2. Authenticate

```bash
notebooklm-mcp-auth
```

This will guide you to paste cookies from Chrome DevTools. You need cookies from an active NotebookLM session:

1. Open Chrome → https://notebooklm.google.com
2. Make sure you're logged in
3. Open DevTools (F12) → Application → Cookies → `notebooklm.google.com`
4. Copy the required cookies (SID, HSID, SSID, APISID, SAPISID, etc.)

Tokens are cached to `~/.notebooklm-mcp/auth.json`.

### 3. Run the MCP server

```bash
notebooklm-mcp
```

### 4. Configure your MCP client

#### Claude Desktop / Antigravity

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "notebooklm-mcp",
      "transport": "stdio"
    }
  }
}
```

#### VS Code (Copilot)

```json
{
  "mcp": {
    "servers": {
      "notebooklm": {
        "command": "notebooklm-mcp",
        "type": "stdio"
      }
    }
  }
}
```

## 🛠️ Tools

| Tool | Description |
|------|-------------|
| `healthcheck` | Check server status (no API call) |
| `list_notebooks` | List all notebooks |
| `get_notebook` | Get notebook details |
| `create_notebook` | Create a new notebook |
| `rename_notebook` | Rename a notebook |
| `delete_notebook` | Delete a notebook |
| `query_notebook` | Q&A with citations |
| `add_url_source` | Add URL as source |
| `add_text_source` | Add text as source |
| `get_notebook_summary` | Get notebook summary |

## 📁 Architecture

```
notebooklm_mcp/
├── __init__.py      — Package exports
├── server.py        — FastMCP server + state machine (10 tools)
├── api_client.py    — HTTP client (httpx, batchexecute RPC)
├── auth.py          — Token management & caching
├── auth_cli.py      — CLI for authentication
├── constants.py     — API constants & code mappings
└── exceptions.py    — Custom exceptions
```

## 🔧 Development

```bash
# Install in editable mode
pip install -e .

# Check auth status
notebooklm-mcp-auth --check
```

## 📄 License

MIT
