import http.client
import json
import os
import profile
import socket as sock
import sqlite3
import sys
from json.decoder import JSONDecodeError
from multiprocessing import context

DB_PATH = os.path.expanduser("~/.local/share/twin/history.db")
SOCKET_PATH = "/tmp/hyprtwin.sock"
MAX_HISTORY_ROWS = 100


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


def _get_context_budget() -> dict:
    profile_path = os.path.expanduser("~/.local/share/twin/profile.json")
    try:
        with open(profile_path, "r") as f:
            profile = json.load(f)
            context_size = profile.get("context_size", 4096)
    except (FileNotFoundError, json.JSONDecodeError):
        context_size = 4096

    safe_prompt_tokens = context_size - 1024
    max_total_characters = max(1000, safe_prompt_tokens * 4)

    return {
        "max_tokens": context_size,
        "max_charcater": max_total_charcate,
        "pipe_budget": int(max_total_charcate * 0.7),
        "history_budget": int(max_total_charcate * 0.3),
    }


def get_history(char):
    """Retrieves the last 6 messages to inject as context."""
    conn = init_db()
    c = conn.cursor()
    c.execute("SELECT role, content FROM messages ORDER BY id DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    # Reverse to restore chronological order
    return [{"role": r[0], "content": r[1]} for r in reversed(rows)]


def save_message(role, content):
    """Saves a message to the memory database and prunes old rows."""
    conn = init_db()
    c = conn.cursor()
    c.execute("INSERT INTO messages (role, content) VALUES (?, ?)", (role, content))

    # Prune: keep only the most recent MAX_HISTORY_ROWS rows
    c.execute(
        "DELETE FROM messages WHERE id NOT IN "
        "(SELECT id FROM messages ORDER BY id DESC LIMIT ?)",
        (MAX_HISTORY_ROWS,),
    )
    conn.commit()
    conn.close()


def clear_history():
    """Wipes the database."""
    conn = init_db()
    c = conn.cursor()
    c.execute("DELETE FROM messages")
    conn.commit()
    conn.close()


def _unix_request(method: str, path: str, body: bytes = None, stream: bool = False):
    """Sends an HTTP request through the Unix domain socket.

    Returns an http.client.HTTPResponse that can be iterated for streaming.
    """
    s = sock.socket(sock.AF_UNIX, sock.SOCK_STREAM)
    s.settimeout(300)  # 5-minute timeout for long generations
    s.connect(SOCKET_PATH)

    conn = http.client.HTTPConnection("localhost")
    conn.sock = s

    headers = {"Content-Type": "application/json"} if body else {}
    conn.request(method, path, body=body, headers=headers)
    return conn, conn.getresponse()


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

    payload_bytes = json.dumps(payload).encode("utf-8")

    try:
        conn, response = _unix_request(
            "POST", "/v1/chat/completions", body=payload_bytes, stream=True
        )
    except (ConnectionRefusedError, FileNotFoundError, OSError):
        print(
            "[-] Error: The engine is cold. Run 'twin build' first to boot the server."
        )
        sys.exit(1)

    if response.status >= 400:
        print(
            f"\n[-] Error: The AI engine rejected the request (HTTP {response.status})."
        )
        try:
            error_data = json.loads(response.read().decode("utf-8"))
            print(
                f"[*] Server Response: {error_data.get('error', {}).get('message', '')}"
            )
        except Exception:
            pass
        print(
            "[!] Hint: Your piped file or memory history exceeds the loaded Context Window."
        )
        sys.exit(1)

    print("\n🤖 Twin: ", end="", flush=True)
    full_response = ""
    is_thinking = False

    # Beautiful streaming logic — read line by line from raw HTTP response
    buffer = b""
    while True:
        chunk = response.readline()
        if not chunk:
            break
        buffer += chunk
        if chunk == b"\n":
            line = buffer.strip()
            buffer = b""
            if line:
                decoded = line.decode("utf-8")
                if decoded.startswith("data: ") and decoded != "data: [DONE]":
                    try:
                        data = json.loads(decoded[6:])
                        # Defensively check if 'choices' exists
                        choices = data.get("choices", [])
                        if not choices:
                            continue  # Skip telemetry/eval chunks

                        delta = choices[0].get("delta", {})
                        content = delta.get("content")

                        # Ensure content actually exists and isn't 'None'
                        if content is not None:
                            # Detect start of thought process
                            if "<think>" in content:
                                is_thinking = True
                                content = content.replace("<think>", "")

                            # Detect end of thought process
                            if "</think>" in content:
                                is_thinking = False
                                content = content.replace("</think>", "")

                            # Only print to terminal if it's NOT thinking
                            if not is_thinking and content.strip() != "":
                                print(content, end="", flush=True)

                            full_response += content
                    except Exception:
                        pass
    print("\n")

    # Close the underlying socket connection
    try:
        conn.close()
    except Exception:
        pass

    if not quick:
        # ONLY save the user's actual question, NOT the giant piped_context!
        save_message("user", query)
        save_message("assistant", full_response)
