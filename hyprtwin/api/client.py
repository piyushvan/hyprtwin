import json
import logging
import os
import sqlite3
import sys
from pathlib import Path

import requests

from hyprtwin.system.config import DB_PATH, PROFILE_PATH

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

# NEW: Agent profile support
ACTIVE_PROFILE_PATH = Path("~/.config/hyprtwin/active_profile.txt").expanduser()
PROFILE_GRAMMAR_DIR = Path("~/.config/hyprtwin/grammars/").expanduser()

# Profile mapping: name -> (hint_token, grammar_filename)
# Grammar files are optional. If None, no grammar constraint.
PROFILE_MAP = {
    "general": ("", None),
    "gitmaster": ("[Git]", "git.gbnf"),
    "sysadmin": ("[Sys]", "sysadmin.gbnf"),
    "architect": ("[Arch]", "architect.gbnf"),
}


def get_active_profile() -> tuple[str, str | None]:
    """Returns (hint_token, grammar_file_path) for the current profile."""
    if not ACTIVE_PROFILE_PATH.exists():
        return PROFILE_MAP["general"]
    profile_name = ACTIVE_PROFILE_PATH.read_text().strip().lower()
    hint, grammar_file = PROFILE_MAP.get(profile_name, PROFILE_MAP["general"])
    grammar_path = None
    if grammar_file:
        grammar_path = PROFILE_GRAMMAR_DIR / grammar_file
        if not grammar_path.exists():
            logging.warning(f"Grammar file {grammar_path} not found. Ignoring.")
            grammar_path = None
    return hint, grammar_path


# Database connection reuse (thread-local, but we're single-threaded)
_db_conn = None


def get_db_connection():
    global _db_conn
    if _db_conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _db_conn = sqlite3.connect(DB_PATH, timeout=10.0)
        _db_conn.execute("PRAGMA journal_mode=WAL;")
        _db_conn.execute("""CREATE TABLE IF NOT EXISTS messages
                            (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT)""")
        _db_conn.commit()
    return _db_conn


def init_db():
    """Legacy compatibility – returns a connection but we reuse."""
    return get_db_connection()


def get_history(safe_token_limit: int):
    """Retrieves history dynamically, sliding backwards to fit the budget."""
    conn = get_db_connection()
    c = conn.cursor()
    # Fetch a generous pool of recent messages
    c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT 20")
    rows = c.fetchall()

    history = []
    current_tokens = 0

    # 1 token ≈ 4 characters (simple estimator)
    for role, content in rows:
        msg_tokens = len(content) // 4
        if current_tokens + msg_tokens > safe_token_limit:
            break
        history.append({"role": role, "content": content})
        current_tokens += msg_tokens

    return list(reversed(history))


def save_message(role, content):
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))
    conn.commit()


def clear_history():
    conn = get_db_connection()
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()


def handshake():
    """Trigger the system greeting."""
    ask_server(
        "You are HyprTwin. You just booted successfully. Say a very short, cool 'system online' greeting.",
        quick=True,
    )


def _build_payload(query, piped_context, max_ctx, quick):
    """Builds the LLM payload with budget-aware history and agent profile injection."""
    # NEW: Get profile hint and grammar
    profile_hint, grammar_path = get_active_profile()

    # Construct the user message with hint injected at the beginning
    user_content = f"{profile_hint} {query}".strip()
    if piped_context:
        full_prompt = f"SYSTEM CONTEXT:\n{piped_context}\n\nUSER QUERY: {user_content}"
    else:
        full_prompt = user_content

    system_prompt = "You are a bare-metal Linux OS assistant. Be highly concise."

    current_query_tokens = (len(full_prompt) + len(system_prompt)) // 4
    # Reserve 512 tokens for response
    safe_history_budget = max_ctx - current_query_tokens - 512

    messages = [{"role": "system", "content": system_prompt}]

    if not quick and safe_history_budget > 0:
        messages.extend(get_history(safe_history_budget))

    messages.append({"role": "user", "content": full_prompt})
    return messages, full_prompt, grammar_path


def ask_server(query: str, piped_context: str = None, quick: bool = False):
    # Load config safely
    max_ctx = 2048
    if os.path.exists(PROFILE_PATH):
        try:
            with open(PROFILE_PATH, "r") as f:
                max_ctx = json.load(f).get("context_size", 2048)
        except (json.JSONDecodeError, IOError):
            logging.warning("Failed to load profile, using default context.")

    messages, full_prompt, grammar_path = _build_payload(
        query, piped_context, max_ctx, quick
    )

    payload = {
        "messages": messages,
        "temperature": 0.3,
        "stream": True,
    }
    # NEW: Add grammar if available (llama-server supports 'grammar' field in /v1/chat/completions)
    if grammar_path:
        with open(grammar_path, "r") as gf:
            grammar_str = gf.read()
            payload["grammar"] = grammar_str

    try:
        response = requests.post(
            "http://127.0.0.1:8080/v1/chat/completions", json=payload, stream=True
        )
        response.raise_for_status()
    except requests.exceptions.RequestException as e:
        logging.error(f"Engine communication failed: {e}")
        print(
            "[!] Hint: Your piped file or memory history exceeds the loaded Context Window."
        )
        sys.exit(1)

    print("\n🤖 Twin: ", end="", flush=True)
    full_response = ""

    # IMPROVED: Stream line-by-line, no extra buffering
    for line in response.iter_lines():
        if line:
            try:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: ") and decoded != "data: [DONE]":
                    chunk = json.loads(decoded[6:])
                    content = chunk["choices"][0]["delta"].get("content")
                    if content is not None:
                        print(content, end="", flush=True)
                        full_response += content
            except (json.JSONDecodeError, KeyError):
                continue
    print("\n")

    if not quick:
        save_message("user", full_prompt)
        save_message("assistant", full_response)
