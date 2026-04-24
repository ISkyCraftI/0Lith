def cmd_list_tasks(backend, request: dict) -> dict:
    try:
        from olith_tasks import list_pending_tasks
        tasks = list_pending_tasks()
    except Exception as e:
        return {"tasks": [], "message": str(e)}
    return {"tasks": tasks}


def cmd_resolve_tasks(backend, request: dict) -> dict:
    try:
        from olith_tasks import resolve_completed
        removed = resolve_completed()
    except Exception as e:
        return {"removed": 0, "message": str(e)}
    return {"removed": removed}
