import os
import signal
import time
import psutil
from tools.base import BaseTool

PROTECTED_PID_THRESHOLD = 100
OWN_PID = os.getpid()

def _proc_detail(p: psutil.Process, include_env: bool = False) -> dict:
    """
    Extract rich detail from a process. Returns partial data on AccessDenied.
    NOTE: Does NOT call cpu_percent() with a blocking interval — that would
    add 0.1 s * num_processes latency to list/search calls.
    """
    info: dict = {}
    with p.oneshot():
        try:
            info["pid"] = p.pid
            info["name"] = p.name()
            info["status"] = p.status()
            info["username"] = p.username()
            info["cmdline"] = " ".join(p.cmdline())[:300]
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            info.setdefault("pid", p.pid)

        try:
            mi = p.memory_info()
            info["memory"] = {
                "rss_mb": round(mi.rss / 1_048_576, 1),
                "vms_mb": round(mi.vms / 1_048_576, 1),
                "shared_mb": round(getattr(mi, "shared", 0) / 1_048_576, 1),
                "percent": round(p.memory_percent(), 2),
            }
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            info["memory"] = None

        try:
            # cpu_percent with interval=None returns usage since last call.
            # For search/detail use, we just report the stored value without blocking.
            info["cpu_percent"] = p.cpu_percent(interval=None)
            info["num_threads"] = p.num_threads()
            info["num_fds"] = p.num_fds() if hasattr(p, "num_fds") else None
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        try:
            create_time = p.create_time()
            elapsed = time.time() - create_time
            h, rem = divmod(int(elapsed), 3600)
            m, s = divmod(rem, 60)
            info["uptime"] = f"{h}h {m}m {s}s"
            info["uptime_seconds"] = int(elapsed)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        try:
            parent = p.parent()
            info["parent"] = (
                {"pid": parent.pid, "name": parent.name()} if parent else None
            )
            children = p.children()
            info["children"] = [{"pid": c.pid, "name": c.name()} for c in children]
            info["num_children"] = len(children)
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            info["parent"] = None
            info["children"] = []

        try:
            info["nice"] = p.nice()
            info["ionice"] = str(p.ionice()) if hasattr(p, "ionice") else None
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            pass

        if include_env:
            try:
                info["environ"] = p.environ()
            except (psutil.AccessDenied, psutil.NoSuchProcess):
                info["environ"] = None

    return info

class ListProcesses(BaseTool):
    name = "list_processes"
    description = (
        "Lists running processes sorted by CPU or memory usage. Returns rich detail per process: "
        "threads, file descriptors, uptime, parent/child count, RSS/VMS memory, nice value."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "sort_by": {
                    "type": "string",
                    "description": "'cpu' or 'memory' (default 'cpu')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max processes to return (default 20, max 50)",
                },
                "status_filter": {
                    "type": "string",
                    "description": (
                        "Filter by status: 'running', 'sleeping', 'zombie', etc. Omit for all."
                    ),
                },
            },
            "required": [],
        }

    def run(
        self,
        sort_by: str = "cpu",
        limit: int = 20,
        status_filter: str | None = None,
    ) -> dict:
        limit = max(1, min(limit, 50))
        attrs = [
            "pid", "name", "cpu_percent", "memory_percent", "memory_info",
            "status", "username", "num_threads", "create_time", "nice",
        ]
        procs: list[dict] = []

        for p in psutil.process_iter(attrs):
            try:
                i = p.info
                if status_filter and i.get("status") != status_filter:
                    continue

                mi = i.get("memory_info")
                elapsed = time.time() - (i.get("create_time") or time.time())
                h, rem = divmod(int(elapsed), 3600)
                m, s = divmod(rem, 60)

                try:
                    num_fds = p.num_fds() if hasattr(p, "num_fds") else None
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    num_fds = None

                try:
                    children_count = len(p.children())
                except (psutil.AccessDenied, psutil.NoSuchProcess):
                    children_count = 0

                procs.append({
                    "pid": i["pid"],
                    "name": i["name"],
                    "status": i.get("status"),
                    "username": i.get("username"),
                    # cpu_percent from process_iter attrs is valid (uses cached value).
                    "cpu_percent": i.get("cpu_percent") or 0.0,
                    "memory_percent": round(i.get("memory_percent") or 0.0, 2),
                    "rss_mb": round(mi.rss / 1_048_576, 1) if mi else None,
                    "vms_mb": round(mi.vms / 1_048_576, 1) if mi else None,
                    "num_threads": i.get("num_threads"),
                    "num_fds": num_fds,
                    "num_children": children_count,
                    "nice": i.get("nice"),
                    "uptime": f"{h}h {m}m {s}s",
                })
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        key = "cpu_percent" if sort_by == "cpu" else "memory_percent"
        procs.sort(key=lambda x: x.get(key) or 0.0, reverse=True)

        return {
            "processes": procs[:limit],
            "total_found": len(procs),
            "sorted_by": sort_by,
        }

