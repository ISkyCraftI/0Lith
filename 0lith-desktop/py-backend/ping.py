#!/usr/bin/env python3
"""Ping-pong minimal pour valider l'IPC Tauri <-> Python."""
import sys
import json

def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
            response = {
                "status": "ok",
                "echo": request.get("message", ""),
                "agent": "hodolith",
                "python_version": sys.version,
            }
            print(json.dumps(response), flush=True)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": str(e)}), flush=True)

if __name__ == "__main__":
    main()
