"""
File and log inspection tools.
find -printf is GNU-specific and NOT available on macOS or Alpine/BusyBox.
This module avoids -printf in all find invocations.
"""
import os
import re
import stat
import subprocess
import time
from tools.base import BaseTool

def _human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n //= 1024
    return f"{n:.1f} PB"

class TailLog(BaseTool):
    name = "tail_log"
    description = (
        "Reads the last N lines of a log file, with optional regex filtering. "
        "Supports common log paths or a custom path. "
        "Also supports journalctl for systemd logs."
    )

    LOG_ALIASES: dict[str, list[str] | None] = {
        "syslog": ["/var/log/syslog", "/var/log/messages"],
        "auth": ["/var/log/auth.log", "/var/log/secure"],
        "kern": ["/var/log/kern.log"],
        "dmesg": None,  # special — uses dmesg binary
    }

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "description": (
                        "Log source. Aliases: 'syslog', 'auth', 'kern', 'dmesg', 'journal'. "
                        "Or an absolute file path like '/var/log/nginx/error.log'."
                    ),
                },
                "lines": {
                    "type": "integer",
                    "description": "Number of lines to return (default 50, max 500)",
                },
                "filter": {
                    "type": "string",
                    "description": "Optional regex pattern to filter lines (case-insensitive)",
                },
                "unit": {
                    "type": "string",
                    "description": "For 'journal' source: systemd unit name (e.g. 'nginx')",
                },
            },
            "required": ["source"],
        }

    def run(
        self,
        source: str,
        lines: int = 50,
        filter: str | None = None,
        unit: str | None = None,
    ) -> dict:
        lines = max(1, min(lines, 500))

        if source == "journal":
            cmd = ["journalctl", "--no-pager", "-n", str(lines), "--output=short-iso"]
            if unit:
                cmd += ["-u", unit]
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
                raw_lines = result.stdout.splitlines()
            except FileNotFoundError:
                return {"error": "journalctl not available on this system."}
            except subprocess.TimeoutExpired:
                return {"error": "journalctl timed out."}

        elif source == "dmesg":
            try:
                result = subprocess.run(
                    ["dmesg", "--time-format=iso"],
                    capture_output=True, text=True, timeout=10,
                )
                raw_lines = result.stdout.splitlines()[-lines:]
            except FileNotFoundError:
                # Fallback: dmesg without --time-format (e.g. macOS)
                try:
                    result = subprocess.run(
                        ["dmesg"], capture_output=True, text=True, timeout=10,
                    )
                    raw_lines = result.stdout.splitlines()[-lines:]
                except Exception as e:
                    return {"error": f"dmesg failed: {e}"}
            except Exception as e:
                return {"error": f"dmesg failed: {e}"}

        else:
            candidates = self.LOG_ALIASES.get(source, [source])
            path = None
            for candidate in (candidates or []):
                if os.path.exists(candidate):
                    path = candidate
                    break

            if not path:
                return {"error": f"Log not found. Tried: {candidates}"}

            try:
                result = subprocess.run(
                    ["tail", "-n", str(lines), path],
                    capture_output=True, text=True, timeout=10,
                )
                raw_lines = result.stdout.splitlines()
            except Exception as e:
                return {"error": f"Failed to read {path}: {e}"}

        if filter:
            try:
                pattern = re.compile(filter, re.IGNORECASE)
                matched = [l for l in raw_lines if pattern.search(l)]
            except re.error as e:
                return {"error": f"Invalid regex: {e}"}
        else:
            matched = raw_lines

        return {
            "source": source,
            "lines_read": len(raw_lines),
            "lines_returned": len(matched),
            "filtered": filter is not None,
            "content": matched,
        }

