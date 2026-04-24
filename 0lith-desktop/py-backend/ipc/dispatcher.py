"""Command dispatcher — registry of (fn, needs_emit) pairs keyed by command name."""

import traceback
import uuid

import requests

from olith_shared import log_error


class Dispatcher:
    def __init__(self, backend):
        self._backend = backend
        self._registry: dict[str, tuple] = {}

    def register(self, command: str, fn, needs_emit: bool = False) -> None:
        self._registry[command] = (fn, needs_emit)

    def dispatch(self, request: dict, emit) -> dict:
        req_id = request.get("id", str(uuid.uuid4()))
        command = request.get("command", "")

        entry = self._registry.get(command)
        if not entry:
            return {"id": req_id, "status": "error", "message": f"Unknown command: {command}"}

        fn, needs_emit = entry

        def _emit(data: dict) -> None:
            emit({"id": req_id, **data})

        try:
            if needs_emit:
                data = fn(self._backend, request, _emit)
            else:
                data = fn(self._backend, request)
            return {"id": req_id, "status": "ok", **data}
        except requests.exceptions.ConnectionError as e:
            return {"id": req_id, "status": "error", "message": f"Service unavailable: {e}"}
        except requests.exceptions.Timeout as e:
            return {"id": req_id, "status": "error", "message": f"Timeout: {e}"}
        except Exception as e:
            log_error("ipc", f"Command '{command}' failed: {traceback.format_exc()}")
            return {"id": req_id, "status": "error", "message": str(e)}
