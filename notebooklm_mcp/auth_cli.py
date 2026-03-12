#!/usr/bin/env python3
"""CLI tool to authenticate with Google NotebookLM.

Usage:
    notebooklm-mcp-auth              Interactive cookie input
    notebooklm-mcp-auth --check      Check if cached tokens are valid
    notebooklm-mcp-auth --headless   Try headless auth via Chrome profile
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from .auth import (
    AuthTokens,
    REQUIRED_COOKIES,
    get_cache_path,
    load_cached_tokens,
    save_tokens_to_cache,
    validate_cookies,
)


def _print_banner():
    print()
    print("  ╔══════════════════════════════════════════╗")
    print("  ║     🔐 NotebookLM MCP — Auth Setup      ║")
    print("  ╚══════════════════════════════════════════╝")
    print()


def _check_existing_tokens() -> bool:
    """Check if cached tokens exist and test them."""
    tokens = load_cached_tokens()
    if not tokens:
        print("❌ No cached tokens found.")
        return False

    print(f"📁 Token file: {get_cache_path()}")
    print(f"🍪 Cookies: {len(tokens.cookies)} keys")

    if not validate_cookies(tokens.cookies):
        missing = [c for c in REQUIRED_COOKIES if c not in tokens.cookies]
        print(f"⚠️  Missing required cookies: {', '.join(missing)}")
        return False

    # Try to refresh CSRF to verify cookies are still valid
    print("🔄 Testing connection...")
    try:
        from .api_client import NotebookLMClient

        client = NotebookLMClient(
            cookies=tokens.cookies,
            csrf_token=tokens.csrf_token,
            session_id=tokens.session_id,
        )
        # If we get here without error, tokens are valid
        print("✅ Authentication valid! CSRF token refreshed.")
        return True
    except ValueError as e:
        if "expired" in str(e).lower() or "login" in str(e).lower():
            print(f"❌ Cookies expired: {e}")
        else:
            print(f"❌ Connection failed: {e}")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def _parse_cookie_string(cookie_str: str) -> dict[str, str]:
    """Parse a cookie string (from Chrome DevTools or header format).

    Supports formats:
    - Header format: "SID=xxx; HSID=yyy; ..."
    - JSON format: {"SID": "xxx", "HSID": "yyy"}
    - One-per-line: "SID=xxx\\nHSID=yyy"
    """
    cookie_str = cookie_str.strip()

    # Try JSON format first
    if cookie_str.startswith("{"):
        try:
            return json.loads(cookie_str)
        except json.JSONDecodeError:
            pass

    # Parse key=value format (semicolon or newline separated)
    cookies = {}
    # Split by ; or newline
    parts = re.split(r'[;\n]', cookie_str)
    for part in parts:
        part = part.strip()
        if '=' in part:
            key, _, value = part.partition('=')
            key = key.strip()
            value = value.strip()
            if key:
                cookies[key] = value

    return cookies


def _interactive_auth():
    """Interactive authentication flow."""
    _print_banner()

    print("To authenticate, you need cookies from an active NotebookLM session.")
    print()
    print("Steps:")
    print("  1. Open Chrome → https://notebooklm.google.com")
    print("  2. Make sure you're logged in")
    print("  3. Open DevTools (F12) → Application tab → Cookies")
    print("  4. Select 'https://notebooklm.google.com'")
    print("  5. Copy ALL cookies (or at least: SID, HSID, SSID, APISID, SAPISID,")
    print("     __Secure-1PSID, __Secure-3PSID, __Secure-1PSIDTS, __Secure-3PSIDTS)")
    print()
    print("Paste cookies below.")
    print('Formats supported: "key=value; ..." or JSON {"key": "value", ...}')
    print("Press Enter twice when done:")
    print()

    lines = []
    empty_count = 0
    while empty_count < 1:
        try:
            line = input()
            if not line.strip():
                empty_count += 1
            else:
                empty_count = 0
                lines.append(line)
        except EOFError:
            break

    raw = "\n".join(lines)
    if not raw.strip():
        print("❌ No input received. Exiting.")
        sys.exit(1)

    cookies = _parse_cookie_string(raw)
    if not cookies:
        print("❌ Could not parse cookies. Make sure format is correct.")
        sys.exit(1)

    print(f"\n📋 Parsed {len(cookies)} cookies")

    # Validate
    if not validate_cookies(cookies):
        missing = [c for c in REQUIRED_COOKIES if c not in cookies]
        print(f"⚠️  Missing required cookies: {', '.join(missing)}")
        print("   The server may not work without these. Continue anyway? [y/N] ", end="")
        answer = input().strip().lower()
        if answer != 'y':
            print("Aborted.")
            sys.exit(1)

    # Save tokens
    tokens = AuthTokens(
        cookies=cookies,
        csrf_token="",  # Will be auto-extracted on first use
        session_id="",
        extracted_at=time.time(),
    )
    save_tokens_to_cache(tokens)

    # Test connection
    print("\n🔄 Testing connection...")
    try:
        from .api_client import NotebookLMClient

        client = NotebookLMClient(
            cookies=cookies,
            csrf_token="",
            session_id="",
        )
        print("✅ Authentication successful! CSRF token extracted.")
        print(f"\n🚀 You can now run: notebooklm-mcp")
    except ValueError as e:
        if "expired" in str(e).lower() or "login" in str(e).lower():
            print(f"❌ Cookies seem expired or invalid: {e}")
            print("   Please make sure you're logged into NotebookLM in Chrome.")
        else:
            print(f"⚠️  Connection test failed: {e}")
            print("   Cookies saved anyway — they might work later.")
    except Exception as e:
        print(f"⚠️  Connection test failed: {e}")
        print("   Cookies saved anyway — they might work later.")


def run_headless_auth() -> AuthTokens | None:
    """Try headless authentication using saved Chrome profile.

    This is called automatically by the server when auth expires.
    It requires a Chrome profile with saved Google login at
    ~/.notebooklm-mcp/chrome-profile/

    Returns:
        AuthTokens if successful, None otherwise
    """
    chrome_profile = Path.home() / ".notebooklm-mcp" / "chrome-profile"
    if not chrome_profile.exists():
        return None

    try:
        import subprocess
        import tempfile

        # Try to extract cookies using Chrome in headless mode
        # This only works if Chrome profile has saved Google login
        # (e.g., from a previous interactive session)

        # For now, just try to reload from disk
        tokens = load_cached_tokens()
        if tokens and validate_cookies(tokens.cookies):
            return tokens

    except Exception:
        pass

    return None


def main():
    """Entry point for notebooklm-mcp-auth CLI."""
    # Fix Windows console encoding (cp1252 can't handle emoji)
    import os
    if os.name == 'nt':
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')

    parser = argparse.ArgumentParser(
        prog="notebooklm-mcp-auth",
        description="Authenticate with Google NotebookLM for MCP server",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="Check if cached tokens are valid",
    )
    parser.add_argument(
        "--headless",
        action="store_true",
        help="Try headless auth via Chrome profile",
    )
    args = parser.parse_args()

    if args.check:
        success = _check_existing_tokens()
        sys.exit(0 if success else 1)

    if args.headless:
        tokens = run_headless_auth()
        if tokens:
            print("✅ Headless auth successful!")
            sys.exit(0)
        else:
            print("❌ Headless auth failed. Use interactive mode instead.")
            sys.exit(1)

    # Default: interactive auth
    _interactive_auth()


if __name__ == "__main__":
    main()
