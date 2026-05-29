import json
import os
import sqlite3
import sys

import requests

DB_PATH = os.path.expanduser("~/.local/share/twin/history.db")


def init_db():
    """Initializes the Tier 1 Memory Database with WAL concurrency."""
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)

    # Added a 10-second timeout so concurrent commands wait instead of crashing
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    c = conn.cursor()

    # FIX: Enable Write-Ahead Logging to prevent "database is locked" errors
    c.execute("PRAGMA journal_mode=WAL;")

    c.execute("""CREATE TABLE IF NOT EXISTS messages
                 (id INTEGER PRIMARY KEY AUTOINCREMENT, role TEXT, content TEXT)""")
    conn.commit()
    return conn


def get_history(limit=6):
    """Retrieves the last 6 messages to inject as context."""
    conn = init_db()
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    # Reverse to restore chronological order
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def save_message(role, content):
    """Saves a message to the memory database."""
    conn = init_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))
    conn.commit()
    conn.close()


def clear_history():
    """Wipes the database."""
    conn = init_db()
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()


def ask_server(query: str, piped_context: str = None, quick: bool = False):
    """Formats the payload, hits the C++ socket, and streams the response."""
    full_prompt = query
    if piped_context:
        full_prompt = f"SYSTEM CONTEXT:\n{piped_context}\n\nUSER QUERY: {query}"

    messages = [
        {
            "role": "system",
            "content": "You are a bare-metal Linux OS assistant. Be highly concise.",
        }
    ]

    if not quick:
        history = get_history()
        messages.extend(history)

    messages.append({"role": "user", "content": full_prompt})

    payload = {
        "messages": messages,
        "temperature": 0.3,
        "stream": True,  # We are streaming the output to feel instantaneous!
    }

    try:
        response = requests.post(
            "http://127.0.0.1:8080/v1/chat/completions", json=payload, stream=True
        )
        response.raise_for_status()
    except requests.exceptions.ConnectionError:
        print(
            "[-] Error: The engine is cold. Run 'twin build' first to boot the server."
        )
        sys.exit(1)
    except requests.exceptions.HTTPError as e:
        print(
            f"\n[-] Error: The AI engine rejected the request (HTTP {response.status_code})."
        )
        try:
            # Try to grab the exact error reason from the llama.cpp server
            error_data = response.json()
            print(
                f"[*] Server Response: {error_data.get('error', {}).get('message', response.text)}"
            )
        except Exception:
            pass
        print(
            "[!] Hint: Your piped file or memory history exceeds the loaded Context Window."
        )
        sys.exit(1)

    print("\n🤖 Twin: ", end="", flush=True)
    full_response = ""

    # Beautiful streaming logic
    for line in response.iter_lines():
        if line:
            decoded = line.decode("utf-8")
            if decoded.startswith("data: ") and decoded != "data: [DONE]":
                try:
                    chunk = json.loads(decoded[6:])
                    content = chunk["choices"][0]["delta"].get("content")

                    # The Fix: Ensure content actually exists and isn't 'None'
                    if content is not None:
                        print(content, end="", flush=True)
                        full_response += content
                except json.JSONDecodeError:
                    pass
    print("\n")

    if not quick:
        save_message("user", full_prompt)
        save_message("assistant", full_response)