class FindLargeFiles(BaseTool):
    name = "find_large_files"
    description = (
        "Finds the largest files under a given directory path. "
        "Returns file path, size, and last-modified time. "
        "Useful for diagnosing disk space issues."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory to search (e.g. '/var', '/home'). Default: '/'.",
                },
                "min_size_mb": {
                    "type": "number",
                    "description": "Minimum file size in MB to include (default 100)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results to return (default 20, max 50)",
                },
            },
            "required": [],
        }

    def run(
        self,
        path: str = "/",
        min_size_mb: float = 100,
        limit: int = 20,
    ) -> dict:
        limit = max(1, min(limit, 50))
        min_size_mb = max(0.0, float(min_size_mb))
        min_bytes = int(min_size_mb * 1_048_576)

        # Use `find ... -size +NM` (portable) then stat results ourselves,
        # avoiding GNU-only -printf which breaks on macOS and Alpine/BusyBox.
        threshold_mb = max(0, int(min_size_mb) - 1)
        try:
            result = subprocess.run(
                [
                    "find", path,
                    "-type", "f",
                    "-size", f"+{threshold_mb}M",
                ],
                capture_output=True, text=True, timeout=30,
            )
        except subprocess.TimeoutExpired:
            return {"error": "Search timed out. Try a more specific path."}
        except FileNotFoundError:
            return {"error": "'find' command not available."}

        files: list[dict] = []
        for filepath in result.stdout.splitlines():
            filepath = filepath.strip()
            if not filepath:
                continue
            try:
                s = os.stat(filepath)
                if s.st_size < min_bytes:
                    continue
                files.append({
                    "path": filepath,
                    "size_mb": round(s.st_size / 1_048_576, 1),
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(s.st_mtime)
                    ),
                })
            except (OSError, PermissionError):
                continue

        files.sort(key=lambda x: x["size_mb"], reverse=True)
        return {
            "search_path": path,
            "min_size_mb": min_size_mb,
            "files": files[:limit],
            "total_found": len(files),
        }

class ListDirectory(BaseTool):
    name = "list_directory"
    description = (
        "Lists files and directories at a given path with sizes, permissions, "
        "owner, last modified time, and type. Like 'ls -lah'."
    )

    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to list (e.g. '/etc', '/var/log')",
                },
                "show_hidden": {
                    "type": "boolean",
                    "description": "Include hidden files (dot files). Default false.",
                },
                "sort_by": {
                    "type": "string",
                    "description": "'name', 'size', or 'modified'. Default 'name'.",
                },
            },
            "required": ["path"],
        }

    def run(
        self,
        path: str,
        show_hidden: bool = False,
        sort_by: str = "name",
    ) -> dict:
        import pwd
        import grp

        try:
            entries_raw = list(os.scandir(path))
        except PermissionError:
            return {"error": f"Permission denied: {path}"}
        except FileNotFoundError:
            return {"error": f"Path not found: {path}"}
        except OSError as e:
            return {"error": f"Cannot list {path}: {e}"}

        entries: list[dict] = []
        for e in entries_raw:
            if not show_hidden and e.name.startswith("."):
                continue
            try:
                s = e.stat(follow_symlinks=False)
                mode = stat.filemode(s.st_mode)
                try:
                    owner = pwd.getpwuid(s.st_uid).pw_name
                except KeyError:
                    owner = str(s.st_uid)
                try:
                    group = grp.getgrgid(s.st_gid).gr_name
                except KeyError:
                    group = str(s.st_gid)

                entries.append({
                    "name": e.name,
                    "type": (
                        "dir" if e.is_dir(follow_symlinks=False)
                        else "symlink" if e.is_symlink()
                        else "file"
                    ),
                    "size_bytes": s.st_size,
                    "size_human": _human_size(s.st_size),
                    "permissions": mode,
                    "owner": owner,
                    "group": group,
                    "modified": time.strftime(
                        "%Y-%m-%d %H:%M:%S", time.localtime(s.st_mtime)
                    ),
                })
            except (PermissionError, FileNotFoundError, OSError):
                continue

        sort_key = {"name": "name", "size": "size_bytes", "modified": "modified"}.get(
            sort_by, "name"
        )
        entries.sort(
            key=lambda x: x[sort_key],
            reverse=(sort_by == "size"),
        )

        return {
            "path": path,
            "count": len(entries),
            "entries": entries,
        }