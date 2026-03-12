# NotebookLM MCP Server

MCP Server for [Google NotebookLM](https://notebooklm.google.com) — manage notebooks, sources, and Q&A via API.

## Features

- 🔍 **List & Get** notebooks
- ➕ **Create, Rename, Delete** notebooks
- 📎 **Add Sources** (URL, text)
- 💬 **Q&A** with citations (follow-up conversations supported)
- 📊 **Notebook Summary**
- 🔄 **State machine** with auto-recovery (auth refresh, retry with backoff)

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Authenticate

You need Google cookies from an authenticated NotebookLM session. Save them to `~/.notebooklm-mcp/auth.json`:

```json
{
  "cookies": {
    "SID": "...",
    "HSID": "...",
    "SSID": "...",
    "APISID": "...",
    "SAPISID": "...",
    "__Secure-1PSID": "...",
    "__Secure-3PSID": "...",
    "__Secure-1PSIDTS": "...",
    "__Secure-3PSIDTS": "..."
  },
  "csrf_token": "",
  "session_id": "",
  "extracted_at": 0
}
```

> **Tip**: Extract cookies from Chrome DevTools → Application → Cookies → `notebooklm.google.com`

### 3. Run the MCP server

```bash
python run_mcp.py
```

### 4. Configure your MCP client

Add to your MCP config:

```json
{
  "mcpServers": {
    "notebooklm": {
      "command": "python",
      "args": ["path/to/run_mcp.py"],
      "transport": "stdio"
    }
  }
}
```

## Tools

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

## Architecture

```
server.py          — FastMCP server + state machine (10 tools)
run_mcp.py         — Entry point (filters stdout banners)
notebooklm_mcp/    — Core API package
  ├── api_client.py  — HTTP client (httpx)
  ├── auth.py        — Token management
  ├── constants.py   — API constants
  └── exceptions.py  — Custom exceptions
```

## License

MIT
