"""IPC stdin/stdout loop — reads JSON lines, dispatches, writes responses."""

import json
import sys


def run(dispatcher) -> None:
    """Block on sys.stdin, dispatch each JSON line, write the response back."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue

        def emit(data: dict) -> None:
            print(json.dumps(data, ensure_ascii=False), flush=True)

        try:
            request = json.loads(line)
        except json.JSONDecodeError as e:
            print(json.dumps({"status": "error", "message": f"Invalid JSON: {e}"}), flush=True)
            continue

        response = dispatcher.dispatch(request, emit)
        print(json.dumps(response, ensure_ascii=False), flush=True)
