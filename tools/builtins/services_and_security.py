import subprocess
import re
from tools.base import BaseTool

class ListServices(BaseTool):
    name = "list_services"
    description = (
        "Lists systemd services and their status. Can filter by state: "
        "'running', 'failed', 'inactive', or 'all'. "
        "Returns unit name, load state, active state, sub-state, and description."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "state": {
                    "type": "string",
                    "description": "'running', 'failed', 'inactive', or 'all' (default 'all')",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default 30, max 100)",
                },
            },
            "required": [],
        }

    def run(self, state: str = "all", limit: int = 30) -> dict:
        limit = min(limit, 100)
        cmd = [
            "systemctl", "list-units", "--type=service",
            "--no-pager", "--no-legend", "--plain",
        ]
        if state != "all":
            cmd += [f"--state={state}"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            return {"error": "systemctl not available. This system may not use systemd."}
        except subprocess.TimeoutExpired:
            return {"error": "systemctl timed out."}

        services = []
        for line in result.stdout.splitlines():
            parts = line.split(None, 4)
            if len(parts) < 4:
                continue
            services.append({
                "unit": parts[0],
                "load": parts[1],
                "active": parts[2],
                "sub": parts[3],
                "description": parts[4] if len(parts) > 4 else "",
            })

        failed = [s for s in services if s["active"] == "failed"]
        return {
            "services": services[:limit],
            "total": len(services),
            "failed_count": len(failed),
            "failed": failed,
        }

class GetServiceStatus(BaseTool):
    name = "get_service_status"
    description = (
        "Returns the detailed status of a specific systemd service: "
        "active state, PID, memory, CPU, recent log lines, and restart count."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Service name (e.g. 'nginx', 'sshd', 'postgresql'). "
                                   ".service suffix is optional.",
                }
            },
            "required": ["name"],
        }

    def run(self, name: str) -> dict:
        if not name.endswith(".service"):
            name = f"{name}.service"
        try:
            result = subprocess.run(
                ["systemctl", "status", name, "--no-pager", "-l"],
                capture_output=True, text=True, timeout=10,
            )
        except FileNotFoundError:
            return {"error": "systemctl not available."}

        output = result.stdout + result.stderr

        def extract(pattern, text, group=1, default=None):
            m = re.search(pattern, text)
            return m.group(group).strip() if m else default

        active_line = extract(r"Active:\s*(.+?)(?:\n|$)", output)
        main_pid = extract(r"Main PID:\s*(\d+)", output)
        memory = extract(r"Memory:\s*(.+?)(?:\n|$)", output)
        cpu = extract(r"CPU:\s*(.+?)(?:\n|$)", output)
        tasks = extract(r"Tasks:\s*(.+?)(?:\n|$)", output)

        return {
            "unit": name,
            "active": active_line,
            "main_pid": int(main_pid) if main_pid else None,
            "memory": memory,
            "cpu": cpu,
            "tasks": tasks,
            "exit_code": result.returncode,
            "is_active": result.returncode == 0,
            "recent_logs": output.splitlines()[-15:],
            "raw": output[:2000],
        }

class GetLoginHistory(BaseTool):
    name = "get_login_history"
    description = (
        "Returns recent login history: user, terminal, source IP, login time, duration. "
        "Also shows currently logged-in users. Useful for auditing access."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "limit": {
                    "type": "integer",
                    "description": "Max login records to return (default 20, max 100)",
                },
                "failed_only": {
                    "type": "boolean",
                    "description": "Only return failed login attempts (via lastb). May require root.",
                },
            },
            "required": [],
        }

    def run(self, limit: int = 20, failed_only: bool = False) -> dict:
        limit = min(limit, 100)
        try:
            who = subprocess.run(["who"], capture_output=True, text=True, timeout=5)
            current_users = [
                {"line": l.strip()} for l in who.stdout.splitlines() if l.strip()
            ]
        except Exception:
            current_users = []

        cmd = ["lastb" if failed_only else "last", "-n", str(limit), "-F"]
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        except FileNotFoundError:
            return {"error": f"{'lastb' if failed_only else 'last'} command not available."}

        records = []
        for line in result.stdout.splitlines():
            if not line.strip() or line.startswith("wtmp") or line.startswith("btmp"):
                continue
            parts = line.split()
            if len(parts) < 3:
                continue
            records.append({
                "user": parts[0],
                "terminal": parts[1] if len(parts) > 1 else None,
                "source": parts[2] if len(parts) > 2 else None,
                "raw": line.strip(),
            })

        return {
            "currently_logged_in": current_users,
            "login_records": records,
            "failed_only": failed_only,
            "count": len(records),
        }

class GetCronJobs(BaseTool):
    name = "get_cron_jobs"
    description = (
        "Lists cron jobs for the current user and system-wide cron entries. "
        "Useful for auditing scheduled tasks and spotting unexpected jobs."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "all_users": {
                    "type": "boolean",
                    "description": "Attempt to read crontabs for all users. Requires root. Default false.",
                }
            },
            "required": [],
        }

    def run(self, all_users: bool = False) -> dict:
        import os
        jobs = {}
        try:
            result = subprocess.run(
                ["crontab", "-l"], capture_output=True, text=True, timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                jobs["current_user"] = _parse_crontab(result.stdout)
        except FileNotFoundError:
            pass

        for cron_dir in ["/etc/cron.d", "/etc/cron.daily", "/etc/cron.hourly",
                         "/etc/cron.weekly", "/etc/cron.monthly"]:
            try:
                files = os.listdir(cron_dir)
                for fname in files:
                    fpath = os.path.join(cron_dir, fname)
                    try:
                        with open(fpath) as f:
                            content = f.read()
                        jobs[f"{cron_dir}/{fname}"] = _parse_crontab(content)
                    except (PermissionError, IsADirectoryError):
                        continue
            except (FileNotFoundError, PermissionError):
                continue

        try:
            with open("/etc/crontab") as f:
                jobs["/etc/crontab"] = _parse_crontab(f.read())
        except (FileNotFoundError, PermissionError):
            pass

        total = sum(len(v) for v in jobs.values())
        return {"cron_jobs": jobs, "total_entries": total}


def _parse_crontab(text: str) -> list[dict]:
    entries = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        entries.append({"entry": stripped})
    return entries