class SearchProcess(BaseTool):
    name = "search_process"
    description = (
        "Search for processes by name or PID. Returns rich detail per match: "
        "full cmdline, uptime, memory breakdown, threads, file descriptors, "
        "parent/child tree, nice value. Optionally includes environment variables."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Partial or full process name to search for (case-insensitive)",
                },
                "pid": {
                    "type": "integer",
                    "description": "Exact PID to look up",
                },
                "include_env": {
                    "type": "boolean",
                    "description": "Include environment variables (default false, can be large)",
                },
            },
            "required": [],
        }

    def run(
        self,
        name: str | None = None,
        pid: int | None = None,
        include_env: bool = False,
    ) -> dict:
        if not name and pid is None:
            return {"error": "Provide at least one of: name, pid"}

        results: list[dict] = []
        for p in psutil.process_iter(["pid", "name"]):
            try:
                i = p.info
                if pid is not None and i["pid"] != pid:
                    continue
                if name and name.lower() not in (i["name"] or "").lower():
                    continue
                results.append(_proc_detail(p, include_env=include_env))
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return {"matches": results, "count": len(results)}

class KillProcess(BaseTool):
    name = "kill_process"
    description = (
        "Sends SIGTERM to a process by PID. "
        "Refuses to kill system processes (PID < 100) or the agent's own process. "
        "Returns the process name and signal confirmation."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "PID of the process to terminate",
                }
            },
            "required": ["pid"],
        }

    def run(self, pid: int) -> dict:
        if pid < PROTECTED_PID_THRESHOLD:
            return {
                "error": (
                    f"Refused: PID {pid} is below the protected threshold "
                    f"({PROTECTED_PID_THRESHOLD}). "
                    "Terminating system processes could destabilize the OS."
                )
            }
        if pid == OWN_PID:
            return {"error": "Refused: cannot terminate the agent's own process."}

        try:
            proc = psutil.Process(pid)
            name = proc.name()
            username = proc.username()
            proc.send_signal(signal.SIGTERM)
            return {
                "success": True,
                "pid": pid,
                "name": name,
                "username": username,
                "signal": "SIGTERM",
                "note": "Process sent SIGTERM. It may take a moment to exit.",
            }
        except psutil.NoSuchProcess:
            return {"error": f"No process with PID {pid} exists."}
        except psutil.AccessDenied:
            return {
                "error": f"Access denied: insufficient permissions to terminate PID {pid}."
            }

class SetProcessPriority(BaseTool):
    name = "set_process_priority"
    description = (
        "Changes the nice value (scheduling priority) of a process. "
        "Nice values range from -20 (highest priority) to 19 (lowest). "
        "Increasing nice (lowering priority) is always safe. "
        "Decreasing nice (raising priority) requires elevated permissions."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "pid": {
                    "type": "integer",
                    "description": "PID of the process",
                },
                "nice": {
                    "type": "integer",
                    "description": "New nice value (-20 to 19). Use positive values to deprioritize.",
                },
            },
            "required": ["pid", "nice"],
        }

    def run(self, pid: int, nice: int) -> dict:
        if pid < PROTECTED_PID_THRESHOLD:
            return {"error": f"Refused: PID {pid} is a protected system process."}
        if not (-20 <= nice <= 19):
            return {"error": f"Invalid nice value {nice}. Must be between -20 and 19."}

        try:
            proc = psutil.Process(pid)
            old_nice = proc.nice()
            proc.nice(nice)
            return {
                "success": True,
                "pid": pid,
                "name": proc.name(),
                "old_nice": old_nice,
                "new_nice": nice,
            }
        except psutil.NoSuchProcess:
            return {"error": f"No process with PID {pid} exists."}
        except psutil.AccessDenied:
            return {
                "error": "Access denied: raising priority (lower nice) requires root/sudo."
            }